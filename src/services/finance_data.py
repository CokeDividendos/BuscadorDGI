from __future__ import annotations

from datetime import datetime, date
from typing import Any, Callable

import pandas as pd
import numpy as np

from src.services.cache_store import cache_get, cache_set
from src.services.yf_client import install_http_cache, yf_call
from src.db import get_conn


class FinanceDataError(RuntimeError):
    pass


# Activa cache HTTP para yfinance
install_http_cache(expire_seconds=3600)


# -----------------------------
# JSON SAFE
# -----------------------------
def _json_safe(x: Any) -> Any:
    """Convierte objetos a tipos JSON serializables."""
    if x is None:
        return None
    if isinstance(x, (str, int, float, bool)):
        return x
    if isinstance(x, (datetime, date)):
        return x.isoformat()
    if isinstance(x, dict):
        return {str(k): _json_safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [_json_safe(v) for v in x]

    # Pandas/numpy scalars
    try:
        if isinstance(x, np.integer):
            return int(x)
        if isinstance(x, np.floating):
            return float(x)
        if isinstance(x, np.bool_):
            return bool(x)
    except Exception:
        pass

    # Object with items
    try:
        if hasattr(x, "items"):
            return {str(k): _json_safe(v) for k, v in dict(x).items()}
    except Exception:
        pass

    return str(x)


# -----------------------------
# STALE CACHE (no expira / no borra)
# -----------------------------
def _cache_get_stale(key: str) -> Any | None:
    """
    Lee DIRECTO desde kv_cache sin aplicar TTL ni borrar expirados.
    Sirve para 'stale-if-error' cuando Yahoo rate-limitea.
    """
    try:
        conn = get_conn()
        cur = conn.cursor()
        # tu cache_store crea kv_cache, usamos la misma tabla
        cur.execute("SELECT value_json FROM kv_cache WHERE key = ?", (key,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        import json
        return json.loads(row["value_json"])
    except Exception:
        return None


def _cache_get_or_set(key: str, ttl: int, fn: Callable[[], Any]):
    """
    - Hit normal: cache_get (respeta TTL)
    - Miss: calcula y cachea
    - Si falla (rate-limit u otro): devuelve stale si existe para evitar caídas
    """
    hit = cache_get(key)
    if hit is not None:
        return hit

    try:
        val = fn()
        val = _json_safe(val)
        cache_set(key, val, ttl_seconds=ttl)
        return val
    except Exception as e:
        stale = _cache_get_stale(key)
        if stale is not None:
            return stale
        raise FinanceDataError(str(e))


# -----------------------------
# PRICE (TTL 5 min)
# -----------------------------
def get_price_data(ticker: str) -> dict:
    """
    Devuelve datos de precio con TTL 5 minutos.

    CLAVE: NO tocamos fast_info.get("currency") ni nada que dispare history_metadata.
    Usamos UNA llamada: history(2d, 1d).
    Si Yahoo rate-limitea, devolvemos stale cache (si existe) y NO crashea.
    """
    t = ticker.strip().upper()
    key = f"yf:quote:{t}"
    ttl = 60 * 5

    def _load():
        import yfinance as yf

        tk = yf.Ticker(t)

        hist = yf_call(lambda: tk.history(period="2d", interval="1d", auto_adjust=True))

        last_price = net = pct = vol = asof = None
        if hist is not None and not hist.empty:
            last_close = float(hist["Close"].iloc[-1])
            last_price = last_close
            asof = str(hist.index[-1].date())
            vol = int(hist["Volume"].iloc[-1]) if "Volume" in hist else None

            if len(hist) >= 2:
                prev = float(hist["Close"].iloc[-2])
                net = last_close - prev
                pct = (net / prev) * 100 if prev else None

        # currency/exchange quedan best-effort (None) para NO disparar requests extra
        return {
            "ticker": t,
            "company_name": None,
            "exchange": None,
            "asset_class": "STOCKS",
            "last_price": float(last_price) if last_price is not None else None,
            "net_change": float(net) if net is not None else None,
            "pct_change": float(pct) if pct is not None else None,
            "volume": vol,
            "currency": None,
            "asof": asof,
        }

    return _cache_get_or_set(key, ttl, _load)


# -----------------------------
# PROFILE (TTL 30 días)
# -----------------------------
def get_profile_data(ticker: str) -> dict:
    """
    Perfil robusto con fallback: TTL 30 días.
    (Si Yahoo rate-limitea, stale-if-error evita caída.)
    """
    t = ticker.strip().upper()
    key = f"yf:profile:{t}"
    ttl = 60 * 60 * 24 * 30

    def _load():
        import yfinance as yf

        tk = yf.Ticker(t)

        info1 = yf_call(lambda: tk.info or {}) or {}
        info2 = {}
        try:
            if hasattr(tk, "get_info"):
                info2 = yf_call(lambda: tk.get_info() or {}) or {}
        except Exception:
            pass

        info3 = {}
        try:
            info3 = yf_call(lambda: getattr(tk, "basic_info", {}) or {}) or {}
        except Exception:
            pass

        info4 = {}
        try:
            info4 = yf_call(lambda: getattr(tk, "fast_info", {}) or {}) or {}
        except Exception:
            pass

        info5 = {}
        try:
            info5 = yf_call(lambda: getattr(tk, "history_metadata", {}) or {}) or {}
        except Exception:
            pass

        def merge(dicts):
            result = {}
            for d in dicts:
                if not isinstance(d, dict):
                    continue
                for k, v in d.items():
                    if k not in result or result[k] is None:
                        result[k] = v
            return result

        merged = merge([info1, info2, info3, info5, info4])
        merged = _json_safe(merged)
        short = merged.get("shortName") or merged.get("longName")

        return {
            "website": merged.get("website"),
            "industry": merged.get("industry"),
            "sector": merged.get("sector"),
            "longBusinessSummary": merged.get("longBusinessSummary"),
            "fullTimeEmployees": merged.get("fullTimeEmployees"),
            "country": merged.get("country"),
            "city": merged.get("city"),
            "address1": merged.get("address1"),
            "phone": merged.get("phone"),
            "shortName": short,
            "raw": merged,
        }

    return _cache_get_or_set(key, ttl, _load)


# -----------------------------
# FINANCIAL SNAPSHOT (TTL 90 días)
# -----------------------------
def get_financial_data(ticker: str) -> dict:
    """
    Snapshot financiero: TTL 90 días.
    """
    t = ticker.strip().upper()
    key = f"yf:financial:{t}"
    ttl = 60 * 60 * 24 * 90

    def _load():
        import yfinance as yf

        tk = yf.Ticker(t)
        info = yf_call(lambda: tk.info or {}) or {}
        info = _json_safe(info)

        return {
            "financial_currency": info.get("financialCurrency") or info.get("currency"),
            "current_price": info.get("currentPrice"),
            "target_mean_price": info.get("targetMeanPrice"),
            "recommendation_key": info.get("recommendationKey"),
            "analyst_opinions": info.get("numberOfAnalystOpinions"),
            "total_cash": info.get("totalCash"),
            "total_debt": info.get("totalDebt"),
            "ebitda": info.get("ebitda"),
            "total_revenue": info.get("totalRevenue"),
            "gross_profits": info.get("grossProfits"),
            "free_cashflow": info.get("freeCashflow"),
            "operating_cashflow": info.get("operatingCashflow"),
            "quick_ratio": info.get("quickRatio"),
            "current_ratio": info.get("currentRatio"),
            "debt_to_equity": info.get("debtToEquity"),
            "roe": info.get("returnOnEquity"),
            "roa": info.get("returnOnAssets"),
            "earnings_growth": info.get("earningsGrowth"),
            "revenue_growth": info.get("revenueGrowth"),
            "gross_margins": info.get("grossMargins"),
            "ebitda_margins": info.get("ebitdaMargins"),
            "operating_margins": info.get("operatingMargins"),
            "profit_margins": info.get("profitMargins"),
        }

    return _cache_get_or_set(key, ttl, _load)


# -----------------------------
# KEY STATS (TTL 30 días)
# -----------------------------
def get_key_stats(ticker: str) -> dict:
    """
    Devuelve Beta, PER TTM, EPS TTM y Target 1Y (con fallback).
    TTL 30 días.
    """
    t = ticker.strip().upper()
    key = f"yf:keystats:{t}"
    ttl = 60 * 60 * 24 * 30

    def _load():
        prof = get_profile_data(t)
        raw = prof.get("raw") if isinstance(prof, dict) else {}

        beta = raw.get("beta")
        pe = raw.get("trailingPE") or raw.get("peTrailingTwelveMonths")
        eps = raw.get("epsTrailingTwelveMonths") or raw.get("trailingEps")
        target = raw.get("targetMeanPrice") or raw.get("targetMedianPrice") or raw.get("targetHighPrice")

        if target is None:
            fin = get_financial_data(t)
            target = fin.get("target_mean_price")

        return {
            "beta": beta,
            "pe_ttm": pe,
            "eps_ttm": eps,
            "target_1y": target,
        }

    return _cache_get_or_set(key, ttl, _load)
