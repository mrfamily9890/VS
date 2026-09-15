"""Verify a PostgreSQL backup can be restored into an isolated target."""

import os
import subprocess
from pathlib import Path

from sqlalchemy import create_engine, text


def main() -> None:
    source_url = os.environ.get("VAHANA_BACKUP_SOURCE_URL")
    target_url = os.environ.get("VAHANA_RESTORE_TARGET_URL")
    backup_file = Path(os.environ.get("VAHANA_BACKUP_FILE", "./vahana-restore-check.dump"))
    if not source_url or not target_url:
        raise SystemExit(
            "Set VAHANA_BACKUP_SOURCE_URL and VAHANA_RESTORE_TARGET_URL before running the restore check."
        )
    subprocess.run(
        ["pg_dump", "--format=custom", "--no-owner", "--file", str(backup_file), source_url],
        check=True,
    )
    subprocess.run(
        [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--dbname",
            target_url,
            str(backup_file),
        ],
        check=True,
    )
    sqlalchemy_target_url = target_url.replace("postgres://", "postgresql+psycopg://", 1)
    sqlalchemy_target_url = sqlalchemy_target_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(sqlalchemy_target_url, pool_pre_ping=True)
    with engine.connect() as connection:
        connection.execute(text("select 1"))
    print(f"Backup restore verification passed: {backup_file}")


if __name__ == "__main__":
    main()
