from __future__ import annotations

from datetime import datetime, date
from typing import Any, Callable

import numpy as np

from src.services.cache_store import cache_get, cache_set
from src.services.yf_client import install_http_cache, yf_call

# Constants for dividend frequency detection (in days)
MONTHLY_THRESHOLD_DAYS = 40      # < 40 days between payments = monthly
QUARTERLY_THRESHOLD_DAYS = 120   # < 120 days between payments = quarterly  
SEMIANNUAL_THRESHOLD_DAYS = 270  # < 270 days between payments = semi-annual
# >= 270 days between payments = annual

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

def _calculate_annual_dividend(divs) -> float | None:
    """
    Calculate trailing 12-month (TTM) dividend sum.

    Strategy:
    1. Sum ALL payments that fall within the trailing 365 days ending today (UTC).
       Using today as the end date avoids counting an extra payment that can occur
       when anchoring the window to the last payment date (e.g. 5 quarterly payments
       instead of 4 for tickers like NKE).
    2. If the TTM window contains no payments, extrapolate from detected frequency.

    Args:
        divs: Pandas Series with dividend history (index = dates, values = dividend amounts)

    Returns:
        Annual dividend amount or None if cannot be calculated
    """
    if divs is None or len(divs) == 0:
        return None

    try:
        import pandas as pd

        # Work on a copy with a normalised timezone-naive DatetimeIndex
        s = divs.copy()
        if not isinstance(s.index, pd.DatetimeIndex):
            s.index = pd.to_datetime(s.index, errors="coerce")
            s = s[s.index.notna()]

        if getattr(s.index, "tz", None) is not None:
            s.index = s.index.tz_convert("UTC").tz_localize(None)

        # Trailing 365-day window anchored to today (UTC), not to the last payment
        end_date = pd.Timestamp.now("UTC").tz_localize(None)
        start_date = end_date - pd.DateOffset(days=365)

        ttm = s[(s.index > start_date) & (s.index <= end_date)]

        if len(ttm) >= 1:
            return float(ttm.sum())

        # Fallback: extrapolate from detected payment frequency
        if len(s) < 2:
            return None

        time_diffs = s.index.to_series().diff().dropna()
        avg_days_between = time_diffs.dt.days.median()

        if avg_days_between < MONTHLY_THRESHOLD_DAYS:
            payments_per_year = 12
        elif avg_days_between < QUARTERLY_THRESHOLD_DAYS:
            payments_per_year = 4
        elif avg_days_between < SEMIANNUAL_THRESHOLD_DAYS:
            payments_per_year = 2
        else:
            payments_per_year = 1

        last_payment = float(s.iloc[-1])
        return last_payment * payments_per_year

    except Exception:
        return None


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
                # Calculate trailing 12-month (TTM) dividend
                annual = _calculate_annual_dividend(divs)
            except Exception:
                annual = None

        # Fallback: use dividendRate from cached profile data (no extra API call)
        if annual is None:
            try:
                prof = get_profile_data(t)
                raw = prof.get("raw") if isinstance(prof, dict) else {}
                rate = raw.get("dividendRate")
                if isinstance(rate, (int, float)) and rate > 0:
                    annual = float(rate)
            except Exception:
                pass

        if annual is not None:
            try:
                forward_annual = annual
                if isinstance(last_price, (int, float)) and last_price:
                    div_yield = (annual / last_price) * 100
                    fwd_yield = (forward_annual / last_price) * 100
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


def get_price_history(ticker: str, period: str = "5y", interval: str = "1d", auto_adjust: bool = False) -> "pd.DataFrame":
    """
    Centralized, cached function for price history.

    Returns a DataFrame with a single 'Close' column (normalized).
    Returns an empty DataFrame with 'Close' column if the fetch fails.

    TTL:
      - "5y"/"1d" or "1y"/"1d" → 24 hours
      - anything else            → 5 minutes
    """
    import pandas as pd

    t = (ticker or "").strip().upper()
    key = f"yf:history:{t}:{period}:{interval}:{auto_adjust}"

    if period in ("5y", "1y") and interval == "1d":
        ttl = 60 * 60 * 24  # 24h
    else:
        ttl = 60 * 5  # 5 min

    cached = cache_get(key)
    if cached is not None:
        try:
            if isinstance(cached, dict) and cached:
                return pd.DataFrame.from_dict(cached, orient="tight")
        except Exception:
            pass
        return pd.DataFrame(columns=["Close"])

    # Fetch from yfinance
    hist = pd.DataFrame(columns=["Close"])
    try:
        import yfinance as yf
        tk = yf.Ticker(t)
        raw = yf_call(lambda: tk.history(period=period, interval=interval, auto_adjust=auto_adjust))
        if raw is not None and isinstance(raw, pd.DataFrame) and not raw.empty:
            if "Close" not in raw.columns:
                close_cols = [c for c in raw.columns if str(c).lower() == "close"]
                if close_cols:
                    raw["Close"] = raw[close_cols[0]]
            if "Close" in raw.columns:
                hist = raw[["Close"]].dropna()
    except Exception:
        pass

    if not hist.empty:
        cache_set(key, hist.to_dict(orient="tight"), ttl_seconds=ttl)

    return hist


def get_52w_range(ticker: str) -> dict:
    """
    Get 52-week range data (low, high, current price).
    Cache 30 days. Uses yfinance info first, falls back to historical data.
    
    Returns:
      - low_52w: 52-week low price
      - high_52w: 52-week high price
      - current_price: current/latest price
    """
    t = (ticker or "").strip().upper()
    key = f"yf:52w_range:{t}"
    ttl = 60 * 60 * 24 * 30  # 30 days

    def _load():
        import yfinance as yf
        
        # Try to get from profile/info first
        low_52w = None
        high_52w = None
        current_price = None
        
        try:
            prof = get_profile_data(t)
            raw = prof.get("raw") if isinstance(prof, dict) else {}
            
            # Try different field names for 52-week data
            low_52w = raw.get("fiftyTwoWeekLow") or raw.get("52WeekLow")
            high_52w = raw.get("fiftyTwoWeekHigh") or raw.get("52WeekHigh")
            current_price = raw.get("currentPrice") or raw.get("regularMarketPrice")
        except Exception:
            pass
        
        # If we don't have 52W data, calculate from 1-year history
        if low_52w is None or high_52w is None:
            try:
                tk = yf.Ticker(t)
                hist = yf_call(lambda: tk.history(period="1y", interval="1d", auto_adjust=True))
                
                if hist is not None and not hist.empty and "Close" in hist.columns:
                    low_52w = float(hist["Close"].min())
                    high_52w = float(hist["Close"].max())
                    
                    # Get current price from latest close if not available
                    if current_price is None:
                        current_price = float(hist["Close"].iloc[-1])
            except Exception:
                pass
        
        # Try to get current price from get_price_data if still None
        if current_price is None:
            try:
                price_data = get_price_data(t)
                current_price = price_data.get("last_price")
            except Exception:
                pass
        
        return {
            "low_52w": float(low_52w) if low_52w is not None else None,
            "high_52w": float(high_52w) if high_52w is not None else None,
            "current_price": float(current_price) if current_price is not None else None,
        }
    
    return _cache_get_or_set(key, ttl, _load)
