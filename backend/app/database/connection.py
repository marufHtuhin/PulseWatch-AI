"""Engine + session factory.

MySQL-first (``mysql+pymysql://...``) with a SQLite fallback for local
testing (``sqlite:///./pulsewatch.db``). The same models/migrations run on
both; no dialect-specific SQL is used anywhere.

TiDB Cloud hosts (``*.tidbcloud.com``) refuse non-TLS connections, so
verified TLS via the certifi CA bundle is configured automatically for
them — the user just pastes the TiDB URL. Other MySQL hosts need no TLS.
"""
from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings


def mysql_ssl_args(database_url: str) -> dict:
    """Connect args for a MySQL URL.

    TiDB Cloud (``*.tidbcloud.com``) → verified TLS: ``{"ssl": {"ca":
    certifi.where()}}``. TiDB's certificates come from Let's Encrypt
    (publicly trusted), so the certifi bundle verifies them with no extra
    config. PyMySQL builds the SSL context with CERT_REQUIRED + hostname
    check when ``"ca"`` is set. Anything else → ``{}`` (Railway and local
    MySQL need no TLS; SQLite never reaches this function).
    """
    try:
        host = (urlparse(database_url).hostname or "").lower()
    except ValueError:
        return {}
    if host.endswith(".tidbcloud.com"):
        import certifi

        return {"ssl": {"ca": certifi.where()}}
    return {}


def create_app_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in database_url:
            kwargs["poolclass"] = StaticPool
        engine = create_engine(database_url, **kwargs)

        @event.listens_for(engine, "connect")
        def _enable_sqlite_fk(dbapi_connection, _connection_record):  # noqa: ANN001, ANN202
            # SQLite enforces foreign keys only when the pragma is on.
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine
    ssl_args = mysql_ssl_args(database_url)
    kwargs: dict = {"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20}
    if ssl_args:
        kwargs["connect_args"] = ssl_args
        # TiDB Cloud closes idle connections after 5 minutes.
        kwargs["pool_recycle"] = 300
    return create_engine(database_url, **kwargs)


engine: Engine = create_app_engine(settings.DATABASE_URL)

# expire_on_commit=False keeps objects usable after commit (handy for
# serializing a check outcome right after the transaction commits).
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Session:
    """FastAPI dependency: one session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
