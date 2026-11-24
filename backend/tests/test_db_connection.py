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
