import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Defaults to a local SQLite file so `uvicorn app.main:app --reload` just
# works with zero setup. On Render, set DATABASE_URL to a managed Postgres
# connection string (Render's free Postgres works fine) — SQLite on a web
# service's ephemeral disk will NOT persist across deploys/restarts.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./isthisai.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    # Import models here (not at module load) so they're registered on
    # Base.metadata before create_all runs, without risking a circular import.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
