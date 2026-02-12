# src/services/cache_store.py
import json
import time
from datetime import datetime
from typing import Any, Optional

import pandas as pd

from src.db import get_conn, _get_cursor, _execute_query


class CacheJSONEncoder(json.JSONEncoder):
    """
    Custom JSON encoder that handles pandas Timestamps and datetime objects.
    
    This encoder converts:
    - pandas.Timestamp -> ISO format string
    - datetime objects -> ISO format string
    
    Note: NaN and Infinity values are handled by Python's json module by default.
    """
    def default(self, obj):
        # Handle pandas Timestamp
        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
        # Handle datetime objects
        elif isinstance(obj, datetime):
            return obj.isoformat()
        # Let the base class handle other types or raise TypeError
        return super().default(obj)


def _ensure_cache_table() -> None:
    # Tables are now created in _init_db_tables(), but keep this for compatibility
    pass


def cache_get(key: str) -> Optional[Any]:
    _ensure_cache_table()
    conn = get_conn()
    cur = _get_cursor(conn)
    _execute_query(cur,
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
            cache_delete(key)
            return None

    try:
        return json.loads(row["value_json"])
    except Exception:
        return None


def cache_set(key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
    _ensure_cache_table()
    conn = get_conn()
    cur = _get_cursor(conn)
    _execute_query(cur,
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
            json.dumps(value, ensure_ascii=False, cls=CacheJSONEncoder),
            int(time.time()),
            int(ttl_seconds) if ttl_seconds is not None else None,
        ),
    )
    conn.commit()
    conn.close()


def cache_delete(key: str) -> None:
    _ensure_cache_table()
    conn = get_conn()
    cur = _get_cursor(conn)
    _execute_query(cur, "DELETE FROM kv_cache WHERE key = ?", (key,))
    conn.commit()
    conn.close()


def cache_clear(prefix: Optional[str] = None) -> None:
    _ensure_cache_table()
    conn = get_conn()
    cur = _get_cursor(conn)
    if prefix:
        _execute_query(cur, "DELETE FROM kv_cache WHERE key LIKE ?", (f"{prefix}%",))
    else:
        _execute_query(cur, "DELETE FROM kv_cache", ())
    conn.commit()
    conn.close()


def cache_clear_all() -> None:
    cache_clear(prefix=None)
