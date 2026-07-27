"""入库编排。上传文件是临时的：解析进数据库主表后即删除。

复用语义（重要）：四类输入都是数据库主表，跨天持久化。
- **某类未上传** → 不动该表，沿用库内已有数据（复用），并在响应中标注 `reused`。
- **某类重新上传** → 按唯一键（工号/流程单号/OA单号/报告日+招聘专员）UPSERT，
  重复数据就地更新（last-wins），不产生重复行；响应标注 `updated`。
任务状态存于 Redis（job_repo）。"""
from __future__ import annotations

from datetime import date
from pathlib import Path
import shutil
import tempfile

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.agents.extraction_agent import ExtractionAgent
from app.core.exceptions import HRAgentError
from app.core.logging import get_logger
from app.models.jobs import JobKind, JobStatus
from app.repositories import clarify_repo, job_repo, report_repo, source_status_repo

log = get_logger("service.ingestion")
_agent = ExtractionAgent()

SOURCE_KEYS = ("employees", "resignations", "agreements", "recruitment")


async def ingest(db: Session, report_date: date, files: dict[str, UploadFile]) -> dict:
    job_id = job_repo.create(JobKind.ingest.value, report_date)
    job_repo.update(job_id, status=JobStatus.running.value)

    tmp = Path(tempfile.mkdtemp(prefix="hr_ingest_"))
    try:
        provided: dict[str, str] = {}
        for key, uf in files.items():
            if uf is None:
                continue
            # combined 或四类源
            if key not in SOURCE_KEYS and key != "combined":
                continue
            safe_name = Path(uf.filename or "").name or "upload.xlsx"
            dest = tmp / f"{key}_{safe_name}"
            with dest.open("wb") as f:
                shutil.copyfileobj(uf.file, f)
            provided[key] = str(dest)

        # 多 sheet 合一：combined 字段，或任一类上传的是合一工作簿
        from app.pipeline.input import workbook_split

        provided = workbook_split.expand_provided_files(provided, tmp)

        # 抽取 Agent：仅写入本次上传的源（其余表保持原样 = 复用）
        # 传入 tmp 目录，使图像转换产生的临时 xlsx 落入同一目录，随后统一清理
        updated_counts = _agent.run(db, report_date, provided, tmp_dir=str(tmp))

        # 汇总：每类源 复用 / 更新 + 当前库内行数
        after = report_repo.count_inputs(db)
        sources: dict[str, dict] = {}
        warnings: list[str] = []
        for key in SOURCE_KEYS:
            if key in provided:
                sources[key] = {"action": "updated", "rows_in_db": after.get(key, 0),
                                "rows_upserted": updated_counts.get(key, 0)}
            else:
                rows = after.get(key, 0)
                sources[key] = {"action": "reused", "rows_in_db": rows, "rows_upserted": None}
                if rows == 0:
                    warnings.append(f"{key}：本次未上传且库内为空")
                else:
                    warnings.append(f"{key}：本次未上传，沿用库内 {rows} 行")

        # 单事务：业务数据（agent 只 flush）+ 上传记录一起提交；
        # 提交成功后才标记 job succeeded，Redis 只是展示缓存、尽力而为。
        source_status_repo.save_db(db, report_date, sources)
        db.commit()
        job_repo.update(job_id, status=JobStatus.succeeded.value,
                        result={"sources": sources, "cleanse": _agent.cleanse_stats})
        try:
            source_status_repo.save(report_date, sources)
        except Exception as exc:  # noqa: BLE001  缓存写失败不改变已提交事实
            log.warning("Redis 上传状态缓存写入失败（不影响已入库数据）：%s", exc)
        return {"job_id": job_id, "status": JobStatus.succeeded.value,
                "counts": {k: after.get(k, 0) for k in SOURCE_KEYS},
                "sources": sources, "warnings": warnings}
    except HRAgentError as exc:
        # 解析层业务错误（表头不符、纳入口径未知类型、图像解析失败等）→
        # 回滚未提交的业务数据，标记 needs_clarification（409），不抛 500
        db.rollback()
        job_repo.update(job_id, status=JobStatus.needs_clarification.value,
                        message=exc.message, result=exc.to_dict())
        # 对 inclusion_filter：把 unknown_types 存入 options，供 orchestration 答复时读取
        import json as _json
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        unknown = detail.get("unknown_types", [])
        options = [_json.dumps({"unknown_types": unknown}, ensure_ascii=False)] if unknown else None
        clarify_repo.add(report_date, exc.code, exc.message, options=options, db=db)
        # needs_clarification 分支也必须满足 IngestResponse 的字段要求（counts 必填），
        # 否则路由层 IngestResponse(**out) 会因缺 counts 抛 pydantic ValidationError，
        # 把本该是"停下来问"的 409 变成一个 500，掩盖了真正的澄清信息。
        return {"job_id": job_id, "status": "needs_clarification",
                "counts": report_repo.count_inputs(db),
                "error": exc.to_dict(), "warnings": [exc.message]}
    except Exception as exc:
        db.rollback()
        job_repo.update(job_id, status=JobStatus.failed.value, message=str(exc))
        raise
    finally:
        # 上传文件是临时的——务必清理
        shutil.rmtree(tmp, ignore_errors=True)
