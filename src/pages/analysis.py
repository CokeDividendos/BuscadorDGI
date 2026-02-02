# src/pages/analysis.py
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from src.auth import is_admin
from src.services.cache_store import cache_clear_all
from src.services.finance_data import get_key_stats, get_price_data, get_profile_data, get_dividend_kpis
from src.services.logos import logo_candidates
from src.services.usage_limits import consume_search, remaining_searches


# =========================================================
# Constantes
# =========================================================
YEARS = 5
DIVIDENDS_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 días


# =========================================================
# Helper Functions
# =========================================================
def _get_user_email() -> str:
    """Get the logged-in user's email from session state."""
    for key in ["auth_email", "user_email", "email", "username", "user", "logged_email"]:
        v = st.session_state.get(key)
        if isinstance(v, str) and "@" in v:
            return v.strip().lower()
    return ""


def _fmt_price(x: Any, currency: str) -> str:
    """Format a price as a currency value."""
    if not isinstance(x, (int, float)) or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "N/D"
    s = f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} {currency}".strip()


def _fmt_kpi(x, suffix: str = "", decimals: int = 2) -> str:
    """Format key performance indicator values."""
    return f"{x:.{decimals}f}{suffix}" if isinstance(x, (int, float)) else "N/D"


# =========================================================
# Dividendos: Carga y Cálculos
# =========================================================

@st.cache_data(ttl=DIVIDENDS_CACHE_TTL_SECONDS, show_spinner=False)
def _load_dividend_inputs(ticker: str, years: int) -> Dict[str, Any]:
    """Load dividend and financial data for a given stock ticker."""
    t = yf.Ticker(ticker)
    try:
        price_daily = t.history(period=f"{years}y", interval="1d", auto_adjust=False)
        if "Close" not in price_daily.columns and not price_daily.empty:
            price_daily["Close"] = price_daily.iloc[:, -1]
        price_daily = price_daily[["Close"]].dropna()
    except Exception:
        price_daily = pd.DataFrame(columns=["Close"])

    dividends = t.dividends.dropna().astype(float) if isinstance(t.dividends, pd.Series) else pd.Series(dtype=float)
    cashflow = t.cashflow.copy() if isinstance(t.cashflow, pd.DataFrame) else pd.DataFrame()

    return {"price_daily": price_daily, "dividends": dividends, "cashflow": cashflow}


# =========================================================
# Página principal
# =========================================================
def page_analysis() -> None:
    DAILY_LIMIT = 3
    user_email = _get_user_email()
    admin = is_admin()

    # CSS
    st.markdown(
        """
        <style>
        /* KPI Section */
        .kpi-section {
            background: #ffffff;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 10px 28px rgba(20,20,20,0.08);
            margin: 20px 0;
        }
        .kpi-container {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 2rem;
            padding: 1rem;
        }
        .kpi-card {
            text-align: center;
        }
        .kpi-label {
            font-size: 0.9rem;
            color: #666;
        }
        .kpi-value {
            font-size: 1.5rem;
            font-weight: bold;
        }

        /* Remove shadow from Plotly charts */
        .stPlotlyChart div[data-testid="stPlotlyChart"] {
            box-shadow: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        if admin:
            if st.button("🧹 Limpiar caché", key="clear_cache_btn", use_container_width=True):
                cache_clear_all()
                st.success("Caché limpiado.")
                st.rerun()

    # Sección de KPIs
    st.markdown('<div class="kpi-section">', unsafe_allow_html=True)
    st.markdown("<h3>KPIs clave</h3>", unsafe_allow_html=True)
    st.markdown('<div class="kpi-container">', unsafe_allow_html=True)

    # Obtener los datos KPI
    stats = get_key_stats("AAPL")  # Cambia el ticker como necesites
    divk = get_dividend_kpis("AAPL")

    beta = _fmt_kpi(stats.get("beta"))
    pe_ttm = _fmt_kpi(stats.get("pe_ttm")) + "x"
    eps_ttm = _fmt_kpi(stats.get("eps_ttm"))
    target_1y = _fmt_kpi(stats.get("target_1y"))
    div_yield = _fmt_kpi(divk.get("div_yield", "dividend_yield"), suffix="%", decimals=2)
    fwd_div_yield = _fmt_kpi(divk.get("fwd_div_yield", "forward_dividend_yield"), suffix="%", decimals=2)
    annual_dividend = _fmt_kpi(divk.get("annual_dividend"), decimals=2)
    payout_ratio = _fmt_kpi(divk.get("payout_ratio"), suffix="%", decimals=2)

    kpis = [
        {"label": "Beta", "value": beta},
        {"label": "PER (TTM)", "value": pe_ttm},
        {"label": "EPS (TTM)", "value": eps_ttm},
        {"label": "Target 1Y", "value": target_1y},
        {"label": "Dividend Yield", "value": div_yield},
        {"label": "Forward Div. Yield", "value": fwd_div_yield},
        {"label": "Div. anual ($)", "value": annual_dividend},
        {"label": "PayOut Ratio", "value": payout_ratio},
    ]

    # Mostrar KPIs en una tarjeta
    for kpi in kpis:
        st.markdown(
            f"""
            <div class='kpi-card'>
                <div class='kpi-label'>{kpi["label"]}</div>
                <div class='kpi-value'>{kpi["value"]}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    st.divider()
