"""
Gemini wrapper. One function: transcribe a single audio chunk, return
structured segments with timestamps relative to the chunk.

Retries on transient errors (503). Fails fast on quota (429) because
quota retries just waste more quota.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

from google import genai
from google.genai import types

from schemas import Segment

log = logging.getLogger("gemini")

_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
_client: genai.Client | None = None


class GeminiError(RuntimeError):
    pass


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise GeminiError("GEMINI_API_KEY not set")
        _client = genai.Client(api_key=key)
    return _client


_RESPONSE_SCHEMA = types.Schema(
    type=types.Type.ARRAY,
    items=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "start": types.Schema(type=types.Type.NUMBER),
            "end": types.Schema(type=types.Type.NUMBER),
            "original": types.Schema(type=types.Type.STRING),
            "translation": types.Schema(type=types.Type.STRING),
        },
        required=["start", "end", "original", "translation"],
    ),
)


async def transcribe_chunk(
    chunk_path: Path,
    target_lang: str,
    time_offset_s: float,
    max_attempts: int = 3,
) -> list[Segment]:
    """Upload one chunk, get translated segments. Shifts timestamps by time_offset_s."""
    # genai SDK is sync; run in a thread so we don't block the event loop.
    return await asyncio.to_thread(
        _transcribe_chunk_sync,
        chunk_path,
        target_lang,
        time_offset_s,
        max_attempts,
    )


def _transcribe_chunk_sync(
    chunk_path: Path,
    target_lang: str,
    time_offset_s: float,
    max_attempts: int,
) -> list[Segment]:
    client = _get_client()

    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return _attempt(client, chunk_path, target_lang, time_offset_s)
        except GeminiError:
            raise  # already final
        except Exception as e:
            last_err = e
            msg = str(e)
            # Only retry on 5xx-ish. Quota errors won't clear in seconds.
            if "503" in msg or "UNAVAILABLE" in msg or "500" in msg:
                wait = 2 * attempt
                log.warning("gemini transient error on attempt %d: %s; retrying in %ds", attempt, msg[:200], wait)
                import time as _t
                _t.sleep(wait)
                continue
            raise GeminiError(f"gemini call failed: {msg}") from e

    raise GeminiError(f"gemini failed after {max_attempts} attempts: {last_err}")


def _attempt(
    client: genai.Client,
    chunk_path: Path,
    target_lang: str,
    time_offset_s: float,
) -> list[Segment]:
    uploaded = client.files.upload(file=str(chunk_path))

    prompt = (
        f"Transcribe this audio and translate each segment to {target_lang}.\n\n"
        "Return ONLY a JSON array. Each element is an object with these fields:\n"
        "  - \"start\": start timestamp in seconds (number, can be float)\n"
        "  - \"end\": end timestamp in seconds (number, can be float)\n"
        "  - \"original\": original transcribed text (in the source language)\n"
        f"  - \"translation\": the {target_lang} translation\n\n"
        "Rules:\n"
        "- Segments should be 2-8 seconds long typically.\n"
        "- Align with natural speech pauses.\n"
        "- If there is no speech, return [].\n"
        "- No markdown, no commentary, just the JSON array."
    )

    response = client.models.generate_content(
        model=_MODEL,
        contents=[
            types.Part.from_uri(file_uri=uploaded.uri, mime_type=uploaded.mime_type),
            prompt,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_RESPONSE_SCHEMA,
        ),
    )

    if response.usage_metadata:
        um = response.usage_metadata
        log.info(
            "gemini: chunk=%s offset=%.1fs tokens in=%d out=%d",
            chunk_path.name, time_offset_s,
            um.prompt_token_count or 0, um.candidates_token_count or 0,
        )

    if not response.text:
        raise GeminiError(f"empty response; finish_reason={_finish_reason(response)}")

    try:
        raw = json.loads(response.text)
    except json.JSONDecodeError as e:
        raise GeminiError(f"invalid JSON: {e}; head={response.text[:200]!r}")

    if not isinstance(raw, list):
        raise GeminiError(f"expected JSON array, got {type(raw).__name__}")

    out: list[Segment] = []
    for item in raw:
        try:
            out.append(Segment(
                start=float(item["start"]) + time_offset_s,
                end=float(item["end"]) + time_offset_s,
                original=str(item.get("original", "")),
                translation=str(item.get("translation", "")),
            ))
        except (KeyError, ValueError, TypeError) as e:
            log.warning("skipping malformed segment: %s (%s)", item, e)

    return out


def _finish_reason(response) -> str:
    try:
        return str(response.candidates[0].finish_reason)
    except Exception:
        return "unknown"
