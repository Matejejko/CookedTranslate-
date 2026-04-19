"""
CookedTranslate - Step 1: standalone transcription+translation script.

Given a YouTube video ID, this script:
  1. Downloads the audio via yt-dlp
  2. Trims to TRIM_SECONDS (default 120) to save quota during dev
  3. Sends to Gemini with a structured-output prompt
  4. Prints a JSON array of {start, end, original, translation} segments

Usage:
    export GEMINI_API_KEY=your_key
    python step1_transcribe.py VIDEO_ID [target_lang]

Example:
    python step1_transcribe.py p_lmUegdLbY English

Requirements:
    pip install -r requirements.txt
    System: ffmpeg (for audio trim). yt-dlp downloads its own binary.

Known limits:
  - Uses Gemini 2.5 Flash-Lite by default (cheapest, works on free tier).
  - No retry logic. First failure just exits. We add retries in step 3.
  - No cache. Every run re-downloads and re-queries Gemini. That's why
    we trim to 2 minutes during dev.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from google import genai
from google.genai import types


# ----- Config -----
MODEL = "gemini-flash-lite-latest"
TRIM_SECONDS = 120  # keep test runs short during dev
AUDIO_FORMAT = "m4a"  # small, well-supported
# ------------------


def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def download_audio(video_id: str, out_path: Path) -> None:
    """Use yt-dlp to grab audio only. Requires yt-dlp on PATH."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = [
        "yt-dlp",
        "-f", "bestaudio",
        "-x",  # extract audio
        "--audio-format", AUDIO_FORMAT,
        "--audio-quality", "5",  # mid quality; Gemini downsamples to 16kbps anyway
        "-o", str(out_path.with_suffix("")) + ".%(ext)s",
        "--no-playlist",
        url,
    ]
    print(f"[1/3] Downloading audio from {url}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        die(f"yt-dlp failed:\n{result.stderr}")


def trim_audio(in_path: Path, out_path: Path, seconds: int) -> None:
    """Trim audio to first N seconds with ffmpeg. Re-encodes to be safe."""
    print(f"[2/3] Trimming to first {seconds}s...")
    cmd = [
        "ffmpeg",
        "-y",  # overwrite
        "-i", str(in_path),
        "-t", str(seconds),
        "-c:a", "aac",
        "-b:a", "64k",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        die(f"ffmpeg failed:\n{result.stderr}")


def transcribe_and_translate(audio_path: Path, target_lang: str) -> list[dict]:
    """Send audio to Gemini, get back timestamped segments with translation."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        die("GEMINI_API_KEY not set in environment")

    client = genai.Client(api_key=api_key)

    print(f"[3/3] Uploading {audio_path.stat().st_size / 1024:.1f} KB to Gemini...")
    uploaded = client.files.upload(file=str(audio_path))

    prompt = f"""Transcribe this audio and translate each segment to {target_lang}.

Return ONLY a JSON array. Each element is an object with these fields:
  - "start": start timestamp in seconds (number, can be float)
  - "end": end timestamp in seconds (number, can be float)
  - "original": the original transcribed text (string, in the source language)
  - "translation": the {target_lang} translation (string)

Rules:
- Segment boundaries should roughly align with natural speech pauses.
- Segments should be 2-8 seconds long typically.
- Do not merge unrelated utterances into one segment.
- Do not include any text outside the JSON array.
- Do not wrap in markdown code fences.
- If there is no speech, return an empty array: []
"""

    # Structured output via response_schema - forces valid JSON without regex parsing.
    response_schema = types.Schema(
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

    response = client.models.generate_content(
        model=MODEL,
        contents=[
            types.Part.from_uri(file_uri=uploaded.uri, mime_type=uploaded.mime_type),
            prompt,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=response_schema,
        ),
    )

    # Log usage so we can track quota burn during dev.
    if response.usage_metadata:
        um = response.usage_metadata
        print(
            f"    tokens: input={um.prompt_token_count} "
            f"output={um.candidates_token_count} "
            f"total={um.total_token_count}",
            file=sys.stderr,
        )

    if not response.text:
        die(f"Gemini returned no text. Full response: {response}")

    try:
        segments = json.loads(response.text)
    except json.JSONDecodeError as e:
        die(f"Failed to parse Gemini JSON: {e}\nRaw: {response.text[:500]}")

    if not isinstance(segments, list):
        die(f"Gemini returned non-list: {type(segments)}")

    return segments


def main() -> None:
    if len(sys.argv) < 2:
        die("Usage: python step1_transcribe.py VIDEO_ID [target_lang]")

    video_id = sys.argv[1]
    target_lang = sys.argv[2] if len(sys.argv) > 2 else "English"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        raw_audio = tmp / f"audio.{AUDIO_FORMAT}"
        trimmed = tmp / "trimmed.m4a"

        download_audio(video_id, raw_audio)
        if not raw_audio.exists():
            # yt-dlp sometimes writes to a slightly different filename
            # (e.g. .m4a.m4a). Find it.
            found = list(tmp.glob(f"audio*"))
            if not found:
                die(f"No audio file found in {tmp}")
            raw_audio = found[0]

        trim_audio(raw_audio, trimmed, TRIM_SECONDS)
        segments = transcribe_and_translate(trimmed, target_lang)

    print(json.dumps(segments, ensure_ascii=False, indent=2))
    print(f"\n--- {len(segments)} segments ---", file=sys.stderr)


if __name__ == "__main__":
    main()
