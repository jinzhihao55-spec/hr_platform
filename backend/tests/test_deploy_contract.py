"""Single-user deployment contract tests.

These tests are intentionally static where possible so a developer can validate
the security boundary without a running Docker daemon.
"""

from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path

import pytest

from app.config import Settings


ROOT = Path(__file__).resolve().parents[1]


def _context_root(test_name: str, compose_name: str, default: Path) -> Path:
    raw = os.getenv(test_name) or os.getenv(compose_name)
    if not raw:
        return default.resolve()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT / "deploy" / path
    return path.resolve()


FRONTEND_ROOT = _context_root(
    "HR_FRONTEND_ROOT", "FRONTEND_CONTEXT", ROOT.parent / "frontend"
)
DATABASE_ROOT = _context_root(
    "HR_DATABASE_ROOT", "DATABASE_CONTEXT", ROOT.parent / "database"
)
_REQUIRES_TRI_REPO = pytest.mark.skipif(
    not FRONTEND_ROOT.is_dir() or not DATABASE_ROOT.is_dir(),
    reason=(
        "cross-repository deployment contract requires explicit "
        "FRONTEND_CONTEXT and DATABASE_CONTEXT"
    ),
)


def _read(path: Path) -> str:
    assert path.is_file(), f"missing deployment file: {path}"
    return path.read_text(encoding="utf-8")


def _service_block(compose: str, service: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(service)}:\s*\n(.*?)(?=^  [a-z][a-z0-9_-]*:\s*\n|^[a-z]|\Z)",
        compose,
    )
    assert match, f"missing compose service: {service}"
    return match.group(1)


def _env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in _read(path).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


@_REQUIRES_TRI_REPO
def test_deployment_assets_exist_for_all_three_repositories() -> None:
    expected = (
        ROOT / "Dockerfile",
        ROOT / ".dockerignore",
        ROOT / "deploy/compose.yaml",
        ROOT / "deploy/nginx.conf",
        ROOT / "deploy/.env.example",
        ROOT / "scripts/check_ready.py",
        ROOT / "docs/DEPLOYMENT_SINGLE_USER.md",
        FRONTEND_ROOT / "Dockerfile",
        FRONTEND_ROOT / ".dockerignore",
        FRONTEND_ROOT / "nginx.conf",
        DATABASE_ROOT / "Dockerfile.migrate",
        DATABASE_ROOT / ".dockerignore",
        DATABASE_ROOT / "migrate.sh",
    )

    for path in expected:
        assert path.is_file(), f"missing deployment file: {path}"


def test_only_the_web_service_publishes_a_host_port() -> None:
    compose = _read(ROOT / "deploy/compose.yaml")
    service_names = ("web", "api", "migrate", "mysql", "redis")
    blocks = {name: _service_block(compose, name) for name in service_names}

    assert "ports:" in blocks["web"]
    assert "WEB_BIND_ADDRESS:-127.0.0.1" in blocks["web"]
    for name in ("api", "migrate", "mysql", "redis"):
        assert "ports:" not in blocks[name], f"{name} must remain internal"


def test_api_waits_for_migration_and_healthy_dependencies() -> None:
    compose = _read(ROOT / "deploy/compose.yaml")
    api = _service_block(compose, "api")
    migrate = _service_block(compose, "migrate")

    assert re.search(
        r"migrate:\s*\n\s+condition:\s+service_completed_successfully", api
    )
    assert api.count("condition: service_healthy") >= 2
    assert re.search(r"mysql:\s*\n\s+condition:\s+service_healthy", migrate)


@_REQUIRES_TRI_REPO
def test_deploy_examples_contain_names_but_no_secret_values() -> None:
    secret_names = {
        "MYSQL_PASSWORD",
        "MYSQL_ROOT_PASSWORD",
        "REDIS_PASSWORD",
        "API_AUTH_TOKEN",
        "PERSON_KEY_SECRET",
        "LLM_API_KEY",
        "LLM_VISION_API_KEY",
    }
    for env_path in (ROOT / ".env.example", ROOT / "deploy/.env.example"):
        values = _env_values(env_path)
        assert secret_names.issubset(values), f"missing secret names in {env_path}"
        assert all(values[name] == "" for name in secret_names)

    combined = "\n".join(
        (
            _read(ROOT / "deploy/compose.yaml"),
            _read(ROOT / "deploy/nginx.conf"),
            _read(FRONTEND_ROOT / "nginx.conf"),
        )
    )
    assert "123456" not in combined
    assert "__REPLACE_WITH" not in combined


@_REQUIRES_TRI_REPO
def test_nginx_injects_the_api_token_without_exposing_it_to_browser_code() -> None:
    deploy_nginx = _read(ROOT / "deploy/nginx.conf")
    image_nginx = _read(FRONTEND_ROOT / "nginx.conf")

    assert deploy_nginx == image_nginx
    assert 'proxy_set_header X-API-Token "${API_AUTH_TOKEN}";' in deploy_nginx
    assert "proxy_pass http://api:8000/;" in deploy_nginx
    assert "try_files $uri $uri/ /index.html;" in deploy_nginx
    assert not any(
        "API_AUTH_TOKEN" in path.read_text(encoding="utf-8")
        for path in (FRONTEND_ROOT / "src").rglob("*")
        if path.is_file()
    )


@_REQUIRES_TRI_REPO
def test_reverse_proxy_allows_the_full_vision_retry_window() -> None:
    deploy_nginx = _read(ROOT / "deploy/nginx.conf")
    image_nginx = _read(FRONTEND_ROOT / "nginx.conf")

    for nginx in (deploy_nginx, image_nginx):
        assert "proxy_read_timeout 480s;" in nginx
        assert "proxy_send_timeout 480s;" in nginx


@_REQUIRES_TRI_REPO
def test_docker_contexts_exclude_runtime_secrets_and_hr_data() -> None:
    backend_ignore = _read(ROOT / ".dockerignore")
    frontend_ignore = _read(FRONTEND_ROOT / ".dockerignore")
    database_ignore = _read(DATABASE_ROOT / ".dockerignore")

    for pattern in (".env", "data/", "testdata/", "output/"):
        assert pattern in backend_ignore
    for pattern in (".env", "node_modules", "dist"):
        assert pattern in frontend_ignore
    for pattern in (".git", ".env"):
        assert pattern in database_ignore


def test_readiness_payload_requires_every_production_dependency() -> None:
    script_path = ROOT / "scripts/check_ready.py"
    spec = importlib.util.spec_from_file_location("check_ready", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    ready = {
        "status": "ready",
        "mysql": True,
        "redis": True,
        "migration": True,
        "output": True,
        "config": True,
    }
    assert module.is_ready_payload(ready) is True

    for field in ("mysql", "redis", "migration", "output", "config"):
        degraded = {**ready, field: False}
        assert module.is_ready_payload(degraded) is False


def test_non_development_settings_require_a_redis_password() -> None:
    with pytest.raises(ValueError, match="redis_password"):
        Settings(
            app_env="prod",
            mysql_password="configured",
            redis_password="",
            person_key_secret="configured",
        )
