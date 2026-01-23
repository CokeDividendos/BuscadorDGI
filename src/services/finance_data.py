# src/services/finance_data.py
from __future__ import annotations

from datetime import datetime, date
from typing import Any, Callable

import pandas as pd
import numpy as np

from src.services.cache_store import cache_get, cache_set
from src.services.yf_client import install_http_cache, yf_call

# ✅ NUEVO: SEC fundamentals (sin romper la fachada)
from src.services.sec_data import get_fundamentals_minimal

class FinanceDataError(RuntimeError):
    pass

# Activa cache HTTP para yfinance
install_http_cache(expire_seconds=3600)


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


def _cache_get_or_set(key: str, ttl: int, fn: Callable[[], Any]):
    hit = cache_get(key)
    if hit is not None:
        return hit
    val = fn()
    val = _json_safe(val)
    cache_set(key, val, ttl_seconds=ttl)
    return val


def _to_iso_date(v: Any) -> str | None:
    """
    Convierte epoch (seg), epoch(ms), datetime/date o str -> 'YYYY-MM-DD'
    """
    if v is None:
        return None
    try:
        if isinstance(v, (datetime, date)):
            return v.date().isoformat() if isinstance(v, datetime) else v.isoformat()
        if isinstance(v, (int, float)):
            ts = float(v)
            if ts > 10_000_000_000:
                ts = ts / 1000.0
            return datetime.utcfromtimestamp(ts).date().isoformat()
        if isinstance(v, str):
            s = v.strip()
            if len(s) >= 10:
                return s[:10]
            return s
    except Exception:
        return None
    return None


