"""
Request and response schemas. Kept in one place so the extension and
tests have one thing to mirror.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class JobCreate(BaseModel):
    video_id: str = Field(..., min_length=5, max_length=20)
    target_lang: str = Field(default="English", min_length=2, max_length=40)


class Segment(BaseModel):
    start: float  # seconds from start of video
    end: float
    original: str
    translation: str


class JobState(BaseModel):
    job_id: str
    video_id: str
    target_lang: str
    status: Literal["pending", "downloading", "transcribing", "done", "failed", "cancelled"]
    # Progress from 0.0 to 1.0. For "transcribing", it's chunks_done / chunks_total.
    progress: float = 0.0
    segments: list[Segment] = []
    error: Optional[str] = None
