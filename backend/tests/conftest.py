"""测试夹具：用一次性 SQLite 引擎，让流水线无需运行中的 MySQL/Redis 即可跑通。
生产使用 MySQL 8.0+（见 app/config.py）。"""
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.reports import DailyReport
import app.models  # noqa: F401  （注册表结构）


def seed_month_start_baseline(db, report_date: date) -> None:
    """非 1 月的月初测试需上月末 YTD 基线（Row13/14/30），否则 compute_daily 会阻断。"""
    if report_date.day != 1 or report_date.month == 1:
        return
    prev = report_date - timedelta(days=1)
    db.add(DailyReport(
        report_date=prev,
        mtd_onboard=0,
        mtd_resign=0,
        ytd_onboard=0,
        ytd_resign=0,
        release_cum=0,
    ))
    db.commit()


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def api_db():
    """Thread-safe in-memory SQLite session for synchronous FastAPI routes."""
    engine = create_engine(
        "sqlite+pysqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
