from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()
database_url = settings.database_url.replace("postgres://", "postgresql+psycopg://", 1)
database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1) if database_url.startswith("postgresql://") else database_url
connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine_options = {"connect_args": connect_args, "pool_pre_ping": True}
if not database_url.startswith("sqlite"):
    engine_options["poolclass"] = NullPool
engine = create_engine(database_url, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    database = SessionLocal()
    try:
        yield database
    finally:
        database.close()
