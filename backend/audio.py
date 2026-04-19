"""
Audio manipulation via ffmpeg.

- probe_duration: how long is this file?
- chunk_audio:    split a file into N-second pieces on disk.
"""

import asyncio
import json
import logging
from pathlib import Path

log = logging.getLogger("audio")


class FfmpegError(RuntimeError):
    pass


async def probe_duration(path: Path) -> float:
    """Return duration in seconds. Uses ffprobe (ships with ffmpeg)."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise FfmpegError(f"ffprobe exit {proc.returncode}: {stderr.decode(errors='replace')[:300]}")

    info = json.loads(stdout.decode())
    return float(info["format"]["duration"])


async def chunk_audio(src: Path, out_dir: Path, chunk_seconds: int) -> list[Path]:
    """
    Split src into fixed-length chunks: chunk_000.m4a, chunk_001.m4a, ...
    Returns the list of chunk paths in order.

    We re-encode to a low-bitrate mono AAC so upload payloads are small.
    Gemini downsamples to 16kbps internally anyway.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "chunk_%03d.m4a")

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(src),
        "-f", "segment",
        "-segment_time", str(chunk_seconds),
        "-ac", "1",           # mono
        "-c:a", "aac",
        "-b:a", "48k",
        "-reset_timestamps", "1",
        pattern,
    ]

    log.info("chunking %s into %ds pieces", src.name, chunk_seconds)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise FfmpegError(
            f"ffmpeg chunking failed (exit {proc.returncode}): "
            f"{stderr.decode(errors='replace')[:500]}"
        )

    chunks = sorted(out_dir.glob("chunk_*.m4a"))
    if not chunks:
        raise FfmpegError("ffmpeg produced no chunks")
    log.info("chunked into %d pieces", len(chunks))
    return chunks
