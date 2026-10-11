"""Database connection and session management"""
import sqlite3

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from app.config import settings


@event.listens_for(Engine, "connect")
def enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    """Enforce references on new SQLite connections, including isolated tests."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


# Create database engine with SQLite-specific settings if needed
engine_kwargs = {
    "echo": settings.db_echo,
    "pool_pre_ping": True,
}

if settings.database_url.startswith("sqlite"):
    # SQLite-specific settings
    engine_kwargs.update({
        "connect_args": {"check_same_thread": False},
        "pool_pre_ping": False,
    })
else:
    # PostgreSQL settings
    engine_kwargs.update({
        "pool_size": 10,
        "max_overflow": 20,
    })

engine = create_engine(settings.database_url, **engine_kwargs)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db():
    """Dependency for getting database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
