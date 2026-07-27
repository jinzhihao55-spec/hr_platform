from __future__ import annotations

import asyncio
import tempfile
from datetime import date
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile

from app.services import ingestion_service


def test_ingest_sanitizes_client_filename(monkeypatch, tmp_path):
    """主上传入口不得让 multipart filename 影响临时目录结构。"""
    base = tmp_path / "uploads"
    base.mkdir()
    captured: dict[str, Path] = {}

    real_mkdtemp = tempfile.mkdtemp
    monkeypatch.setattr(
        ingestion_service.tempfile,
        "mkdtemp",
        lambda prefix: real_mkdtemp(prefix=prefix, dir=base),
    )
    monkeypatch.setattr(ingestion_service.job_repo, "create", lambda *_args: "job-1")
    monkeypatch.setattr(ingestion_service.job_repo, "update", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ingestion_service.report_repo,
        "count_inputs",
        lambda *_args: {key: 1 for key in ingestion_service.SOURCE_KEYS},
    )
    monkeypatch.setattr(
        ingestion_service.source_status_repo,
        "save",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        ingestion_service.source_status_repo,
        "save_db",
        lambda *_args, **_kwargs: None,
    )

    def fake_run(_db, _report_date, files, **_kwargs):
        captured["path"] = Path(files["employees"])
        return {"employees": 1}

    monkeypatch.setattr(ingestion_service._agent, "run", fake_run)
    monkeypatch.setattr(ingestion_service._agent, "cleanse_stats", {}, raising=False)
    from app.pipeline.input import workbook_split
    monkeypatch.setattr(
        workbook_split,
        "expand_provided_files",
        lambda provided, _tmp: provided,
    )
    upload = UploadFile(
        filename="../../../../outside.xlsx",
        file=BytesIO(b"placeholder"),
    )

    class _StubDB:
        def commit(self):
            return None

    asyncio.run(
        ingestion_service.ingest(
            _StubDB(),
            date(2026, 7, 10),
            {"employees": upload},
        )
    )

    assert captured["path"].parent.parent == base
    assert ".." not in captured["path"].parts
    assert captured["path"].name == "employees_outside.xlsx"


def _stub_ingest_env(monkeypatch, events):
    monkeypatch.setattr(ingestion_service.job_repo, "create", lambda *_args: "job-1")
    monkeypatch.setattr(
        ingestion_service.job_repo, "update",
        lambda _job, status=None, **_kw: events.append(f"job:{status}"),
    )
    monkeypatch.setattr(
        ingestion_service.report_repo, "count_inputs",
        lambda *_args: {key: 1 for key in ingestion_service.SOURCE_KEYS},
    )
    monkeypatch.setattr(
        ingestion_service._agent, "run",
        lambda *_args, **_kwargs: events.append("agent_run") or {},
    )
    monkeypatch.setattr(ingestion_service._agent, "cleanse_stats", {}, raising=False)


class _TxDB:
    def __init__(self, events):
        self.events = events

    def commit(self):
        self.events.append("commit")

    def rollback(self):
        self.events.append("rollback")


def test_ingest_single_transaction_order(monkeypatch):
    """业务数据 + 上传记录一次 commit；job succeeded 与 Redis 缓存在 commit 之后。"""
    events: list[str] = []
    _stub_ingest_env(monkeypatch, events)
    monkeypatch.setattr(
        ingestion_service.source_status_repo, "save_db",
        lambda *_args, **_kwargs: events.append("save_db"),
    )
    monkeypatch.setattr(
        ingestion_service.source_status_repo, "save",
        lambda *_args, **_kwargs: events.append("redis"),
    )

    out = asyncio.run(ingestion_service.ingest(_TxDB(events), date(2026, 7, 10), {}))

    assert out["status"] == "succeeded"
    assert events.count("commit") == 1
    assert events.index("save_db") < events.index("commit")
    assert events.index("commit") < events.index("job:succeeded")
    assert events.index("job:succeeded") < events.index("redis")


def test_ingest_rolls_back_and_marks_job_failed_when_persist_fails(monkeypatch):
    events: list[str] = []
    _stub_ingest_env(monkeypatch, events)

    def broken_save_db(*_args, **_kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(ingestion_service.source_status_repo, "save_db", broken_save_db)

    import pytest as _pytest
    with _pytest.raises(RuntimeError):
        asyncio.run(ingestion_service.ingest(_TxDB(events), date(2026, 7, 10), {}))

    assert "rollback" in events
    assert "commit" not in events
    assert "job:succeeded" not in events
    assert "job:failed" in events


def test_ingest_succeeds_even_if_redis_cache_write_fails(monkeypatch):
    """Redis 只是展示缓存：写失败不得把已提交的入库伪装成失败。"""
    events: list[str] = []
    _stub_ingest_env(monkeypatch, events)
    monkeypatch.setattr(
        ingestion_service.source_status_repo, "save_db",
        lambda *_args, **_kwargs: events.append("save_db"),
    )

    def broken_redis(*_args, **_kwargs):
        raise RuntimeError("redis down")

    monkeypatch.setattr(ingestion_service.source_status_repo, "save", broken_redis)

    out = asyncio.run(ingestion_service.ingest(_TxDB(events), date(2026, 7, 10), {}))

    assert out["status"] == "succeeded"
    assert "job:failed" not in events


def test_extraction_agent_run_does_not_commit():
    """事务所有权在 ingestion service；抽取 Agent 只 flush 不 commit。"""
    from datetime import date as _date

    from app.agents.extraction_agent import ExtractionAgent

    events: list[str] = []

    class _DB:
        def commit(self):
            events.append("commit")

        def flush(self):
            events.append("flush")

    ExtractionAgent().run(_DB(), _date(2026, 7, 10), {})

    assert "commit" not in events
