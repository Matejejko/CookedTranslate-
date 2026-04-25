"""
yt-dlp wrapper. Calls yt-dlp as a subprocess via `python -m yt_dlp` so it
works regardless of PATH on Windows/macOS/Linux.
"""

import asyncio
import logging
import sys
from pathlib import Path

log = logging.getLogger("ytdl")


class YtdlError(RuntimeError):
    pass


async def download_audio(video_id: str, out_path: Path) -> Path:
    """Download best audio track to out_path (as .m4a). Returns the final path."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    # yt-dlp substitutes %(ext)s with the actual extension it chose.
    # We force m4a to keep things predictable.
    output_template = str(out_path.with_suffix("")) + ".%(ext)s"

    cmd = [
        sys.executable,
        "-m", "yt_dlp",
        "-f", "bestaudio",
        "-x",  # extract audio
        "--audio-format", "m4a",
        "--audio-quality", "5",
        "-o", output_template,
        "--no-playlist",
        "--quiet",
        "--no-warnings",
        url,
    ]

    log.info("yt-dlp downloading %s -> %s", video_id, out_path)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise YtdlError(
            f"yt-dlp exit {proc.returncode}: {stderr.decode(errors='replace')[:500]}"
        )

    # yt-dlp writes to <stem>.m4a. Find it.
    final = out_path.with_suffix(".m4a")
    if not final.exists():
        # Fallback: look for anything yt-dlp wrote to the same dir with our stem.
        candidates = list(out_path.parent.glob(f"{out_path.stem}.*"))
        if not candidates:
            raise YtdlError(f"yt-dlp reported success but no file at {final}")
        final = candidates[0]

    log.info("yt-dlp done: %s (%d KB)", final, final.stat().st_size // 1024)
    return final
