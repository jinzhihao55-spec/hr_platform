"""人事报表智能体后端的 FastAPI 入口。

流水线：Input -> Cleansing -> (MySQL) -> Calculation -> Export。
Agent（提取 / 计算）负责编排；LLM 的 skill 单独存放在 docs/skills/ 且可选。
任何数字都不由模型产生。
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.database import init_db
from app.core.exceptions import HRAgentError
from app.core.logging import get_logger
from app.api.routes import (
    archive, chat, clarifications, config, context,
    calendar, health, ingestion, jobs, query, reports, runs,
)

log = get_logger("main")


def _assert_deploy_guard() -> None:
    """共享环境硬性前置：忘配 token 不能变成静默裸奔。"""
    if settings.app_env not in ("dev", "local", "test") and not settings.api_auth_token:
        raise RuntimeError(
            f"APP_ENV={settings.app_env} 时必须设置 API_AUTH_TOKEN（由 Nginx/网关注入，"
            "不要写进前端），否则拒绝启动。参见 deploy/nginx.conf。"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("启动人事报表智能体后端 (env=%s)", settings.app_env)
    _assert_deploy_guard()
    try:
        init_db()
    except Exception as exc:  # 开发环境启动时 MySQL 可能不可达
        if settings.app_env in ("dev", "local", "test"):
            log.warning("init_db 跳过/失败: %s", exc)
        else:
            raise
    else:
        try:
            from app.core.database import SessionLocal
            from app.services.publication_service import recover_publication_attempts

            with SessionLocal() as db:
                recover_publication_attempts(db)
        except Exception as exc:
            if settings.app_env in ("dev", "local", "test"):
                log.warning("发布恢复检查失败: %s", exc)
            else:
                raise
    yield


app = FastAPI(title="人事报表智能体 · Backend", version="1.0.0", lifespan=lifespan)


def _cors_origins() -> list[str]:
    """CORS 白名单来自配置（逗号分隔），不允许通配。"""
    return [o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()]


@app.middleware("http")
async def _api_guard(request, call_next):
    """最小 API 守门：上传大小上限 + 共享 token 认证（/health 豁免探活）。

    每次请求读取 settings，便于测试与热更新；token 比较用常量时间。"""
    from fastapi.responses import JSONResponse

    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > settings.max_upload_mb * 1024 * 1024:
        return JSONResponse(
            status_code=413,
            content={"error": "payload_too_large",
                     "message": f"请求体超过 {settings.max_upload_mb}MB 上限"},
        )

    token = settings.api_auth_token
    if (token and request.url.path not in ("/health", "/live", "/ready")
            and request.method != "OPTIONS"):
        import secrets as _secrets

        provided = request.headers.get("x-api-token") or ""
        if not _secrets.compare_digest(provided, token):
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "message": "缺少或错误的 X-API-Token"},
            )
    return await call_next(request)


# CORS 最后注册（最外层），保证 401/413 响应也带 CORS 头
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(chat.router)
app.include_router(ingestion.router)
app.include_router(reports.router)
app.include_router(jobs.router)
app.include_router(query.router)
app.include_router(context.router)
app.include_router(archive.router)
app.include_router(config.router)
app.include_router(clarifications.router)
app.include_router(calendar.router)
app.include_router(runs.router)


@app.exception_handler(HRAgentError)
async def hr_error_handler(_request, exc: HRAgentError):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=409, content=exc.to_dict())
