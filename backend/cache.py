"""
SQLite-backed cache of completed translations.

Key insight: translation is deterministic for a given (video, language,
pipeline_version). If we've translated it once, we never need to hit
Gemini again unless the prompt/model/chunk-size changes — at which point
we bump PIPELINE_VERSION and old entries become unreachable.

This module is sync. Callers MUST run cache calls via asyncio.to_thread()
so the event loop isn't blocked on disk I/O.

Schema is created on init(). Eviction is best-effort LRU by total bytes,
checked after every put().
"""

import json
import logging
import os
import sqlite3
import time
from pathlib import Path

from schemas import Segment

log = logging.getLogger("cache")

# Bump this integer ANY time something that affects translation output
# changes: prompt wording in gemini_client.py, the model, chunk size,
# segment overlap rules, etc. All cached entries written with an older
# version become invisible to get() and will be evicted by LRU eventually.
PIPELINE_VERSION = 1

_DB_PATH = Path(os.environ.get("CACHE_DB_PATH", "./cookedtranslate.db"))
_MAX_BYTES = int(os.environ.get("CACHE_MAX_BYTES", str(500 * 1024 * 1024)))  # 500 MB

_SCHEMA = """
CREATE TABLE IF NOT EXISTS translations (
    video_id         TEXT    NOT NULL,
    target_lang      TEXT    NOT NULL,
    pipeline_version INTEGER NOT NULL,
    segments_json    TEXT    NOT NULL,
    created_at       INTEGER NOT NULL,
    last_accessed    INTEGER NOT NULL,
    bytes            INTEGER NOT NULL,
    PRIMARY KEY (video_id, target_lang, pipeline_version)
);
CREATE INDEX IF NOT EXISTS idx_last_accessed
    ON translations (last_accessed);
"""


def _connect() -> sqlite3.Connection:
    """Open a fresh connection. Cheap; sqlite3 connections are not heavy."""
    conn = sqlite3.connect(_DB_PATH, timeout=10.0)
    # WAL lets readers proceed while a write is in flight. Cheap, sane default.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init() -> None:
    """Create the database file and schema if they don't exist. Call once at startup."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(_SCHEMA)
    log.info("cache initialized at %s (max %d MB, pipeline_version=%d)",
             _DB_PATH, _MAX_BYTES // (1024 * 1024), PIPELINE_VERSION)


def get(video_id: str, target_lang: str) -> list[Segment] | None:
    """Return cached segments for this (video, lang) at the current pipeline version,
    or None on miss. Updates last_accessed on hit so LRU works."""
    now = int(time.time())
    with _connect() as conn:
        row = conn.execute(
            "SELECT segments_json FROM translations "
            "WHERE video_id = ? AND target_lang = ? AND pipeline_version = ?",
            (video_id, target_lang, PIPELINE_VERSION),
        ).fetchone()
        if row is None:
            return None

        # Bump last_accessed for LRU. Best-effort; failure here shouldn't
        # break the read.
        try:
            conn.execute(
                "UPDATE translations SET last_accessed = ? "
                "WHERE video_id = ? AND target_lang = ? AND pipeline_version = ?",
                (now, video_id, target_lang, PIPELINE_VERSION),
            )
            conn.commit()
        except sqlite3.Error as e:
            log.warning("failed to update last_accessed: %s", e)

    raw = json.loads(row[0])
    return [Segment(**item) for item in raw]


def put(video_id: str, target_lang: str, segments: list[Segment]) -> None:
    """Write segments to cache. No-op if segments is empty (don't cache failures)."""
    if not segments:
        log.debug("not caching empty segments for %s (%s)", video_id, target_lang)
        return

    payload = json.dumps([s.model_dump() for s in segments], ensure_ascii=False)
    payload_bytes = len(payload.encode("utf-8"))
    now = int(time.time())

    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO translations "
            "(video_id, target_lang, pipeline_version, segments_json, "
            " created_at, last_accessed, bytes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (video_id, target_lang, PIPELINE_VERSION, payload, now, now, payload_bytes),
        )
        conn.commit()
    log.info("cached %s (%s): %d segments, %d KB",
             video_id, target_lang, len(segments), payload_bytes // 1024)

    _evict_if_needed()


def _evict_if_needed() -> None:
    """If total bytes > _MAX_BYTES, delete oldest-by-last_accessed until under.
    Runs in its own connection/transaction so partial failure doesn't corrupt state."""
    with _connect() as conn:
        total = conn.execute(
            "SELECT COALESCE(SUM(bytes), 0) FROM translations"
        ).fetchone()[0]

        if total <= _MAX_BYTES:
            return

        log.info("cache over budget: %d > %d, evicting", total, _MAX_BYTES)
        # Delete oldest entries until we're under budget. Doing it in a
        # loop instead of one DELETE-with-LIMIT-by-cumulative-sum because
        # SQLite doesn't have window functions in older versions and the
        # loop is fine — eviction is rare.
        evicted = 0
        while total > _MAX_BYTES:
            row = conn.execute(
                "SELECT video_id, target_lang, pipeline_version, bytes "
                "FROM translations ORDER BY last_accessed ASC LIMIT 1"
            ).fetchone()
            if row is None:
                break  # empty table somehow; bail
            vid, lang, ver, b = row
            conn.execute(
                "DELETE FROM translations "
                "WHERE video_id = ? AND target_lang = ? AND pipeline_version = ?",
                (vid, lang, ver),
            )
            total -= b
            evicted += 1
        conn.commit()
        log.info("evicted %d entries; total now %d bytes", evicted, total)
