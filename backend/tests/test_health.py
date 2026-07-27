"""健康检查不得报假健康：MySQL/Redis 任一不可用时 status 必须降级。"""
import sqlalchemy
from sqlalchemy import Text
from fastapi.testclient import TestClient

from app.api.routes import health as health_route
from app.core import database
from app.main import app

client = TestClient(app)


def test_health_degrades_when_mysql_down(monkeypatch):
    monkeypatch.setattr(health_route, "_mysql_ok", lambda: False)
    monkeypatch.setattr(health_route, "_redis_ok", lambda: True)

    payload = client.get("/health").json()

    assert payload["mysql"] is False
    assert payload["status"] == "degraded"


def test_health_degrades_when_redis_down(monkeypatch):
    monkeypatch.setattr(health_route, "_mysql_ok", lambda: True)
    monkeypatch.setattr(health_route, "_redis_ok", lambda: False)

    payload = client.get("/health").json()

    assert payload["redis"] is False
    assert payload["status"] == "degraded"


def test_health_ok_when_dependencies_up(monkeypatch):
    monkeypatch.setattr(health_route, "_mysql_ok", lambda: True)
    monkeypatch.setattr(health_route, "_redis_ok", lambda: True)

    payload = client.get("/health").json()

    assert payload["status"] == "ok"
    assert payload["mysql"] is True
    assert payload["redis"] is True


def test_live_probe_is_always_ok(monkeypatch):
    monkeypatch.setattr(health_route, "_mysql_ok", lambda: False)
    monkeypatch.setattr(health_route, "_redis_ok", lambda: False)

    assert client.get("/live").status_code == 200


def test_ready_probe_returns_503_when_dependency_down(monkeypatch):
    monkeypatch.setattr(health_route, "_mysql_ok", lambda: False)
    monkeypatch.setattr(health_route, "_redis_ok", lambda: True)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["mysql"] is False


def test_ready_probe_ok_when_dependencies_up(monkeypatch):
    monkeypatch.setattr(health_route, "_mysql_ok", lambda: True)
    monkeypatch.setattr(health_route, "_redis_ok", lambda: True)
    monkeypatch.setattr(health_route, "_migration_ok", lambda: True)
    monkeypatch.setattr(health_route, "_output_ok", lambda: True)
    monkeypatch.setattr(health_route, "_config_ok", lambda: True)

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["migration"] is True
    assert response.json()["output"] is True
    assert response.json()["config"] is True


def test_ready_probe_reports_migration_and_output_failures(monkeypatch):
    monkeypatch.setattr(health_route, "_mysql_ok", lambda: True)
    monkeypatch.setattr(health_route, "_redis_ok", lambda: True)
    monkeypatch.setattr(health_route, "_migration_ok", lambda: False)
    monkeypatch.setattr(health_route, "_output_ok", lambda: False)
    monkeypatch.setattr(health_route, "_config_ok", lambda: True)

    response = client.get("/ready")

    assert response.status_code == 503
    assert {
        "status": "not_ready",
        "migration": False,
        "output": False,
    }.items() <= response.json().items()


def test_migration_check_rejects_text_publication_snapshot(monkeypatch):
    columns = {
        "report_runs": {"source_bundle_hash", "baseline_report_id"},
        "run_sources": {"sha256", "schema_version", "parse_status"},
        "run_report_targets": {"preview_hash", "validation_summary"},
        "published_reports": {"snapshot_hash", "is_current", "version", "snapshot_json"},
        "report_artifacts": {"protected_path", "sha256"},
        "publication_attempts": {"status", "staging_path", "final_path"},
    }

    class Inspector:
        def get_table_names(self):
            return list(columns)

        def get_columns(self, table):
            return [
                {"name": name, "type": Text()}
                for name in columns[table]
            ]

    monkeypatch.setattr(sqlalchemy, "inspect", lambda _engine: Inspector())
    monkeypatch.setattr(database, "engine", object())

    assert health_route._migration_ok() is False
