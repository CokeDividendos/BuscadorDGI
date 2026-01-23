# src/services/cache_store.py
import json
import time
from typing import Any, Optional

from src.db import get_conn


def _ensure_cache_table() -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
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


def cache_get(key: str) -> Optional[Any]:
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
            # expirado → borrar y retornar None
            cache_delete(key)
            return None

    try:
        return json.loads(row["value_json"])
    except Exception:
        return None


def cache_set(key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
    _ensure_cache_table()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
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
            json.dumps(value, ensure_ascii=False),
            int(time.time()),
            int(ttl_seconds) if ttl_seconds is not None else None,
        ),
    )
    conn.commit()
    conn.close()


def cache_delete(key: str) -> None:
    _ensure_cache_table()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM kv_cache WHERE key = ?", (key,))
    conn.commit()
    conn.close()


def cache_clear(prefix: Optional[str] = None) -> None:
    _ensure_cache_table()
    conn = get_conn()
    cur = conn.cursor()
    if prefix:
        cur.execute("DELETE FROM kv_cache WHERE key LIKE ?", (f"{prefix}%",))
    else:
        cur.execute("DELETE FROM kv_cache")
    conn.commit()
    conn.close()

# --- Backward compatible alias (do not remove) ---
def cache_clear_all() -> None:
    """Compatibilidad: borra todo el cache."""
    cache_clear(prefix=None)
