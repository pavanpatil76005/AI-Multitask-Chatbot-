from collections.abc import Generator
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session

from app.core.config import get_settings


def utcnow() -> datetime:
    """Return naive UTC for the project's existing TIMESTAMP columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )


def get_db() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session


def check_database_connection() -> bool:
    with get_engine().connect() as connection:
        return connection.execute(text("SELECT 1")).scalar_one() == 1


if __name__ == "__main__":
    if not check_database_connection():
        raise SystemExit("Database connection check failed")
    print("Database connection successful")
