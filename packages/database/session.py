import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy.pool import NullPool

import tempfile

_engines = {}

def get_engine():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL environment variable is not set. Check your .env file.")
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if db_url.startswith("sqlite:///") and not db_url.startswith("sqlite:////") and ":memory:" not in db_url:
        rel_path = db_url.replace("sqlite:///", "")
        filename = os.path.basename(rel_path)
        abs_path = os.path.join(tempfile.gettempdir(), filename).replace("\\", "/")
        db_url = f"sqlite:///{abs_path}"
    if db_url not in _engines:
        if db_url.startswith("sqlite"):
            _engines[db_url] = create_engine(db_url, connect_args={"check_same_thread": False}, poolclass=NullPool)
        else:
            try:
                eng = create_engine(
                    db_url,
                    pool_size=10,
                    max_overflow=20,
                    pool_pre_ping=True
                )
                # Test connection
                with eng.connect() as conn:
                    pass
                _engines[db_url] = eng
            except Exception as e:
                allow_fallback = os.getenv("ALLOW_SQLITE_FALLBACK", "false").lower() == "true"
                if allow_fallback:
                    fallback_url = "sqlite:///" + os.path.join(tempfile.gettempdir(), "nw_fallback.db").replace("\\", "/")
                    _engines[db_url] = create_engine(fallback_url, connect_args={"check_same_thread": False}, poolclass=NullPool)
                else:
                    raise RuntimeError(f"Database connection failed for '{db_url}'. Ensure PostgreSQL is running or set ALLOW_SQLITE_FALLBACK=true for offline testing. Error: {e}")
    return _engines[db_url]

class _EngineProxy:
    def __getattr__(self, name):
        return getattr(get_engine(), name)

engine = _EngineProxy()

def SessionLocal():
    eng = get_engine()
    sm = sessionmaker(autocommit=False, autoflush=False, bind=eng)
    return sm()

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

