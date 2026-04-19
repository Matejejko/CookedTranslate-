# CookedTranslate

CookedTranslate is an experimental YouTube translation project.

Current repository state:
- **Active code:** a Python/FastAPI backend (`backend/`) that processes YouTube audio in chunks and returns timestamped translated segments.
- **Legacy prototypes:** early extension/API experiments are kept in `OLD/`.
- **Design docs/assets:** roadmap files and architecture/request-flow SVGs in the repo root.

---

## What it does (today)

The backend provides an async job API:
- `POST /jobs` — create or reuse a translation job
- `GET /jobs/{job_id}` — poll status/progress/segments
- `DELETE /jobs/{job_id}` — cancel job
- `GET /health` — liveness check

Pipeline flow (from `backend/pipeline.py`):
1. Download YouTube audio
2. Probe duration and split into chunks (default `30s`)
3. Transcribe + translate chunks via Gemini in parallel (default concurrency `3`)
4. Emit chunk results in-order so client-side playback remains stable
5. Clean up temporary files

Job state is **in-memory only** (`backend/jobs.py`), so restart clears all jobs.

---

## Repository structure

```text
.
├── backend/                       # Active FastAPI backend
│   ├── app.py                     # API entrypoint
│   ├── pipeline.py                # End-to-end async pipeline
│   ├── gemini_client.py           # Gemini integration
│   ├── audio.py                   # ffmpeg/ffprobe helpers
│   ├── jobs.py                    # In-memory job registry
│   ├── schemas.py                 # Pydantic request/response models
│   ├── requirements.txt
│   ├── env.example
│   └── README.md                  # Backend-focused usage notes
├── OLD/                           # Earlier prototypes and experiments
├── ROADMAP.md                     # Project roadmap
├── cookedtranslate_architecture.svg
└── cookedtranslate_request_flow.svg
```

---

## Backend setup

From `/home/runner/work/CookedTranslate/CookedTranslate/backend`:

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=your_key
uvicorn app:app --reload --port 8000
```

Environment variables (`backend/env.example`):
- `GEMINI_API_KEY` (required)
- `GEMINI_MODEL` (default: `gemini-flash-lite-latest`)
- `CHUNK_SECONDS` (default: `30`)
- `MAX_PARALLEL` (default: `3`)

Dependencies (current): FastAPI, Uvicorn, Pydantic, google-genai, yt-dlp.

---

## Quick API usage

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"video_id":"w-u_NrA9owA","target_lang":"English"}'
```

Then poll:

```bash
curl http://localhost:8000/jobs/<job_id>
```

---

## Important notes / current limits

- No persistent storage yet (jobs vanish on restart)
- No cache layer yet
- No auth/rate limiting yet
- CORS is open (`*`) for development
- The backend currently imports `ytdl` (`from ytdl import ...`) but no `backend/ytdl.py` file exists in this snapshot, so backend execution requires restoring/adding that module

---

## Project status

This repo is in an active prototyping phase: backend pipeline is present, while extension/productization work is planned in `ROADMAP.md`.
