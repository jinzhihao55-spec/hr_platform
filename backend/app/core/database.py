"""MySQL 8.0+，基于 SQLAlchemy 2.0。"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


_is_sqlite = settings.sqlalchemy_url.startswith("sqlite")

_engine_kwargs = dict(future=True)
if _is_sqlite:
    from sqlalchemy.pool import StaticPool
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
    _engine_kwargs["poolclass"] = StaticPool
else:
    _engine_kwargs["pool_pre_ping"] = True
    _engine_kwargs["pool_recycle"] = 3600

engine = create_engine(settings.sqlalchemy_url, **_engine_kwargs)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖注入。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """建表。导入 models 以便其注册到 Base.metadata。"""
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
