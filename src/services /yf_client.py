# src/services/yf_client.py
from __future__ import annotations

import time
import random
import threading

try:
    import yfinance as yf  # noqa: F401
except Exception:
    yf = None  # type: ignore

try:
    import requests_cache
    _HAS_RCACHE = True
except Exception:
    _HAS_RCACHE = False


class YFError(RuntimeError):
    pass


# -----------------------------
# GLOBAL THROTTLE (anti-burst)
# -----------------------------
_REQ_LOCK = threading.Lock()
_LAST_REQ_TS = 0.0

# Ajusta si quieres: 0.8–1.2s suele bajar MUCHO rate limits
MIN_SECONDS_BETWEEN_REQUESTS = 0.9


def install_http_cache(cache_name: str = "yf_http_cache", expire_seconds: int = 3600) -> None:
    """
    Cachea respuestas HTTP subyacentes de yfinance para reducir llamadas a Yahoo.
    """
    if not _HAS_RCACHE:
        return
    try:
        requests_cache.install_cache(cache_name, expire_after=expire_seconds)
    except Exception:
        pass


def _is_rate_limit_error(exc: Exception) -> bool:
    # yfinance.exceptions.YFRateLimitError (si existe)
    if exc.__class__.__name__ == "YFRateLimitError":
        return True
    msg = str(exc).lower()
    # heurísticas
    return ("rate limit" in msg) or ("too many requests" in msg) or ("429" in msg)


def yf_call(fn, max_attempts: int = 6):
    """
    Wrapper de reintentos con:
    - throttle global (evita bursts)
    - backoff exponencial + jitter
    - backoff más fuerte si es rate-limit
    """
    global _LAST_REQ_TS
    last = None

    for attempt in range(1, max_attempts + 1):
        try:
            # throttle global
            with _REQ_LOCK:
                now = time.time()
                wait = MIN_SECONDS_BETWEEN_REQUESTS - (now - _LAST_REQ_TS)
                if wait > 0:
                    time.sleep(wait)
                _LAST_REQ_TS = time.time()

            return fn()

        except Exception as e:
            last = e
            if attempt == max_attempts:
                break

            # Backoff normal vs rate limit
            if _is_rate_limit_error(e):
                # más agresivo: 5, 10, 20, 40... (cap ~60)
                base = min(5 * (2 ** (attempt - 1)), 60)
            else:
                base = min((2 ** (attempt - 1)), 20)

            sleep_s = base + random.uniform(0, 0.6)
            time.sleep(sleep_s)

    raise YFError(str(last) if last else "yfinance error")
