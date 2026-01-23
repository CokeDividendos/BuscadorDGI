from __future__ import annotations

from datetime import datetime, date
from typing import Any, Callable

import numpy as np

from src.services.cache_store import cache_get, cache_set
from src.services.yf_client import install_http_cache, yf_call

class FinanceDataError(RuntimeError):
    pass

install_http_cache(expire_seconds=3600)

def _json_safe(x: Any) -> Any:
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
    try:
        if isinstance(x, np.integer):
            return int(x)
        if isinstance(x, np.floating):
            return float(x)
        if isinstance(x, np.bool_):
            return bool(x)
    except Exception:
        pass
    try:
        if hasattr(x, "items"):
            return {str(k): _json_safe(v) for k, v in dict(x).items()}
    except Exception:
        pass
    return str(x)

def _cache_get_or_set(key: str, ttl: int, fn: Callable[[], Any]):
    hit = cache_get(key)
    if hit is not None:
        return hit
    val = fn()
    val = _json_safe(val)
    cache_set(key, val, ttl_seconds=ttl)
    return val

def get_price_data(ticker: str) -> dict:
    t = ticker.strip().upper()
    key = f"yf:quote:{t}"
    ttl = 60 * 5

    def _load():
        import yfinance as yf
        tk = yf.Ticker(t)

        fast = yf_call(lambda: getattr(tk, "fast_info", {}) or {})
        price = fast.get("last_price") or fast.get("last") or None
        currency = fast.get("currency")
        exchange = fast.get("exchange")

        hist = yf_call(lambda: tk.history(period="2d", interval="1d", auto_adjust=True))
        net = pct = vol = asof = None

        if hist is not None and not hist.empty:
            last_close = float(hist["Close"].iloc[-1])
            asof = str(hist.index[-1].date())
            vol = int(hist["Volume"].iloc[-1]) if "Volume" in hist else None

            if price is None:
                price = last_close
            else:
                try:
                    price = float(price)
                except Exception:
                    price = last_close

            if len(hist) >= 2:
                prev = float(hist["Close"].iloc[-2])
                net = last_close - prev
                pct = (net / prev) * 100 if prev else None

        return {
            "ticker": t,
            "exchange": exchange,
            "asset_class": "STOCKS",
            "last_price": float(price) if price is not None else None,
            "net_change": float(net) if net is not None else None,
            "pct_change": float(pct) if pct is not None else None,
            "volume": vol,
            "currency": currency,
            "asof": asof,
        }

    return _cache_get_or_set(key, ttl, _load)

def get_profile_data(ticker: str) -> dict:
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

def get_key_stats(ticker: str) -> dict:
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

        return {"beta": beta, "pe_ttm": pe, "eps_ttm": eps, "target_1y": target}

    return _cache_get_or_set(key, ttl, _load)

def get_dividend_kpis(ticker: str) -> dict:
    """
    KPIs de dividendos. Cache 24h. Solo yfinance.
    Retorna:
      - div_yield (%)
      - fwd_div_yield (%)
      - annual_div ($)
      - payout (%)
      - ex_date (str)
      - next_div (str)
    """
    t = (ticker or "").strip().upper()
    key = f"yf:divkpis:{t}"
    ttl = 60 * 60 * 24  # 24h

    def _load():
        import yfinance as yf

        # Precio (usa tu get_price_data si existe)
        try:
            price = get_price_data(t) or {}
            last_price = price.get("last_price")
        except Exception:
            last_price = None

        tk = yf.Ticker(t)

        annual = None
        div_yield = None
        fwd_yield = None
        payout = None
        ex_date = None
        next_div = None

        # Dividendos históricos
        try:
            divs = tk.dividends
        except Exception:
            divs = None

        if divs is not None and len(divs) > 0:
            try:
                # trailing 12m
                last_dt = divs.index.max()
                cutoff = last_dt - __import__("pandas").Timedelta(days=365)
                div_12m = divs[divs.index >= cutoff]
                annual = float(div_12m.sum()) if len(div_12m) else float(divs.tail(4).sum())

                # forward anual (heurística simple)
                last_div = float(divs.iloc[-1])
                freq = max(1, min(12, int(len(div_12m)) if len(div_12m) else 4))
                forward_annual = last_div * freq

                if isinstance(last_price, (int, float)) and last_price:
                    div_yield = (annual / last_price) * 100 if annual is not None else None
                    fwd_yield = (forward_annual / last_price) * 100 if forward_annual is not None else None
            except Exception:
                pass

        # Payout = annual / EPS(TTM)
        try:
            stats = get_key_stats(t) or {}
            eps = stats.get("eps_ttm")
            if isinstance(annual, (int, float)) and isinstance(eps, (int, float)) and eps:
                payout = (annual / eps) * 100
        except Exception:
            pass

        # Ex-date / próximo dividendo: best effort vía calendar
        try:
            cal = tk.calendar
            if cal is not None and hasattr(cal, "columns") and len(cal.columns) > 0:
                for col in cal.columns:
                    cname = str(col).lower()
                    v = cal[col].iloc[0]
                    v_str = None
                    try:
                        v_str = v.date().isoformat()
                    except Exception:
                        v_str = str(v)

                    if ("ex" in cname and "div" in cname) or ("ex-div" in cname):
                        ex_date = v_str
                    if ("dividend" in cname and "date" in cname and "ex" not in cname):
                        next_div = v_str
        except Exception:
            pass

        return {
            "div_yield": div_yield,
            "fwd_div_yield": fwd_yield,
            "annual_div": annual,
            "payout": payout,
            "ex_date": ex_date,
            "next_div": next_div,
        }

    # usa tu caché SQLite si ya tienes helpers tipo _cache_get_or_set / cache_get / cache_set
    try:
        return _cache_get_or_set(key, ttl, _load)  # si existe en tu finance_data.py
    except Exception:
        # fallback simple si no existe
        try:
            from src.services.cache_store import cache_get, cache_set
            hit = cache_get(key)
            if hit is not None:
                return hit
            val = _load()
            cache_set(key, val, ttl_seconds=ttl)
            return val
        except Exception:
            return _load()

    return _cache_get_or_set(key, ttl, _load)
