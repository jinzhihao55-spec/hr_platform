"""任务类型 / 状态枚举。任务状态存于 Redis（见 app/repositories/job_repo.py），
不落 MySQL，故此处仅保留枚举，无 ORM 表。"""
import enum


class JobKind(str, enum.Enum):
    ingest = "ingest"
    daily = "daily"
    weekly = "weekly"


class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    needs_clarification = "needs_clarification"
    blocked = "blocked"        # 校验硬阻断
    succeeded = "succeeded"
    failed = "failed"
