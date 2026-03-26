# src/services/cache_store.py
import json
import time
from datetime import datetime
from typing import Any, Optional

import numpy as np
import pandas as pd
import requests

from src.db import get_conn
from src.services import upstash_redis as _redis

# Exceptions that indicate a Redis back-end problem rather than a programming error.
_REDIS_ERRORS = (RuntimeError, requests.RequestException, OSError)


class CacheJSONEncoder(json.JSONEncoder):
    """
    Custom JSON encoder that handles pandas Timestamps, datetime objects, and numpy types.
    
    This encoder converts:
    - pandas.Timestamp -> ISO format string
    - datetime objects -> ISO format string
    - numpy integers (int8, int16, int32, int64, etc.) -> int
    - numpy floats (float16, float32, float64, etc.) -> float
    - numpy booleans -> bool
    - numpy arrays -> list
    - pandas NA / NaT -> None
    
    Note: NaN and Infinity values are handled by Python's json module by default.
    """
    def default(self, obj):
        # Handle pandas NA / NaT first (NaT is a subclass of datetime, check before datetime)
        if obj is pd.NA or obj is pd.NaT:
            return None
        # Handle pandas Timestamp
        elif isinstance(obj, pd.Timestamp):
            return obj.isoformat()
        # Handle datetime objects
        elif isinstance(obj, datetime):
            return obj.isoformat()
        # Handle numpy scalar types and arrays (identified by module to avoid false positives)
        elif type(obj).__module__ == "numpy":
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.floating):
                return float(obj)
            if isinstance(obj, np.bool_):
                return bool(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
        # Let the base class handle other types or raise TypeError
        return super().default(obj)


def _ensure_cache_table() -> None:
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS kv_cache (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            ttl_seconds INTEGER
        )
        """
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# SQLite helpers (internal fallback implementations)
# ---------------------------------------------------------------------------

def _sqlite_get(key: str) -> Optional[Any]:
    _ensure_cache_table()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT value_json, created_at, ttl_seconds FROM kv_cache WHERE key = ?",
        (key,),
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    created_at = int(row["created_at"])
    ttl = row["ttl_seconds"]
    if ttl is not None:
        ttl = int(ttl)
        if (int(time.time()) - created_at) > ttl:
            _sqlite_delete(key)
            return None

    try:
        return json.loads(row["value_json"])
    except Exception:
        return None


def _sqlite_set(key: str, value_json: str, ttl_seconds: Optional[int] = None) -> None:
    _ensure_cache_table()
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO kv_cache(key, value_json, created_at, ttl_seconds)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value_json=excluded.value_json,
            created_at=excluded.created_at,
            ttl_seconds=excluded.ttl_seconds
        """,
        (
            key,
            value_json,
            int(time.time()),
            int(ttl_seconds) if ttl_seconds is not None else None,
        ),
    )
    conn.commit()
    conn.close()


def _sqlite_delete(key: str) -> None:
    _ensure_cache_table()
    conn = get_conn()
    conn.execute("DELETE FROM kv_cache WHERE key = ?", (key,))
    conn.commit()
    conn.close()


def _sqlite_clear(prefix: Optional[str] = None) -> None:
    _ensure_cache_table()
    conn = get_conn()
    cur = conn.cursor()
    if prefix:
        cur.execute("DELETE FROM kv_cache WHERE key LIKE ?", (f"{prefix}%",))
    else:
        cur.execute("DELETE FROM kv_cache")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Public API — Redis primary, SQLite fallback
# ---------------------------------------------------------------------------

def cache_get(key: str) -> Optional[Any]:
    if _redis.is_configured():
        try:
            raw = _redis.redis_get(key)
            if raw is None:
                return None
            try:
                return json.loads(raw)
            except Exception:
                return None
        except _REDIS_ERRORS:
            pass  # Network / transient error — fall through to SQLite
    return _sqlite_get(key)


def cache_set(key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
    value_json = json.dumps(value, ensure_ascii=False, cls=CacheJSONEncoder)
    if _redis.is_configured():
        try:
            _redis.redis_set(key, value_json, ttl_seconds=ttl_seconds)
            return
        except _REDIS_ERRORS:
            pass  # Network / transient error — fall through to SQLite
    _sqlite_set(key, value_json, ttl_seconds=ttl_seconds)


def cache_delete(key: str) -> None:
    if _redis.is_configured():
        try:
            _redis.redis_del(key)
            return
        except _REDIS_ERRORS:
            pass  # Fall through to SQLite
    _sqlite_delete(key)


def cache_clear(prefix: Optional[str] = None) -> None:
    if _redis.is_configured():
        try:
            if prefix:
                _redis.redis_scan_delete_by_prefix(prefix)
            else:
                _redis.redis_scan_delete_by_prefix("")
            return
        except _REDIS_ERRORS:
            pass  # Fall through to SQLite
    _sqlite_clear(prefix)


def cache_clear_all() -> None:
    cache_clear(prefix=None)
