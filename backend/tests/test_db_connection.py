"""TiDB TLS auto-configuration for MySQL connections."""
from __future__ import annotations

import os

import certifi

from app.database.connection import create_app_engine, mysql_ssl_args

TIDB_URL = (
    "mysql+pymysql://user:pass@cluster-xyz.tidbcloud.com:4000/pulsewatch"
)
TIDB_URL_UPPER_HOST = (
    "mysql+pymysql://user:pass@CLUSTER-XYZ.TIDBCLOUD.COM:4000/pulsewatch"
)
RAILWAY_URL = "mysql+pymysql://root:pass@containers-us-west-1.railway.app:1234/pulsewatch"
LOCAL_URL = "mysql+pymysql://pulsewatch:pulsewatchpass@127.0.0.1:3306/pulsewatch"


def test_tidb_host_gets_verified_tls():
    args = mysql_ssl_args(TIDB_URL)
    assert args == {"ssl": {"ca": certifi.where()}}
    assert os.path.isfile(args["ssl"]["ca"])


def test_tidb_host_match_is_case_insensitive():
    assert mysql_ssl_args(TIDB_URL_UPPER_HOST) == {"ssl": {"ca": certifi.where()}}


def test_non_tidb_mysql_gets_no_tls_args():
    assert mysql_ssl_args(RAILWAY_URL) == {}
    assert mysql_ssl_args(LOCAL_URL) == {}


def test_malformed_url_gets_no_tls_args():
    assert mysql_ssl_args("mysql+pymysql://[::1") == {}


def test_tidb_engine_uses_tls_and_pool_recycle():
    # Engine creation is lazy (no connection), so this is network-free.
    engine = create_app_engine(TIDB_URL)
    try:
        assert engine.pool._recycle == 300
    finally:
        engine.dispose()


def test_plain_mysql_engine_has_no_pool_recycle():
    engine = create_app_engine(LOCAL_URL)
    try:
        # SQLAlchemy default: -1 (no recycling).
        assert engine.pool._recycle == -1
    finally:
        engine.dispose()


# --- DATABASE_URL scheme normalization (config) ----------------------------

def test_plain_mysql_scheme_rewritten_to_pymysql():
    """Regression test: TiDB Cloud shows a plain mysql:// URL; without
    the +pymysql qualifier SQLAlchemy defaults to mysqldb and crashes
    with `No module named 'MySQLdb'` (first Render deploy failure)."""
    from app.core.config import Settings

    s = Settings(DATABASE_URL="mysql://u:p@cluster-xyz.tidbcloud.com:4000/db")
    assert s.DATABASE_URL == "mysql+pymysql://u:p@cluster-xyz.tidbcloud.com:4000/db"


def test_pymysql_scheme_left_untouched():
    from app.core.config import Settings

    url = "mysql+pymysql://u:p@host:3306/db"
    assert Settings(DATABASE_URL=url).DATABASE_URL == url


def test_sqlite_url_left_untouched_and_whitespace_stripped():
    from app.core.config import Settings

    assert (
        Settings(DATABASE_URL="  sqlite:///./x.db\n").DATABASE_URL
        == "sqlite:///./x.db"
    )


def test_pasted_api_keys_are_stripped():
    """A trailing newline pasted into a Render env var must not
    invalidate the key (Gemini returns 400 'API key not valid' while
    gemini_configured still reports true — production incident
    25 Nov 2026, new alerts showed Template despite a set key)."""
    from app.core.config import Settings

    s = Settings(
        GEMINI_API_KEY="  AIza-test-key\n",
        BREVO_API_KEY="\txkeysib-test\r\n",
        TELEGRAM_BOT_TOKEN="  123:abc \n",
    )
    assert s.GEMINI_API_KEY == "AIza-test-key"
    assert s.BREVO_API_KEY == "xkeysib-test"
    assert s.TELEGRAM_BOT_TOKEN == "123:abc"
    assert Settings(GEMINI_API_KEY="   ").GEMINI_API_KEY is None


def test_cors_origins_strip_trailing_slash():
    """Browsers send the origin without a trailing slash, so a pasted
    FRONTEND_URL ending in '/' must still match."""
    from app.core.config import Settings

    s = Settings(
        FRONTEND_URL="https://pulsewatchai.vercel.app/, http://localhost:5173/"
    )
    assert s.cors_origins == [
        "https://pulsewatchai.vercel.app",
        "http://localhost:5173",
    ]
