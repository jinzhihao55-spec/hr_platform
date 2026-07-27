"""Idempotently apply the small schema addition required by the 2026-07-24 build."""

from sqlalchemy import inspect

from app.core.database import engine


def main() -> None:
    inspector = inspect(engine)
    if "run_sources" not in inspector.get_table_names():
        raise RuntimeError("run_sources table does not exist; initialize the database first")
    columns = {column["name"] for column in inspector.get_columns("run_sources")}
    if "original_filename" in columns:
        print("schema current: run_sources.original_filename already exists")
        return
    if engine.dialect.name != "mysql":
        raise RuntimeError(
            "automatic 2026-07-24 migration only supports MySQL; "
            f"current dialect is {engine.dialect.name}"
        )
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE run_sources "
            "ADD COLUMN original_filename VARCHAR(255) NULL AFTER original_extension"
        )
    print("schema updated: added run_sources.original_filename")


if __name__ == "__main__":
    main()
