"""
FastAPI entry point.

Endpoints:
    POST   /jobs                    create a new translation job
    GET    /jobs/{job_id}           poll for status + ready segments
    DELETE /jobs/{job_id}           cancel an in-flight job
    GET    /health                  liveness probe
"""
import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from dotenv import load_dotenv
load_dotenv()

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from jobs import JobStore, JobStatus
from pipeline import run_pipeline
from schemas import JobCreate, JobState
import cache

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("app")

store = JobStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("backend starting")
    cache.init()
    yield
    log.info("backend shutting down; cancelling %d active jobs", len(store.active_tasks()))
    for task in store.active_tasks():
        task.cancel()


from fastapi.responses import JSONResponse

class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"

app = FastAPI(title="CookedTranslate Backend", lifespan=lifespan, default_response_class=UTF8JSONResponse)

# The extension runs on youtube.com and calls us cross-origin. During dev
# allow everything; tighten in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.post("/jobs", response_model=JobState)
async def create_job(req: JobCreate) -> JobState:
    # If a job for the same (videoId, targetLang) already exists and isn't
    # failed, return it instead of starting a duplicate. Poor man's dedup;
    # a real cache comes later.
    existing = store.find_live(req.video_id, req.target_lang)
    if existing:
        log.info("reusing existing job %s for %s", existing.job_id, req.video_id)
        return existing.to_state()

    # Cache check: hit means we synthesize a "done" job and skip the pipeline.
    cached = await asyncio.to_thread(cache.get, req.video_id, req.target_lang)
    if cached is not None:
        job = store.create(req.video_id, req.target_lang)
        store.append_segments(job.job_id, cached, progress=1.0)
        store.update_status(job.job_id, JobStatus.DONE, progress=1.0)
        log.info("cache hit for %s (%s): %d segments",
            req.video_id, req.target_lang, len(cached))
        return job.to_state()

    job = store.create(req.video_id, req.target_lang)
    task = asyncio.create_task(
        run_pipeline(job, store),
        name=f"pipeline-{job.job_id}",
    )
    store.attach_task(job.job_id, task)
    log.info("created job %s for video %s -> %s", job.job_id, req.video_id, req.target_lang)
    return job.to_state()


@app.get("/jobs/{job_id}", response_model=JobState)
async def get_job(job_id: str) -> JobState:
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job.to_state()


@app.delete("/jobs/{job_id}")
async def cancel_job(job_id: str) -> dict:
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED):
        return {"status": job.status.value, "noop": True}

    store.cancel(job_id)
    log.info("cancelled job %s", job_id)
    return {"status": "cancelled"}
