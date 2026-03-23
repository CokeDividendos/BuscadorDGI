# src/services/upstash_redis.py
"""
Minimal Upstash Redis REST client for use as a cache backend.

Configuration is read from (in order of preference):
  1. st.secrets["upstash"]["rest_url"] / st.secrets["upstash"]["rest_token"]
  2. Environment variables UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN

If neither is configured, all functions become no-ops / return None,
so the caller can fall back safely to SQLite.
"""
import os
from typing import Any, List, Optional, Tuple

import requests

# Aggressive timeouts to avoid freezing the Streamlit UI on network issues.
_TIMEOUT: Tuple[int, int] = (2, 3)  # (connect_seconds, read_seconds)


def _get_config() -> Tuple[Optional[str], Optional[str]]:
    """Return (rest_url, rest_token), reading from st.secrets then env vars."""
    url: Optional[str] = None
    token: Optional[str] = None

    # Prefer Streamlit secrets when running inside Streamlit
    try:
        import streamlit as st  # noqa: PLC0415

        upstash = st.secrets.get("upstash", {})
        url = upstash.get("rest_url") or None
        token = upstash.get("rest_token") or None
    except Exception:
        pass

    # Fallback to environment variables
    if not url:
        url = os.environ.get("UPSTASH_REDIS_REST_URL") or None
    if not token:
        token = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or None

    return url, token


def is_configured() -> bool:
    """Return True if Upstash Redis credentials are available."""
    url, token = _get_config()
    return bool(url and token)


def _execute(command: List[Any]) -> Any:
    """
    Send a Redis command to Upstash via HTTP POST.

    Raises RuntimeError on configuration error, requests.RequestException on
    network / HTTP errors, and RuntimeError when Upstash returns an error body.
    """
    url, token = _get_config()
    if not url or not token:
        raise RuntimeError("Upstash Redis is not configured")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    resp = requests.post(url, headers=headers, json=command, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Upstash error: {data['error']}")
    return data.get("result")


# ---------------------------------------------------------------------------
# Public helpers used by cache_store.py
# ---------------------------------------------------------------------------

def redis_get(key: str) -> Optional[str]:
    """
    GET a key from Redis.

    Returns the raw string value, or None on cache miss.
    Raises on network / configuration errors (let caller handle fallback).
    """
    result = _execute(["GET", key])
    # Upstash returns None (JSON null) for missing keys
    if result is None:
        return None
    return str(result)


def redis_set(key: str, value_str: str, ttl_seconds: Optional[int] = None) -> None:
    """
    SET a key in Redis with an optional TTL (EX seconds).

    Raises on network / configuration errors.
    """
    cmd: List[Any] = ["SET", key, value_str]
    if ttl_seconds is not None:
        cmd += ["EX", int(ttl_seconds)]
    _execute(cmd)


def redis_del(key: str) -> None:
    """
    DEL a key from Redis.

    Raises on network / configuration errors.
    """
    _execute(["DEL", key])


def redis_scan_delete_by_prefix(prefix: str) -> None:
    """
    Delete all keys whose names start with *prefix* using iterative SCAN.

    Uses SCAN (not KEYS) to avoid blocking Redis on large keyspaces.
    A safety cap of 200 iterations prevents infinite loops.
    Raises on network / configuration errors.
    """
    pattern = f"{prefix}*"
    cursor = "0"
    max_iterations = 200

    for _ in range(max_iterations):
        result = _execute(["SCAN", cursor, "MATCH", pattern, "COUNT", "100"])
        if not result or len(result) < 2:
            break
        cursor = str(result[0])
        keys = result[1]
        if keys:
            _execute(["DEL"] + keys)
        if cursor == "0":
            break
