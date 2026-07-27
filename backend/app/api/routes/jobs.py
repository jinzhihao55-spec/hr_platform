from fastapi import APIRouter, HTTPException

from app.repositories import job_repo
from app.schemas.api import JobOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str):
    job = job_repo.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    return JobOut(**job)


@router.get("", response_model=list[JobOut])
def list_jobs():
    return [JobOut(**j) for j in job_repo.list_recent(50)]
