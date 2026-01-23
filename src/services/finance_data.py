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
    """
    t = ticker.strip().upper()
    key = f"yf:divkpis:{t}"
    ttl = 60 * 60 * 24

    def _load():
        import yfinance as yf
        tk = yf.Ticker(t)

        price = get_price_data(t)
        last_price = price.get("last_price")

        divs = yf_call(lambda: tk.dividends)  # Series
        annual = None
        trailing_yield = None
        forward_yield = None
        next_div = None
        ex_date = None

        if divs is not None and len(divs) > 0:
            # trailing 12m
            try:
                now = divs.index.max()
                cutoff = now - np.timedelta64(365, "D")
                div_12m = divs[divs.index >= cutoff]
                annual = float(div_12m.sum()) if len(div_12m) else float(divs.tail(4).sum())

                # forward annual (heurística: último dividendo * frecuencia estimada)
                last_div = float(divs.iloc[-1])
                freq = int(max(1, min(12, len(div_12m))))  # 1..12 aprox
                # si paga trimestral típico: len(div_12m)=4, ok
                forward_annual = last_div * freq

                if isinstance(last_price, (int, float)) and last_price:
                    trailing_yield = (annual / last_price) * 100 if annual is not None else None
                    forward_yield = (forward_annual / last_price) * 100 if forward_annual is not None else None

                # next dividend / ex-date: best effort vía calendar (puede fallar)
                try:
                    cal = yf_call(lambda: tk.calendar)
                    if cal is not None and hasattr(cal, "loc"):
                        # yfinance a veces trae "Ex-Dividend Date" y "Dividend Date"
                        for col in cal.columns:
                            cname = str(col).lower()
                            if "ex" in cname and "div" in cname:
                                ex_date = str(cal[col].iloc[0].date()) if hasattr(cal[col].iloc[0], "date") else str(cal[col].iloc[0])
                            if "dividend" in cname and "date" in cname and "ex" not in cname:
                                next_div = str(cal[col].iloc[0].date()) if hasattr(cal[col].iloc[0], "date") else str(cal[col].iloc[0])
                except Exception:
                    pass
            except Exception:
                pass

        # payout = annual / eps_ttm
        stats = get_key_stats(t)
        eps = stats.get("eps_ttm")
        payout = None
        if isinstance(annual, (int, float)) and isinstance(eps, (int, float)) and eps:
            payout = (annual / eps) * 100

        return {
            "div_yield": trailing_yield,
            "fwd_div_yield": forward_yield,
            "annual_div": annual,
            "payout": payout,
            "ex_date": ex_date,
            "next_div": next_div,
        }

    return _cache_get_or_set(key, ttl, _load)
