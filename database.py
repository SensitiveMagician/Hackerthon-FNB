"""Database configuration for local SQLite and hosted Supabase PostgreSQL."""
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

raw_database_url = os.getenv("DATABASE_URL", "sqlite:///./mali_mode.db").strip()
if not raw_database_url:
    raw_database_url = "sqlite:///./mali_mode.db"

# Some hosting dashboards/providers return the legacy postgres:// scheme.
# SQLAlchemy 2 expects postgresql:// (or an explicit driver scheme).
if raw_database_url.startswith("postgres://"):
    raw_database_url = "postgresql://" + raw_database_url[len("postgres://"):]

# Supabase requires TLS. Preserve any query parameters already in the URL.
if raw_database_url.startswith(("postgresql://", "postgresql+psycopg2://")):
    if "sslmode=" not in raw_database_url:
        separator = "&" if "?" in raw_database_url else "?"
        raw_database_url += f"{separator}sslmode=require"
    engine = create_engine(
        raw_database_url,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=5,
        max_overflow=2,
        connect_args={"connect_timeout": 10},
    )
else:
    # SQLite is intended for local development and automated tests.
    sqlite_connect_args = {"check_same_thread": False} if raw_database_url.startswith("sqlite") else {}
    engine = create_engine(raw_database_url, connect_args=sqlite_connect_args, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
