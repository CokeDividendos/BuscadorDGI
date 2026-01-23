# src/services/yf_client.py
from __future__ import annotations

import time
import random

try:
    import requests_cache
    _HAS_RCACHE = True
except Exception:
    _HAS_RCACHE = False


class YFError(RuntimeError):
    pass


def install_http_cache(cache_name: str = "yf_http_cache", expire_seconds: int = 3600) -> None:
    if not _HAS_RCACHE:
        return
    try:
        requests_cache.install_cache(cache_name, expire_after=expire_seconds)
    except Exception:
        pass


def yf_call(fn, max_attempts: int = 4):
    last = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as e:
            last = e
            if attempt == max_attempts:
                break
            sleep_s = (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            time.sleep(sleep_s)
    raise YFError(str(last) if last else "yfinance error")
