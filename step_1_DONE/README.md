# CookedTranslate — Step 1

Standalone script that proves the Gemini audio-in pipeline works end-to-end, without any backend or extension.

## Setup

```bash
# 1. Install ffmpeg (system package)
sudo apt install ffmpeg         # Ubuntu
brew install ffmpeg             # macOS

# 2. Python deps
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. API key
export GEMINI_API_KEY=your_actual_key_here
```

## Run

```bash
python step1_transcribe.py p_lmUegdLbY English
```

Or pick any YouTube video ID you want.

## Expected output

A JSON array printed to stdout:

```json
[
  {
    "start": 0.0,
    "end": 3.2,
    "original": "こんにちは、ニュース7です。",
    "translation": "Hello, this is News 7."
  },
  ...
]
```

Token usage is printed to stderr so you can watch your quota burn.

## What we're testing

1. yt-dlp actually downloads audio from YouTube
2. Gemini handles Japanese (or whatever source lang) and produces English
3. Timestamps are usable (non-overlapping, in seconds)
4. Structured output returns valid JSON consistently
5. Quality is actually better than YouTube's built-in auto-translate

## If it breaks

- `yt-dlp failed`: either bad video ID, age-gated video, or yt-dlp needs updating (`pip install -U yt-dlp`)
- `ffmpeg failed`: ffmpeg not installed or not on PATH
- `GEMINI_API_KEY not set`: export the env var
- `429 RESOURCE_EXHAUSTED`: you hit free-tier quota, wait ~1 minute
- `Failed to parse Gemini JSON`: Gemini occasionally ignores the schema. Rerun.
