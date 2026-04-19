"""
The pipeline. Runs asynchronously for one job.

Stages:
  1. Download audio (yt-dlp)
  2. Chunk it (ffmpeg)
  3. Fan out: transcribe N chunks in parallel, cap concurrency
  4. As each chunk returns, append segments to the job store so the
     client can poll and see them stream in.
  5. Clean up temp files aggressively.

On cancellation: asyncio.CancelledError propagates, cleanup runs in
the finally block.
"""

import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path

from audio import chunk_audio, probe_duration
from gemini_client import GeminiError, transcribe_chunk
from jobs import Job, JobStatus, JobStore
from schemas import Segment
from ytdl import YtdlError, download_audio

log = logging.getLogger("pipeline")

CHUNK_SECONDS = int(os.environ.get("CHUNK_SECONDS", "30"))
MAX_PARALLEL = int(os.environ.get("MAX_PARALLEL", "3"))


async def run_pipeline(job: Job, store: JobStore) -> None:
    tmp_root = Path(tempfile.mkdtemp(prefix=f"ct_{job.job_id}_"))
    try:
        await _run(job, store, tmp_root)
    except asyncio.CancelledError:
        log.info("job %s cancelled", job.job_id)
        raise
    except Exception as e:
        log.exception("job %s failed", job.job_id)
        store.set_failed(job.job_id, f"{type(e).__name__}: {e}")
    finally:
        # Always nuke temp dir. Audio never lingers on disk.
        shutil.rmtree(tmp_root, ignore_errors=True)
        log.info("cleaned up %s", tmp_root)


async def _run(job: Job, store: JobStore, tmp_root: Path) -> None:
    # --- download ---
    store.update_status(job.job_id, JobStatus.DOWNLOADING, progress=0.0)
    audio_path = tmp_root / "audio"
    try:
        audio_file = await download_audio(job.video_id, audio_path)
    except YtdlError as e:
        store.set_failed(job.job_id, f"download failed: {e}")
        return

    duration = await probe_duration(audio_file)
    log.info("job %s: %.1fs audio", job.job_id, duration)

    # --- chunk ---
    store.update_status(job.job_id, JobStatus.TRANSCRIBING, progress=0.0)
    chunks_dir = tmp_root / "chunks"
    chunks = await chunk_audio(audio_file, chunks_dir, CHUNK_SECONDS)

    # We don't need the original audio anymore.
    audio_file.unlink(missing_ok=True)

    # --- fan out ---
    semaphore = asyncio.Semaphore(MAX_PARALLEL)
    total = len(chunks)
    done_count = 0
    # Lock to serialize the "append this chunk's segments and bump progress"
    # step so segments stay in chunk order even when calls finish out of order.
    completed_chunks: dict[int, list[Segment]] = {}
    next_to_emit = 0
    emit_lock = asyncio.Lock()

    async def process_one(idx: int, chunk_path: Path) -> None:
        nonlocal done_count, next_to_emit
        async with semaphore:
            offset = idx * CHUNK_SECONDS
            try:
                segments = await transcribe_chunk(chunk_path, job.target_lang, float(offset))
            except GeminiError as e:
                log.error("chunk %d failed: %s", idx, e)
                segments = []  # soft-fail: keep going, one bad chunk shouldn't kill the job

        # Delete this chunk's file as soon as it's processed.
        chunk_path.unlink(missing_ok=True)

        async with emit_lock:
            completed_chunks[idx] = segments
            # Emit any contiguous prefix of completed chunks so segments
            # appear in order.
            while next_to_emit in completed_chunks:
                segs = completed_chunks.pop(next_to_emit)
                done_count_local = next_to_emit + 1
                progress = done_count_local / total
                store.append_segments(job.job_id, segs, progress)
                log.info("job %s: emitted chunk %d/%d (+%d segs)",
                         job.job_id, done_count_local, total, len(segs))
                next_to_emit += 1
            done_count += 1

    tasks = [asyncio.create_task(process_one(i, p)) for i, p in enumerate(chunks)]
    await asyncio.gather(*tasks)

    store.update_status(job.job_id, JobStatus.DONE, progress=1.0)
    log.info("job %s done: %d total segments", job.job_id,
             len(store.get(job.job_id).segments))