def get_price_data(ticker: str) -> dict:
    """
    Devuelve datos de precio con TTL 5 minutos.
    (Robusto ante rate-limit: si fast_info dispara error, igual intenta con history)
    """
    t = ticker.strip().upper()
    key = f"yf:quote:{t}"
    ttl = 60 * 5

    def _load():
        import yfinance as yf
        tk = yf.Ticker(t)

        price = None
        currency = None
        exchange = None

        try:
            fast = yf_call(lambda: getattr(tk, "fast_info", None))
            fast_dict = {}
            if isinstance(fast, dict):
                fast_dict = fast
            else:
                try:
                    fast_dict = dict(fast)
                except Exception:
                    fast_dict = {}
            price = fast_dict.get("last_price") or fast_dict.get("last") or None
            currency = fast_dict.get("currency") or None
            exchange = fast_dict.get("exchange") or None
        except Exception:
            pass

        hist = None
        try:
            hist = yf_call(lambda: tk.history(period="2d", interval="1d", auto_adjust=True))
        except Exception:
            hist = None

        net = pct = vol = asof = None
        if hist is not None and isinstance(hist, pd.DataFrame) and not hist.empty and "Close" in hist:
            try:
                last_close = float(hist["Close"].iloc[-1])
                asof = str(hist.index[-1].date())
                if "Volume" in hist:
                    try:
                        vol = int(hist["Volume"].iloc[-1])
                    except Exception:
                        vol = None

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
            except Exception:
                pass

        return {
            "ticker": t,
            "company_name": None,
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
    """
    Perfil robusto con fallback: TTL 30 días.
    (Se mantiene en yfinance por ahora; no es la parte “pesada” comparado con fundamentals)
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

        merged = {}
        for d in (info3, info2, info1):
            if isinstance(d, dict):
                merged.update(d)

        long = merged.get("longName") or merged.get("shortName") or None
        short = merged.get("shortName") or None
        website = merged.get("website") or None
        sector = merged.get("sector") or None
        industry = merged.get("industry") or None

        return {
            "longName": long,
            "shortName": short,
            "website": website,
            "sector": sector,
            "industry": industry,
            "raw": _json_safe(merged),
        }

    return _cache_get_or_set(key, ttl, _load)


# -----------------------------
# ✅ NUEVO: SEC fundamentals (cacheados)
# -----------------------------
def get_sec_fundamentals(ticker: str) -> dict:
    """
    Fundamentals “mínimos” desde SEC (companyfacts).
    TTL 24h.
    """
    t = ticker.strip().upper()
    key = f"sec:fundamentals:{t}"
    ttl = 60 * 60 * 24

    def _load():
        return get_fundamentals_minimal(t) or {}

    return _cache_get_or_set(key, ttl, _load)


def get_financial_data(ticker: str) -> dict:
    """
    Snapshot financiero.
    ✅ Antes: yfinance (TTL 90 días)
    ✅ Ahora: intenta SEC primero y rellena, con fallback a yfinance para campos “market/analyst”.

    TTL recomendado: 24h (SEC) — porque se recalcula fácil y depende de filings.
    """
    t = ticker.strip().upper()
    key = f"mix:financial:{t}"
    ttl = 60 * 60 * 24  # 24h

    def _load():
        # 1) SEC fundamentals
        sec = get_sec_fundamentals(t) or {}
        latest = (sec.get("latest") or {}) if isinstance(sec, dict) else {}
        price = get_price_data(t) or {}
        last_price = price.get("last_price")

        revenue = latest.get("revenue")
        net_income = latest.get("net_income")
        assets = latest.get("assets")
        liabilities = latest.get("liabilities")
        equity = latest.get("equity")
        cash = latest.get("cash")
        debt = latest.get("debt")
        operating_cf = latest.get("operating_cf")
        capex = latest.get("capex")
        free_cf = latest.get("free_cf")

        # Ratios “calculables” (best effort)
        profit_margin = None
        if isinstance(revenue, (int, float)) and revenue and isinstance(net_income, (int, float)):
            profit_margin = float(net_income) / float(revenue)

        roe = None
        if isinstance(equity, (int, float)) and equity and isinstance(net_income, (int, float)):
            roe = float(net_income) / float(equity)

        # Growth YoY (revenue y earnings) desde series SEC
        rev_growth = earn_growth = None
        series = (sec.get("series") or {}) if isinstance(sec, dict) else {}
        rev_series = series.get("revenue") or []
        ni_series = series.get("net_income") or []

        def _yoy(series_rows):
            if not isinstance(series_rows, list) or len(series_rows) < 2:
                return None
            a = series_rows[-2].get("value")
            b = series_rows[-1].get("value")
            try:
                a = float(a)
                b = float(b)
                if a == 0:
                    return None
                return (b - a) / a
            except Exception:
                return None

        rev_growth = _yoy(rev_series)
        earn_growth = _yoy(ni_series)

        # 2) Campos de mercado/analistas (yfinance fallback)
        yinfo = {}
        try:
            import yfinance as yf
            tk = yf.Ticker(t)
            yinfo = yf_call(lambda: tk.info or {}) or {}
            yinfo = _json_safe(yinfo)
        except Exception:
            yinfo = {}

        # Lo que sí seguimos tomando de yfinance (cuando exista)
        fin_currency = yinfo.get("financialCurrency") or yinfo.get("currency")
        target_mean = yinfo.get("targetMeanPrice")
        reco = yinfo.get("recommendationKey")
        analyst_ops = yinfo.get("numberOfAnalystOpinions")

        # Liquidez / ratios contables que antes venían de yfinance: si no están, N/D
        # (se pueden calcular luego desde SEC con más mapeo)
        quick_ratio = yinfo.get("quickRatio")
        current_ratio = yinfo.get("currentRatio")
        debt_to_equity = yinfo.get("debtToEquity")

        # Márgenes (si yfinance los tiene, los dejamos como fallback)
        gross_margins = yinfo.get("grossMargins")
        ebitda_margins = yinfo.get("ebitdaMargins")
        operating_margins = yinfo.get("operatingMargins")

        return {
            "financial_currency": fin_currency,

            # Precio/mercado
            "current_price": last_price if isinstance(last_price, (int, float)) else yinfo.get("currentPrice"),
            "target_mean_price": target_mean,
            "recommendation_key": reco,
            "analyst_opinions": analyst_ops,

            # Balance / fundamentals (SEC)
            "total_cash": cash,
            "total_debt": debt,
            "total_revenue": revenue,
            "gross_profits": latest.get("gross_profit"),
            "operating_cashflow": operating_cf,
            "free_cashflow": free_cf,

            # Ratios / crecimiento (SEC best effort)
            "roe": roe,                          # (decimal)
            "earnings_growth": earn_growth,      # (decimal YoY)
            "revenue_growth": rev_growth,        # (decimal YoY)
            "profit_margins": profit_margin,     # (decimal)

            # Fallback yfinance / por completar (no rompe)
            "ebitda": yinfo.get("ebitda"),
            "quick_ratio": quick_ratio,
            "current_ratio": current_ratio,
            "debt_to_equity": debt_to_equity,
            "gross_margins": gross_margins,
            "ebitda_margins": ebitda_margins,
            "operating_margins": operating_margins,
        }

    return _cache_get_or_set(key, ttl, _load)


def get_key_stats(ticker: str) -> dict:
    """
    Devuelve Beta, PER TTM, EPS TTM y Target 1Y.
    Se mantiene híbrido:
      - Beta/Target: yfinance
      - EPS: yfinance (por ahora), luego se puede calcular desde SEC (TTM)
      - PER: calculado con precio/eps cuando sea posible
    TTL 30 días.
    """
    t = ticker.strip().upper()
    key = f"mix:keystats:{t}"
    ttl = 60 * 60 * 24 * 30

    def _load():
        prof = get_profile_data(t)
        raw = prof.get("raw") if isinstance(prof, dict) else {}

        beta = raw.get("beta")
        eps = raw.get("epsTrailingTwelveMonths") or raw.get("trailingEps")
        target = raw.get("targetMeanPrice") or raw.get("targetMedianPrice") or raw.get("targetHighPrice")

        # Precio actual para PER
        price = get_price_data(t) or {}
        last_price = price.get("last_price")

        pe_calc = None
        if isinstance(last_price, (int, float)) and isinstance(eps, (int, float)) and eps:
            try:
                pe_calc = float(last_price) / float(eps)
            except Exception:
                pe_calc = None

        # fallback a yfinance trailingPE si existe
        pe = pe_calc or raw.get("trailingPE") or raw.get("peTrailingTwelveMonths")

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


# ✅ Se mantiene: KPIs dividendos (yfinance)
def get_dividend_kpis(ticker: str) -> dict:
    """
    KPIs para cards de dividendos (6):
    - Dividend Yield (%): anual / precio (si posible)
    - Forward Div. Yield (%): (dividendRate / precio) o dividendYield*100
    - Dividendo Anual $: dividendRate o trailingAnnualDividendRate
    - PayOut Ratio (%): (anual / EPS TTM)*100 o payoutRatio*100
    - Ex-Date fecha: exDividendDate (YYYY-MM-DD)
    - Próximo Dividendo $: lastDividendValue (fallback)
    TTL: 24h (varía poco)
    """
    t = ticker.strip().upper()
    key = f"yf:divkpis:{t}"
    ttl = 60 * 60 * 24  # 24h

    def _load():
        prof = get_profile_data(t) or {}
        raw = prof.get("raw") if isinstance(prof, dict) else {}
        price = get_price_data(t) or {}
        stats = get_key_stats(t) or {}

        last_price = price.get("last_price")
        eps_ttm = stats.get("eps_ttm")

        annual = (
            raw.get("dividendRate")
            or raw.get("trailingAnnualDividendRate")
            or None
        )
        try:
            annual = float(annual) if annual is not None else None
        except Exception:
            annual = None

        nxt = raw.get("lastDividendValue")
        try:
            nxt = float(nxt) if nxt is not None else None
        except Exception:
            nxt = None

        div_yield = None
        if isinstance(last_price, (int, float)) and last_price and isinstance(annual, (int, float)):
            div_yield = (annual / float(last_price)) * 100.0

        fwd_yield = None
        dy_raw = raw.get("dividendYield")
        if isinstance(dy_raw, (int, float)):
            fwd_yield = float(dy_raw) * 100.0
        elif div_yield is not None:
            fwd_yield = div_yield

        pr_raw = raw.get("payoutRatio")
        payout = None
        if isinstance(pr_raw, (int, float)):
            payout = float(pr_raw) * 100.0
        else:
            if isinstance(annual, (int, float)) and isinstance(eps_ttm, (int, float)) and eps_ttm:
                try:
                    payout = (float(annual) / float(eps_ttm)) * 100.0
                except Exception:
                    payout = None

        exd = _to_iso_date(raw.get("exDividendDate"))

        return {
            "dividend_yield": div_yield,
            "forward_div_yield": fwd_yield,
            "annual_dividend": annual,
            "payout_ratio": payout,
            "ex_div_date": exd,
            "next_dividend": nxt,
        }

    return _cache_get_or_set(key, ttl, _load)
