# src/services/usage_limits.py
from __future__ import annotations
from datetime import datetime, timezone

from src.services.cache_store import cache_get, cache_set


def _today_key() -> str:
    # Usa fecha UTC para consistencia
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def remaining_searches(email: str, daily_limit: int) -> int:
    k = f"usage:searches:{email}:{_today_key()}"
    used = cache_get(k) or 0
    try:
        used = int(used)
    except Exception:
        used = 0
    return max(daily_limit - used, 0)


def consume_search(email: str, daily_limit: int, cost: int = 1) -> tuple[bool, int]:
    """
    Devuelve (allowed, remaining_after)
    """
    k = f"usage:searches:{email}:{_today_key()}"
    used = cache_get(k) or 0
    try:
        used = int(used)
    except Exception:
        used = 0

    if used + cost > daily_limit:
        return (False, max(daily_limit - used, 0))

    used_new = used + cost
    # TTL hasta fin de día (aprox 26h para asegurar)
    cache_set(k, used_new, ttl_seconds=26 * 3600)
    return (True, max(daily_limit - used_new, 0))
