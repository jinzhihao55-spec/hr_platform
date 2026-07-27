import tempfile
from pathlib import Path

from fastapi import APIRouter

from app.config import settings

from app.core.redis_client import get_redis
from app.llm.llm_client import get_llm_client

router = APIRouter(tags=["health"])


def _mysql_ok() -> bool:
    try:
        from sqlalchemy import text

        from app.core.database import SessionLocal

        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _redis_ok() -> bool:
    try:
        get_redis().ping()
        return True
    except Exception:
        return False


def _migration_ok() -> bool:
    try:
        from sqlalchemy import inspect

        from app.core.database import engine

        required = {
            "report_runs": {"source_bundle_hash", "baseline_report_id"},
            "run_sources": {"sha256", "schema_version", "parse_status"},
            "run_report_targets": {"preview_hash", "validation_summary"},
            "published_reports": {"snapshot_hash", "is_current", "version"},
            "report_artifacts": {"protected_path", "sha256"},
            "publication_attempts": {"status", "staging_path", "final_path"},
        }
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        if not set(required).issubset(table_names):
            return False
        inspected_columns = {
            table: {
                column["name"]: column
                for column in inspector.get_columns(table)
            }
            for table in required
        }
        if not all(
            columns.issubset(inspected_columns[table])
            for table, columns in required.items()
        ):
            return False
        snapshot_type = inspected_columns["published_reports"]["snapshot_json"][
            "type"
        ]
        return snapshot_type.__class__.__name__.casefold() == "longtext"
    except Exception:
        return False


def _output_ok() -> bool:
    try:
        output = Path(settings.output_dir)
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=output, prefix=".ready-", delete=True):
            pass
        return True
    except Exception:
        return False


def _config_ok() -> bool:
    if settings.app_env in ("dev", "local", "test"):
        return True
    return bool(
        settings.api_auth_token
        and settings.mysql_password
        and settings.redis_password
        and settings.person_key_secret
    )


@router.get("/health")
def health() -> dict:
    """依赖任一不可用时 status=degraded——不得报假健康（保留 200 兼容现有前端）。"""
    mysql_ok = _mysql_ok()
    redis_ok = _redis_ok()
    return {
        "status": "ok" if (mysql_ok and redis_ok) else "degraded",
        "mysql": mysql_ok,
        "redis": redis_ok,
        "llm_enabled": get_llm_client().enabled,
    }


@router.get("/live")
def live() -> dict:
    """存活探针：进程活着即 200，不查依赖。"""
    return {"status": "alive"}


@router.get("/ready")
def ready():
    """就绪探针验证依赖、迁移、输出目录和生产配置。"""
    from fastapi.responses import JSONResponse

    mysql_ok = _mysql_ok()
    redis_ok = _redis_ok()
    migration_ok = _migration_ok() if mysql_ok else False
    output_ok = _output_ok()
    config_ok = _config_ok()
    payload = {
        "mysql": mysql_ok,
        "redis": redis_ok,
        "migration": migration_ok,
        "output": output_ok,
        "config": config_ok,
    }
    if all(payload.values()):
        return {"status": "ready", **payload}
    return JSONResponse(status_code=503, content={"status": "not_ready", **payload})
