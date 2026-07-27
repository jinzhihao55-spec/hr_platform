"""API 守门：token 认证、CORS 白名单、上传大小上限。"""
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app, _cors_origins

client = TestClient(app)


def test_cors_default_is_not_wildcard():
    origins = _cors_origins()
    assert origins
    assert "*" not in origins


def test_requests_require_token_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "api_auth_token", "secret-token")

    assert client.get("/openapi.json").status_code == 401
    assert client.get(
        "/openapi.json", headers={"X-API-Token": "secret-token"}
    ).status_code == 200
    # 探活豁免：负载均衡/监控不带 token
    assert client.get("/health").status_code == 200


def test_auth_disabled_when_token_empty(monkeypatch):
    monkeypatch.setattr(settings, "api_auth_token", "")

    assert client.get("/openapi.json").status_code == 200


def test_oversized_upload_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "api_auth_token", "")
    monkeypatch.setattr(settings, "max_upload_mb", 1)

    response = client.post("/ingest", content=b"x" * (2 * 1024 * 1024))

    assert response.status_code == 413


def test_prod_startup_requires_auth_token(monkeypatch):
    """APP_ENV=prod 且 token 为空必须拒绝启动——忘配不能变成静默裸奔。"""
    import pytest as _pytest

    from app.main import _assert_deploy_guard

    monkeypatch.setattr(settings, "app_env", "prod")
    monkeypatch.setattr(settings, "api_auth_token", "")
    with _pytest.raises(RuntimeError):
        _assert_deploy_guard()

    monkeypatch.setattr(settings, "api_auth_token", "tok")
    _assert_deploy_guard()

    monkeypatch.setattr(settings, "app_env", "dev")
    monkeypatch.setattr(settings, "api_auth_token", "")
    _assert_deploy_guard()


def test_staging_and_uat_startup_require_auth_token(monkeypatch):
    """共享测试环境也不能因为不是 prod 就静默关闭鉴权。"""
    import pytest as _pytest

    from app.main import _assert_deploy_guard

    monkeypatch.setattr(settings, "api_auth_token", "")
    for app_env in ("staging", "uat"):
        monkeypatch.setattr(settings, "app_env", app_env)
        with _pytest.raises(RuntimeError):
            _assert_deploy_guard()


def test_month_opening_actor_is_verified_by_proxy_identity(monkeypatch):
    """共享环境只能由网关识别且列入白名单的 HR 用户确认月初基线。"""
    import pytest as _pytest
    from fastapi import HTTPException
    from starlette.requests import Request

    from app.api.routes.reports import _month_opening_actor

    def request_for(user: str | None):
        headers = [] if user is None else [(b"x-authenticated-user", user.encode())]
        return Request({"type": "http", "method": "POST", "path": "/", "headers": headers})

    monkeypatch.setattr(settings, "app_env", "staging")
    monkeypatch.setattr(settings, "month_opening_allowed_users", "hr-a,hr-b", raising=False)
    assert _month_opening_actor(request_for("hr-a"), "spoofed") == "hr-a"

    for user in (None, "student-a"):
        with _pytest.raises(HTTPException) as caught:
            _month_opening_actor(request_for(user), "spoofed")
        assert caught.value.status_code == 403
