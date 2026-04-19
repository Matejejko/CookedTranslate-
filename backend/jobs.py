"""
In-memory job registry. Holds per-job state plus the asyncio.Task running
the pipeline, so we can cancel it cleanly.

Not persistent. Restart = all jobs lost. Good enough for dev.
"""

import asyncio
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from schemas import JobState, Segment


class JobStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    job_id: str
    video_id: str
    target_lang: str
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    segments: list[Segment] = field(default_factory=list)
    error: Optional[str] = None
    task: Optional[asyncio.Task] = None

    def to_state(self) -> JobState:
        return JobState(
            job_id=self.job_id,
            video_id=self.video_id,
            target_lang=self.target_lang,
            status=self.status.value,
            progress=self.progress,
            segments=list(self.segments),
            error=self.error,
        )


class JobStore:
    """Thread-safe job registry.

    FastAPI + asyncio means we're single-threaded per event loop, but the
    pipeline may offload CPU work to thread pools (ffmpeg etc.), so we
    lock when mutating shared job state from those workers.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, video_id: str, target_lang: str) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(job_id=job_id, video_id=video_id, target_lang=target_lang)
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def find_live(self, video_id: str, target_lang: str) -> Optional[Job]:
        """Return an existing non-terminal job for this (video, lang), if any."""
        with self._lock:
            for job in self._jobs.values():
                if (
                    job.video_id == video_id
                    and job.target_lang == target_lang
                    and job.status not in (JobStatus.FAILED, JobStatus.CANCELLED)
                ):
                    return job
        return None

    def attach_task(self, job_id: str, task: asyncio.Task) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].task = task

    def cancel(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = JobStatus.CANCELLED
            if job.task and not job.task.done():
                job.task.cancel()

    def update_status(self, job_id: str, status: JobStatus, progress: float | None = None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = status
            if progress is not None:
                job.progress = progress

    def append_segments(self, job_id: str, segments: list[Segment], progress: float) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.segments.extend(segments)
            job.progress = progress

    def set_failed(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = JobStatus.FAILED
            job.error = error

    def active_tasks(self) -> list[asyncio.Task]:
        with self._lock:
            return [j.task for j in self._jobs.values() if j.task and not j.task.done()]
