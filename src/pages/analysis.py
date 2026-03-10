# src/pages/analysis.py
from __future__ import annotations

import math
import random
import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

# IMPORTAR sólo is_admin desde auth — _get_user_email se define localmente
from src.auth import is_admin
from src.services.cache_store import cache_clear_all, cache_get, cache_set
from src.db import get_user_gpt_api_key, get_user_perplexity_api_key
from src.services.blog import get_blog_posts_by_ticker
from src.services.finance_data import (
    get_key_stats,
    get_price_data,
    get_profile_data,
    get_dividend_kpis,
    get_52w_range,
)
from src.services.logos import logo_candidates
from src.services.usage_limits import consume_search, remaining_searches

# =========================================================
# Constantes
# =========================================================
YEARS = 5
DIVIDENDS_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 días
FINANCIAL_STATEMENTS_CACHE_TTL = 60 * 60 * 24 * 90  # 3 months for balance, income, cashflow

# Retry configuration for yfinance API calls
# MAX_ATTEMPTS includes the initial attempt (e.g., 3 = 1 initial + 2 retries)
# With BASE_DELAY=2, backoff delays are: 2s after attempt 1, 4s after attempt 2
MAX_ATTEMPTS = 3
RETRY_BASE_DELAY = 2  # Base delay in seconds for exponential backoff
RETRY_JITTER_MIN = 0.0
RETRY_JITTER_MAX = 0.5

# Color scheme constants
COLOR_PRIMARY = "#ff6d01"     # Orange - Primary chart elements
COLOR_SECONDARY = "#ff00ff"   # Magenta - Secondary chart elements
COLOR_TERTIARY = "#01c2ef"    # Cyan - Tertiary chart elements
COLOR_BACKGROUND = "#141f41"  # Dark blue - Chart background
COLOR_TEXT = "#ffffff"        # White - All text


# =========================================================
# Helpers UI / formato
# =========================================================
def _get_user_email() -> str:
    for key in ["auth_email", "user_email", "email", "username", "user", "logged_email"]:
        v = st.session_state.get(key)
        if isinstance(v, str) and "@" in v:
            return v.strip().lower()
    return ""


def _fmt_price(x: Any, currency: str) -> str:
    if not isinstance(x, (int, float)) or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "N/D"
    s = f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} {currency}".strip()


def _fmt_delta(net: Any, pct: Any) -> Tuple[Optional[str], Optional[float]]:
    if isinstance(net, (int, float)) and isinstance(pct, (int, float)):
        return f"{net:+.2f} ({pct:+.2f}%)", float(pct)
    return None, None


def _fmt_kpi(x: Any, suffix: str = "", decimals: int = 2) -> str:
    if not isinstance(x, (int, float)) or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "N/D"
    return f"{x:.{decimals}f}{suffix}"


def _fmt_large_number(value: float) -> str:
    """Format large numbers with B/M suffix"""
    if abs(value) >= 1e9:
        return f"${value/1e9:.2f}B"
    elif abs(value) >= 1e6:
        return f"${value/1e6:.2f}M"
    else:
        return f"${value:.2f}"


def _kpi_card(label: str, value: str) -> None:
    st.markdown(
        f"""
        <div class="kpi-card">
          <div class="kpi-label">{label}</div>
          <div class="kpi-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _divk_get(divk: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if not isinstance(divk, dict):
            continue
        v = divk.get(k)
        if v is not None:
            return v
    return None


# =========================================================
# Dividendos: carga y cálculos (cache)
# =========================================================
@st.cache_data(ttl=DIVIDENDS_CACHE_TTL_SECONDS, show_spinner=False)
def _load_dividend_inputs(ticker: str, years: int) -> Dict[str, Any]:
    t = yf.Ticker(ticker)

    try:
        price_daily = t.history(period=f"{years}y", interval="1d", auto_adjust=False)
    except Exception:
        price_daily = pd.DataFrame(columns=["Close"])

    if isinstance(price_daily, pd.DataFrame) and not price_daily.empty:
        if "Close" not in price_daily.columns:
            close_cols = [c for c in price_daily.columns if str(c).lower() == "close"]
            if close_cols:
                price_daily["Close"] = price_daily[close_cols[0]]
        price_daily = price_daily[["Close"]].dropna()
    else:
        price_daily = pd.DataFrame(columns=["Close"])

    dividends = t.dividends
    if dividends is None or not isinstance(dividends, pd.Series):
        dividends = pd.Series(dtype=float)
    else:
        dividends = dividends.dropna().astype(float)

    cashflow = t.cashflow
    if cashflow is None or not isinstance(cashflow, pd.DataFrame):
        cashflow = pd.DataFrame()

    return {"price_daily": price_daily, "dividends": dividends, "cashflow": cashflow}


def _annual_dividends_last_years(dividends: pd.Series, years: int) -> pd.Series:
    if dividends is None or dividends.empty:
        return pd.Series(dtype=float)

    ann = dividends.resample("Y").sum().dropna().astype(float)
    ann.index = ann.index.year

    current_year = datetime.now().year
    full_years = ann[ann.index < current_year]
    if full_years.empty:
        full_years = ann

    end = int(full_years.index.max())
    start = end - (years - 1)
    out = full_years.loc[start:end]
    return out.dropna()


def _cagr_from_annual(annual: pd.Series) -> Optional[float]:
    if annual is None or len(annual) < 2:
        return None
    first = float(annual.iloc[0])
    last = float(annual.iloc[-1])
    n = (int(annual.index[-1]) - int(annual.index[0]))
    if first <= 0 or n <= 0:
        return None
    return ((last / first) ** (1 / n) - 1) * 100


# =========================================================
# Gráficos Dividendos
# =========================================================
def _plot_dividend_evolution(ticker: str, price_daily: pd.DataFrame, dividends: pd.Series) -> None:
    if not isinstance(dividends, pd.Series):
        st.warning("No se pudieron cargar los datos de dividendos.")
        return

    # Always use annual view
    annual = _annual_dividends_last_years(dividends, YEARS)

    if annual.empty:
        st.warning("No hay dividendos suficientes para graficar la evolución (últimos 5 años).")
        return

    cagr = _cagr_from_annual(annual)
    if cagr is None:
        title = f"Evolución del dividendo anual — {ticker} (últimos {YEARS} años)"
    else:
        title = f"Evolución del dividendo anual — {ticker} | CAGR: {cagr:.2f}% (últimos {YEARS} años)"

    st.markdown(f"**{title}**")
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=annual.index.astype(str),
            y=annual.values,
            name="Dividendo anual",
            marker_color="#ff6d01",
            text=[f"${v:.2f}" for v in annual.values],
            textposition="outside",
        )
    )
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="Dividendo anual ($)",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="#141f41",
        plot_bgcolor="#141f41",
        font=dict(color="#ffffff"),
    )
    fig.update_yaxes(showgrid=False, zeroline=False)
    fig.update_xaxes(showgrid=False, zeroline=False)
    st.plotly_chart(fig, use_container_width=True, key=f"div_evo_{ticker}")

    with st.expander("Ver tabla (últimos 5 años)"):
        st.dataframe(pd.DataFrame({"Periodo": annual.index.astype(str), "Dividendo": annual.values}).set_index("Periodo"), use_container_width=True)


def _pick_cashflow_cols(df: pd.DataFrame) -> Tuple[Optional[str], Optional[str]]:
    if df is None or df.empty:
        return None, None

    cols = set(df.columns)
    fcf_candidates = ["Free Cash Flow", "FreeCashFlow", "freeCashFlow"]
    div_candidates = [
        "Cash Dividends Paid",
        "CashDividendsPaid",
        "cashDividendsPaid",
        "Dividends Paid",
        "DividendsPaid",
    ]

    fcf_col = next((c for c in fcf_candidates if c in cols), None)
    div_col = next((c for c in div_candidates if c in cols), None)

    if fcf_col is None:
        ocf_candidates = ["Total Cash From Operating Activities", "Operating Cash Flow", "OperatingCashFlow"]
        capex_candidates = ["Capital Expenditures", "CapitalExpenditures", "capex"]
        ocf = next((c for c in ocf_candidates if c in cols), None)
        capex = next((c for c in capex_candidates if c in cols), None)
        if ocf and capex:
            fcf_col = "__FCF_DERIVED__"
    return fcf_col, div_col


def _plot_dividend_safety(ticker: str, cashflow: pd.DataFrame) -> None:
    if cashflow is None or cashflow.empty:
        st.warning("No hay datos de cashflow suficientes para graficar seguridad del dividendo.")
        return

    df = cashflow.transpose().copy()
    df.index = pd.to_datetime(df.index, errors="coerce")
    df = df.loc[df.index.notna()]
    df["Year"] = df.index.year
    df = df.set_index("Year")

    fcf_col, div_col = _pick_cashflow_cols(df)
    if div_col is None:
        st.warning("No se encontró la columna de dividendos pagados en cashflow.")
        return

    df = df.sort_index().tail(YEARS)

    if fcf_col == "__FCF_DERIVED__":
        ocf_candidates = ["Total Cash From Operating Activities", "Operating Cash Flow", "OperatingCashFlow"]
        capex_candidates = ["Capital Expenditures", "CapitalExpenditures", "capex"]
        ocf = next((c for c in ocf_candidates if c in df.columns), None)
        capex = next((c for c in capex_candidates if c in df.columns), None)
        if not ocf or not capex:
            st.warning("No se pudo derivar FCF (faltan OCF o CapEx).")
            return
        fcf = pd.to_numeric(df[ocf], errors="coerce") - pd.to_numeric(df[capex], errors="coerce")
    else:
        if fcf_col is None or fcf_col not in df.columns:
            st.warning("No se encontró FCF en cashflow (ni se pudo derivar).")
            return
        fcf = pd.to_numeric(df[fcf_col], errors="coerce")

    div_paid = pd.to_numeric(df[div_col], errors="coerce").abs()
    out = pd.DataFrame({"FCF": fcf, "Dividendos pagados": div_paid}).dropna()
    if out.empty:
        st.warning("No hay filas suficientes para graficar seguridad del dividendo.")
        return

    out["FCF Payout (%)"] = (out["Dividendos pagados"] / out["FCF"]) * 100

    st.markdown(f"**Seguridad del dividendo — {ticker} (últimos {YEARS} años disponibles)**")
    fig = go.Figure()
    fig.add_trace(go.Bar(x=out.index.astype(str), y=out["FCF"], name="FCF", marker_color="#ff6d01", text=out["FCF"].round(0), textposition="outside"))
    fig.add_trace(
        go.Bar(
            x=out.index.astype(str),
            y=out["Dividendos pagados"],
            name="Dividendos pagados",
            marker_color="#ff00ff",
            text=out["Dividendos pagados"].round(0),
            textposition="outside",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=out.index.astype(str),
            y=out["FCF Payout (%)"],
            name="FCF Payout (%)",
            mode="lines+markers+text",
            yaxis="y2",
            line=dict(color="#01c2ef"),
            text=[f"{v:.0f}%" if pd.notna(v) else "" for v in out["FCF Payout (%)"]],
            textposition="top center",
        )
    )
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="USD",
        yaxis2=dict(title="FCF Payout (%)", overlaying="y", side="right"),
        barmode="group",
        height=520,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="#141f41",
        plot_bgcolor="#141f41",
        font=dict(color="#ffffff"),
    )
    # quitar líneas horizontales
    fig.update_yaxes(showgrid=False, zeroline=False)
    fig.update_xaxes(showgrid=False, zeroline=False)
    st.plotly_chart(fig, use_container_width=True, key=f"div_safe_{ticker}")

    with st.expander("Ver tabla (últimos 5 años)"):
        st.dataframe(out, use_container_width=True)


def _plot_geraldine_weiss(ticker: str, price_daily: pd.DataFrame, dividends: pd.Series, annual_div: Optional[float] = None) -> None:
    """Plot Geraldine Weiss chart with dividend bands and KPIs.

    Args:
        ticker: Stock ticker symbol
        price_daily: Daily price data
        dividends: Dividend series data
        annual_div: Optional cached annual dividend value from KPIs to avoid redundant API calls
    """
    if price_daily is None or price_daily.empty:
        st.warning("No hay precio diario suficiente para Geraldine Weiss.")
        return

    annual = _annual_dividends_last_years(dividends, YEARS)
    if annual.empty:
        st.warning("No hay dividendos suficientes para Geraldine Weiss (últimos 5 años).")
        return

    cagr = _cagr_from_annual(annual)

    monthly = price_daily.resample("M").last().copy()
    monthly["Year"] = monthly.index.year

    current_year = datetime.now().year
    last_year = int(annual.index.max())
    # Use cached annual_div if provided, otherwise calculate from dividends
    last_div = annual_div if annual_div is not None else float(annual.loc[last_year])

    def _adj_div(year: int) -> Optional[float]:
        if year in annual.index:
            return float(annual.loc[year])
        if year == current_year and cagr is not None and (year - 1) in annual.index:
            return float(annual.loc[year - 1]) * (1 + cagr / 100.0)
        return None

    monthly["DivAnual"] = monthly["Year"].apply(lambda y: _adj_div(int(y)))
    monthly = monthly.dropna(subset=["DivAnual", "Close"])
    if monthly.empty:
        st.warning("No hay datos suficientes para calcular yields GW en el rango.")
        return

    monthly["Yield"] = monthly["DivAnual"] / monthly["Close"]
    y_min = float(monthly["Yield"].min())
    y_max = float(monthly["Yield"].max())

    monthly["Sobrevalorado"] = monthly["DivAnual"] / y_min if y_min > 0 else None
    monthly["Infravalorado"] = monthly["DivAnual"] / y_max if y_max > 0 else None

    st.markdown(f"**Geraldine Weiss — {ticker} (últimos {YEARS} años)**")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=price_daily.index, y=price_daily["Close"], mode="lines", name="Precio (diario)", line=dict(color="#ff6d01")))
    fig.add_trace(go.Scatter(x=monthly.index, y=monthly["Sobrevalorado"], mode="lines", name="Banda sobrevalorado", line=dict(dash="dot", color="#ff00ff")))
    fig.add_trace(go.Scatter(x=monthly.index, y=monthly["Infravalorado"], mode="lines", name="Banda infravalorado", line=dict(dash="dot", color="#01c2ef")))

    current_price = float(price_daily["Close"].iloc[-1])
    fig.add_trace(
        go.Scatter(
            x=[price_daily.index[-1]],
            y=[current_price],
            mode="markers+text",
            name="Precio actual",
            marker=dict(color="#ffffff", size=10),
            text=[f"${current_price:.2f}"],
            textposition="top center",
        )
    )

    fig.update_layout(
        xaxis_title="Fecha",
        yaxis_title="Precio ($)",
        height=520,
        margin=dict(l=20, r=20, t=10, b=40),
        paper_bgcolor="#141f41",
        plot_bgcolor="#141f41",
        font=dict(color="#ffffff"),
    )
    # quitar líneas horizontales
    fig.update_yaxes(showgrid=False, zeroline=False)
    fig.update_xaxes(showgrid=False, zeroline=False)
    st.plotly_chart(fig, use_container_width=True, key=f"gw_{ticker}")

    # Display KPIs in a single row
    # Get projected values from the last data point in the bands
    projected_infravalorado = monthly["Infravalorado"].iloc[-1]
    projected_sobrevalorado = monthly["Sobrevalorado"].iloc[-1]
    
    cols = st.columns(6)
    cols[0].metric("Div. anual (último)", f"${last_div:,.2f}")
    cols[1].metric("CAGR div.", f"{cagr:.2f}%" if cagr is not None else "N/D")
    cols[2].metric("Yield mín.", f"{y_min:.2%}")
    cols[3].metric("Yield máx.", f"{y_max:.2%}")
    cols[4].metric("Infravalorado (teórico)", f"${projected_infravalorado:,.2f}" if pd.notna(projected_infravalorado) else "N/D")
    cols[5].metric("Sobrevalorado (teórico)", f"${projected_sobrevalorado:,.2f}" if pd.notna(projected_sobrevalorado) else "N/D")

    with st.expander("Ver tabla mensual (GW)"):
        show = monthly[["Close", "DivAnual", "Yield", "Sobrevalorado", "Infravalorado"]].copy()
        st.dataframe(show, use_container_width=True)


# =========================================================
# Financial Statements Data Loaders
# =========================================================
def _load_financial_statements(ticker: str) -> Dict[str, Any]:
    """Load balance sheet, income statement, and cash flow data with caching (3 months)"""
    # Check cache first
    cache_key = f"financial_statements_{ticker}"
    cached_data = cache_get(cache_key)
    
    if cached_data:
        # Reconstruct DataFrames from cached data with proper orientation
        return {
            "balance_sheet": pd.DataFrame.from_dict(cached_data["balance_sheet"], orient='tight') if cached_data["balance_sheet"] else pd.DataFrame(),
            "income_stmt": pd.DataFrame.from_dict(cached_data["income_stmt"], orient='tight') if cached_data["income_stmt"] else pd.DataFrame(),
            "cashflow": pd.DataFrame.from_dict(cached_data["cashflow"], orient='tight') if cached_data["cashflow"] else pd.DataFrame(),
        }
    
    ticker_obj = yf.Ticker(ticker)
    
    try:
        balance_sheet = ticker_obj.balance_sheet
        if balance_sheet is None or not isinstance(balance_sheet, pd.DataFrame):
            balance_sheet = pd.DataFrame()
    except Exception:
        balance_sheet = pd.DataFrame()
    
    try:
        income_stmt = ticker_obj.income_stmt
        if income_stmt is None or not isinstance(income_stmt, pd.DataFrame):
            income_stmt = pd.DataFrame()
    except Exception:
        income_stmt = pd.DataFrame()
    
    try:
        cashflow = ticker_obj.cashflow
        if cashflow is None or not isinstance(cashflow, pd.DataFrame):
            cashflow = pd.DataFrame()
    except Exception:
        cashflow = pd.DataFrame()
    
    # Cache the data for 3 months using 'tight' orientation to preserve index/column structure
    cache_data = {
        "balance_sheet": balance_sheet.to_dict(orient='tight') if not balance_sheet.empty else None,
        "income_stmt": income_stmt.to_dict(orient='tight') if not income_stmt.empty else None,
        "cashflow": cashflow.to_dict(orient='tight') if not cashflow.empty else None,
    }
    cache_set(cache_key, cache_data, ttl_seconds=FINANCIAL_STATEMENTS_CACHE_TTL)
    
    return {
        "balance_sheet": balance_sheet,
        "income_stmt": income_stmt,
        "cashflow": cashflow,
    }


@st.cache_data(ttl=DIVIDENDS_CACHE_TTL_SECONDS, show_spinner=False)
def _load_ticker_info(ticker: str) -> Dict[str, Any]:
    """
    Safely load ticker info with error handling for rate limits and other exceptions.
    Returns empty dict if info cannot be retrieved.
    Implements retry logic with exponential backoff for transient errors.
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            ticker_obj = yf.Ticker(ticker)
            info = ticker_obj.info
            if not isinstance(info, dict):
                return {}
            return info
        except Exception as e:
            error_type = type(e).__name__
            
            # Don't retry on rate limit errors, fail fast
            if "RateLimit" in error_type:
                st.warning(
                    "⚠️ Se ha alcanzado el límite de solicitudes diario. "
                    "Algunos datos pueden no estar disponibles. Por favor, intenta nuevamente más tarde."
                )
                return {}
            
            # For other errors, retry with exponential backoff (except on last attempt)
            if attempt < MAX_ATTEMPTS:
                sleep_time = (RETRY_BASE_DELAY ** attempt) + random.uniform(RETRY_JITTER_MIN, RETRY_JITTER_MAX)
                time.sleep(sleep_time)
            # On final attempt, silently return empty dict to allow app to continue
    
    return {}


def _prepare_financial_df(df: pd.DataFrame, years: int = YEARS) -> pd.DataFrame:
    """Transpose and prepare financial statement dataframe

    Handles two input formats:
    1. YFinance format: index=timestamps, columns=account_names (needs transpose)
    2. Chile CSV format: index=account_names, columns=year_strings (already transposed)
    """
    if df is None or df.empty:
        return pd.DataFrame()

    # Detect Chile CSV format: columns are year strings (e.g. "2019", "2020")
    is_chile_format = False
    if len(df.columns) > 0:
        try:
            year_cols = [int(str(c).strip()) for c in df.columns]
            if all(1900 <= y <= 2100 for y in year_cols):
                is_chile_format = True
        except (ValueError, TypeError):
            pass

    result = df.transpose().copy()

    if is_chile_format:
        # Chile CSV: after transpose, index contains year strings — convert to integers
        result.index = pd.to_numeric(result.index.astype(str).str.strip(), errors="coerce")
        result = result.loc[result.index.notna()]
        result.index = result.index.astype(int)
        result.index.name = "Year"
    else:
        # YFinance format: after transpose, index contains timestamps
        result.index = pd.to_datetime(result.index, errors="coerce")
        result = result.loc[result.index.notna()]
        result["Year"] = result.index.year
        result = result.set_index("Year")

    result = result.sort_index().tail(years)

    return result


# =========================================================
# Balance Section Charts
# =========================================================
def _plot_assets_evolution(ticker: str, balance_df: pd.DataFrame) -> None:
    """Chart: Total Assets vs Current Assets Evolution"""
    if balance_df.empty:
        st.warning("No hay datos de balance suficientes.")
        return
    
    # Find column names
    total_assets_col = None
    current_assets_col = None
    
    for col in balance_df.columns:
        col_lower = str(col).lower()
        if "total assets" in col_lower or "totalassets" in col_lower:
            total_assets_col = col
        if "current assets" in col_lower or "currentassets" in col_lower:
            current_assets_col = col
    
    if not total_assets_col or not current_assets_col:
        st.warning("No se encontraron las columnas de activos totales o corrientes.")
        return
    
    data = pd.DataFrame({
        "Activos Totales": pd.to_numeric(balance_df[total_assets_col], errors="coerce"),
        "Activos Corrientes": pd.to_numeric(balance_df[current_assets_col], errors="coerce")
    }).dropna()
    
    if data.empty:
        st.warning("No hay datos suficientes para graficar activos.")
        return
    
    st.markdown(f"**Evolución Activos Totales vs Activos Corrientes — {ticker}**")
    fig = go.Figure()
    fig.add_trace(go.Bar(x=data.index.astype(str), y=data["Activos Totales"], name="Activos Totales", marker_color="#ff6d01"))
    fig.add_trace(go.Bar(x=data.index.astype(str), y=data["Activos Corrientes"], name="Activos Corrientes", marker_color="#ff00ff"))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="USD",
        barmode="group",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="#141f41",
        plot_bgcolor="#141f41",
        font=dict(color="#ffffff"),
    )
    fig.update_yaxes(showgrid=False, zeroline=False)
    fig.update_xaxes(showgrid=False, zeroline=False)
    st.plotly_chart(fig, use_container_width=True, key=f"assets_{ticker}")


def _plot_liabilities_evolution(ticker: str, balance_df: pd.DataFrame) -> None:
    """Chart: Total Liabilities vs Current Liabilities Evolution"""
    if balance_df.empty:
        st.warning("No hay datos de balance suficientes.")
        return
    
    total_liab_col = None
    current_liab_col = None
    
    for col in balance_df.columns:
        col_lower = str(col).lower()
        if "total liabilities" in col_lower or "totalliabilities" in col_lower:
            total_liab_col = col
        if "current liabilities" in col_lower or "currentliabilities" in col_lower:
            current_liab_col = col
    
    if not total_liab_col or not current_liab_col:
        st.warning("No se encontraron las columnas de pasivos totales o corrientes.")
        return
    
    data = pd.DataFrame({
        "Pasivos Totales": pd.to_numeric(balance_df[total_liab_col], errors="coerce"),
        "Pasivos Corrientes": pd.to_numeric(balance_df[current_liab_col], errors="coerce")
    }).dropna()
    
    if data.empty:
        st.warning("No hay datos suficientes para graficar pasivos.")
        return
    
    st.markdown(f"**Evolución Pasivos Totales vs Pasivos Corrientes — {ticker}**")
    fig = go.Figure()
    fig.add_trace(go.Bar(x=data.index.astype(str), y=data["Pasivos Totales"], name="Pasivos Totales", marker_color="#ff6d01"))
    fig.add_trace(go.Bar(x=data.index.astype(str), y=data["Pasivos Corrientes"], name="Pasivos Corrientes", marker_color="#ff00ff"))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="USD",
        barmode="group",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="#141f41",
        plot_bgcolor="#141f41",
        font=dict(color="#ffffff"),
    )
    fig.update_yaxes(showgrid=False, zeroline=False)
    fig.update_xaxes(showgrid=False, zeroline=False)
    st.plotly_chart(fig, use_container_width=True, key=f"liabilities_{ticker}")


def _plot_debt_evolution(ticker: str, balance_df: pd.DataFrame) -> None:
    """Chart: Total Debt vs Net Debt Evolution"""
    if balance_df.empty:
        st.warning("No hay datos de balance suficientes.")
        return
    
    total_debt_col = None
    net_debt_col = None
    cash_col = None
    
    for col in balance_df.columns:
        col_lower = str(col).lower()
        if "total debt" in col_lower or "totaldebt" in col_lower:
            total_debt_col = col
        if "net debt" in col_lower or "netdebt" in col_lower:
            net_debt_col = col
        if "cash" in col_lower and "equivalents" in col_lower:
            cash_col = col
    
    if not total_debt_col:
        st.warning("No se encontró la columna de deuda total.")
        return
    
    total_debt = pd.to_numeric(balance_df[total_debt_col], errors="coerce")
    
    # Calculate net debt if not available
    if net_debt_col:
        net_debt = pd.to_numeric(balance_df[net_debt_col], errors="coerce")
    elif cash_col:
        cash = pd.to_numeric(balance_df[cash_col], errors="coerce")
        net_debt = total_debt - cash
    else:
        net_debt = total_debt
    
    data = pd.DataFrame({
        "Deuda Total": total_debt,
        "Deuda Neta": net_debt
    }).dropna()
    
    if data.empty:
        st.warning("No hay datos suficientes para graficar deuda.")
        return
    
    st.markdown(f"**Evolución Deuda Total vs Deuda Neta — {ticker}**")
    fig = go.Figure()
    fig.add_trace(go.Bar(x=data.index.astype(str), y=data["Deuda Total"], name="Deuda Total", marker_color="#ff6d01"))
    fig.add_trace(go.Bar(x=data.index.astype(str), y=data["Deuda Neta"], name="Deuda Neta", marker_color="#ff00ff"))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="USD",
        barmode="group",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="#141f41",
        plot_bgcolor="#141f41",
        font=dict(color="#ffffff"),
    )
    fig.update_yaxes(showgrid=False, zeroline=False)
    fig.update_xaxes(showgrid=False, zeroline=False)
    st.plotly_chart(fig, use_container_width=True, key=f"debt_{ticker}")


def _plot_equity_evolution(ticker: str, balance_df: pd.DataFrame) -> None:
    """Chart: Equity Evolution"""
    if balance_df.empty:
        st.warning("No hay datos de balance suficientes.")
        return
    
    equity_col = None
    
    for col in balance_df.columns:
        col_lower = str(col).lower()
        if ("stockholders equity" in col_lower or "shareholders equity" in col_lower or 
            "total equity" in col_lower or "totalequity" in col_lower):
            equity_col = col
            break
    
    if not equity_col:
        st.warning("No se encontró la columna de patrimonio.")
        return
    
    equity = pd.to_numeric(balance_df[equity_col], errors="coerce").dropna()
    
    if equity.empty:
        st.warning("No hay datos suficientes para graficar patrimonio.")
        return
    
    st.markdown(f"**Evolución del Patrimonio — {ticker}**")
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=equity.index.astype(str), 
        y=equity.values, 
        name="Patrimonio",
        marker_color="#ff6d01",
        text=[_fmt_large_number(v) for v in equity.values],
        textposition="outside"
    ))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="USD",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="#141f41",
        plot_bgcolor="#141f41",
        font=dict(color="#ffffff"),
    )
    fig.update_yaxes(showgrid=False, zeroline=False)
    fig.update_xaxes(showgrid=False, zeroline=False)
    st.plotly_chart(fig, use_container_width=True, key=f"equity_{ticker}")


# =========================================================
# Income Statement Section Charts
# =========================================================
def _plot_revenue_evolution(ticker: str, income_df: pd.DataFrame) -> None:
    """Chart: Revenue Evolution"""
    if income_df.empty:
        st.warning("No hay datos de estado de resultados suficientes.")
        return
    
    revenue_col = None
    
    for col in income_df.columns:
        col_lower = str(col).lower()
        if "total revenue" in col_lower or "totalrevenue" in col_lower:
            revenue_col = col
            break
    
    if not revenue_col:
        st.warning("No se encontró la columna de ingresos.")
        return
    
    revenue = pd.to_numeric(income_df[revenue_col], errors="coerce").dropna()
    
    if revenue.empty:
        st.warning("No hay datos suficientes para graficar ingresos.")
        return
    
    st.markdown(f"**Evolución de los Ingresos — {ticker}**")
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=revenue.index.astype(str), 
        y=revenue.values, 
        name="Ingresos",
        marker_color="#ff6d01",
        text=[_fmt_large_number(v) for v in revenue.values],
        textposition="outside"
    ))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="USD",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="#141f41",
        plot_bgcolor="#141f41",
        font=dict(color="#ffffff"),
    )
    fig.update_yaxes(showgrid=False, zeroline=False)
    fig.update_xaxes(showgrid=False, zeroline=False)
    st.plotly_chart(fig, use_container_width=True, key=f"revenue_{ticker}")


def _plot_margins_evolution(ticker: str, income_df: pd.DataFrame) -> None:
    """Chart: Margins Evolution (Gross, Operating, Net)"""
    if income_df.empty:
        st.warning("No hay datos de estado de resultados suficientes.")
        return
    
    revenue_col = None
    gross_profit_col = None
    operating_income_col = None
    net_income_col = None
    
    for col in income_df.columns:
        col_lower = str(col).lower()
        if "total revenue" in col_lower or "totalrevenue" in col_lower:
            revenue_col = col
        if "gross profit" in col_lower or "grossprofit" in col_lower:
            gross_profit_col = col
        if "operating income" in col_lower or "operatingincome" in col_lower:
            operating_income_col = col
        if "net income" in col_lower or "netincome" in col_lower:
            net_income_col = col
    
    if not revenue_col:
        st.warning("No se encontró la columna de ingresos para calcular márgenes.")
        return
    
    revenue = pd.to_numeric(income_df[revenue_col], errors="coerce")
    
    margins = pd.DataFrame()
    
    if gross_profit_col:
        gross_profit = pd.to_numeric(income_df[gross_profit_col], errors="coerce")
        margins["Margen Bruto (%)"] = (gross_profit / revenue * 100)
    
    if operating_income_col:
        operating_income = pd.to_numeric(income_df[operating_income_col], errors="coerce")
        margins["Margen Operativo (%)"] = (operating_income / revenue * 100)
    
    if net_income_col:
        net_income = pd.to_numeric(income_df[net_income_col], errors="coerce")
        margins["Margen Neto (%)"] = (net_income / revenue * 100)
    
    margins = margins.dropna(how="all")
    
    if margins.empty:
        st.warning("No hay datos suficientes para calcular márgenes.")
        return
    
    st.markdown(f"**Evolución de Márgenes — {ticker}**")
    fig = go.Figure()
    
    colors = ["#ff6d01", "#ff00ff", "#01c2ef"]
    for i, col in enumerate(margins.columns):
        fig.add_trace(go.Scatter(
            x=margins.index.astype(str), 
            y=margins[col].values, 
            mode="lines+markers",
            name=col,
            line=dict(color=colors[i % len(colors)])
        ))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="Porcentaje (%)",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="#141f41",
        plot_bgcolor="#141f41",
        font=dict(color="#ffffff"),
    )
    fig.update_yaxes(showgrid=False, zeroline=False)
    fig.update_xaxes(showgrid=False, zeroline=False)
    st.plotly_chart(fig, use_container_width=True, key=f"margins_{ticker}")


def _plot_eps_evolution(ticker: str, income_df: pd.DataFrame) -> None:
    """Chart: EPS Evolution"""
    if income_df.empty:
        st.warning("No hay datos de estado de resultados suficientes.")
        return
    
    eps_col = None
    
    for col in income_df.columns:
        col_lower = str(col).lower()
        if ("basic eps" in col_lower or "diluted eps" in col_lower or 
            "earnings per share" in col_lower):
            eps_col = col
            break
    
    if not eps_col:
        # Try to calculate EPS from net income and shares outstanding
        net_income_col = None
        shares_col = None
        
        for col in income_df.columns:
            col_lower = str(col).lower()
            if "net income" in col_lower or "netincome" in col_lower:
                net_income_col = col
            if "shares outstanding" in col_lower or "sharesoutstanding" in col_lower:
                shares_col = col
        
        if net_income_col and shares_col:
            net_income = pd.to_numeric(income_df[net_income_col], errors="coerce")
            shares = pd.to_numeric(income_df[shares_col], errors="coerce")
            eps = (net_income / shares).dropna()
        else:
            st.warning("No se encontró la columna de EPS ni se pudo calcular.")
            return
    else:
        eps = pd.to_numeric(income_df[eps_col], errors="coerce").dropna()
    
    if eps.empty:
        st.warning("No hay datos suficientes para graficar EPS.")
        return
    
    st.markdown(f"**Evolución del EPS — {ticker}**")
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=eps.index.astype(str), 
        y=eps.values, 
        name="EPS",
        marker_color="#ff6d01",
        text=[f"${v:.2f}" for v in eps.values],
        textposition="outside"
    ))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="USD",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="#141f41",
        plot_bgcolor="#141f41",
        font=dict(color="#ffffff"),
    )
    fig.update_yaxes(showgrid=False, zeroline=False)
    fig.update_xaxes(showgrid=False, zeroline=False)
    st.plotly_chart(fig, use_container_width=True, key=f"eps_{ticker}")


def _plot_shares_outstanding(ticker: str, income_df: pd.DataFrame) -> None:
    """Chart: Shares Outstanding Evolution"""
    if income_df.empty:
        st.warning("No hay datos de estado de resultados suficientes.")
        return
    
    shares_col = None
    
    for col in income_df.columns:
        col_lower = str(col).lower()
        if "shares outstanding" in col_lower or "sharesoutstanding" in col_lower or "diluted average shares" in col_lower:
            shares_col = col
            break
    
    if not shares_col:
        st.warning("No se encontró la columna de acciones en circulación.")
        return
    
    shares = pd.to_numeric(income_df[shares_col], errors="coerce").dropna()
    
    if shares.empty:
        st.warning("No hay datos suficientes para graficar acciones en circulación.")
        return
    
    st.markdown(f"**Evolución de Acciones en Circulación — {ticker}**")
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=shares.index.astype(str), 
        y=shares.values, 
        name="Acciones",
        marker_color="#ff6d01",
        text=[f"{v/1e9:.2f}B" if abs(v) >= 1e9 else f"{v/1e6:.2f}M" for v in shares.values],
        textposition="outside"
    ))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="Número de Acciones",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="#141f41",
        plot_bgcolor="#141f41",
        font=dict(color="#ffffff"),
    )
    fig.update_yaxes(showgrid=False, zeroline=False)
    fig.update_xaxes(showgrid=False, zeroline=False)
    st.plotly_chart(fig, use_container_width=True, key=f"shares_{ticker}")


# =========================================================
# Cash Flow Section Charts  
# =========================================================
def _plot_cashflow_vs_capex(ticker: str, cashflow_df: pd.DataFrame) -> None:
    """Chart: Operating Cash Flow vs CapEx"""
    if cashflow_df.empty:
        st.warning("No hay datos de flujo de efectivo suficientes.")
        return
    
    ocf_col = None
    capex_col = None
    
    for col in cashflow_df.columns:
        col_lower = str(col).lower()
        if "operating cash flow" in col_lower or "total cash from operating" in col_lower:
            ocf_col = col
        if "capital expenditure" in col_lower or "capitalexpenditure" in col_lower:
            capex_col = col
    
    if not ocf_col or not capex_col:
        st.warning("No se encontraron las columnas de flujo de caja operativo o CapEx.")
        return
    
    data = pd.DataFrame({
        "Flujo de Caja Operativo": pd.to_numeric(cashflow_df[ocf_col], errors="coerce"),
        "CapEx": pd.to_numeric(cashflow_df[capex_col], errors="coerce").abs()
    }).dropna()
    
    if data.empty:
        st.warning("No hay datos suficientes para graficar flujo de caja vs CapEx.")
        return
    
    # Calculate FCF (Free Cash Flow) = OCF - CapEx
    data["FCF"] = data["Flujo de Caja Operativo"] - data["CapEx"]
    
    st.markdown(f"**Flujo de Caja Operativo vs CapEx — {ticker}**")
    fig = go.Figure()
    fig.add_trace(go.Bar(x=data.index.astype(str), y=data["Flujo de Caja Operativo"], name="Flujo de Caja Operativo", marker_color="#ff6d01"))
    fig.add_trace(go.Bar(x=data.index.astype(str), y=data["CapEx"], name="CapEx", marker_color="#ff00ff"))
    fig.add_trace(go.Scatter(x=data.index.astype(str), y=data["FCF"], name="FCF", mode="lines+markers", line=dict(color="#01c2ef", width=2), marker=dict(size=8)))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="USD",
        barmode="group",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="#141f41",
        plot_bgcolor="#141f41",
        font=dict(color="#ffffff"),
    )
    fig.update_yaxes(showgrid=False, zeroline=False)
    fig.update_xaxes(showgrid=False, zeroline=False)
    st.plotly_chart(fig, use_container_width=True, key=f"cf_capex_{ticker}")


def _plot_debt_issuance(ticker: str, cashflow_df: pd.DataFrame) -> None:
    """Chart: Debt Issuance"""
    if cashflow_df.empty:
        st.warning("No hay datos de flujo de efectivo suficientes.")
        return
    
    debt_issued_col = None
    
    for col in cashflow_df.columns:
        col_lower = str(col).lower()
        if "issuance of debt" in col_lower or "long term debt issued" in col_lower:
            debt_issued_col = col
            break
    
    if not debt_issued_col:
        st.warning("No se encontró la columna de emisión de deuda.")
        return
    
    debt_issued = pd.to_numeric(cashflow_df[debt_issued_col], errors="coerce").dropna()
    
    if debt_issued.empty:
        st.warning("No hay datos suficientes para graficar emisión de deuda.")
        return
    
    st.markdown(f"**Emisión de Deuda — {ticker}**")
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=debt_issued.index.astype(str), 
        y=debt_issued.values, 
        name="Emisión de Deuda",
        marker_color=["#01c2ef" if v > 0 else "#ff00ff" for v in debt_issued.values]
    ))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="USD",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="#141f41",
        plot_bgcolor="#141f41",
        font=dict(color="#ffffff"),
    )
    fig.update_yaxes(showgrid=False, zeroline=False)
    fig.update_xaxes(showgrid=False, zeroline=False)
    st.plotly_chart(fig, use_container_width=True, key=f"debt_issuance_{ticker}")


def _plot_debt_repayment(ticker: str, cashflow_df: pd.DataFrame) -> None:
    """Chart: Debt Repayment"""
    if cashflow_df.empty:
        st.warning("No hay datos de flujo de efectivo suficientes.")
        return
    
    debt_repay_col = None
    
    for col in cashflow_df.columns:
        col_lower = str(col).lower()
        if "repayment of debt" in col_lower or "long term debt repayment" in col_lower or "debt repayment" in col_lower:
            debt_repay_col = col
            break
    
    if not debt_repay_col:
        st.warning("No se encontró la columna de pago de deuda.")
        return
    
    debt_repay = pd.to_numeric(cashflow_df[debt_repay_col], errors="coerce").abs().dropna()
    
    if debt_repay.empty:
        st.warning("No hay datos suficientes para graficar pago de deuda.")
        return
    
    st.markdown(f"**Pago de Deuda — {ticker}**")
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=debt_repay.index.astype(str), 
        y=debt_repay.values, 
        name="Pago de Deuda",
        marker_color="#ff6d01"
    ))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="USD",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="#141f41",
        plot_bgcolor="#141f41",
        font=dict(color="#ffffff"),
    )
    fig.update_yaxes(showgrid=False, zeroline=False)
    fig.update_xaxes(showgrid=False, zeroline=False)
    st.plotly_chart(fig, use_container_width=True, key=f"debt_repay_{ticker}")


def _plot_share_buybacks(ticker: str, cashflow_df: pd.DataFrame) -> None:
    """Chart: Share Buybacks"""
    if cashflow_df.empty:
        st.warning("No hay datos de flujo de efectivo suficientes.")
        return
    
    buyback_col = None
    
    for col in cashflow_df.columns:
        col_lower = str(col).lower()
        if ("repurchase" in col_lower and "stock" in col_lower) or "buyback" in col_lower or "treasury stock" in col_lower:
            buyback_col = col
            break
    
    if not buyback_col:
        st.warning("No se encontró la columna de recompra de acciones.")
        return
    
    buybacks = pd.to_numeric(cashflow_df[buyback_col], errors="coerce").abs().dropna()
    
    if buybacks.empty:
        st.warning("No hay datos suficientes para graficar recompra de acciones.")
        return
    
    st.markdown(f"**Recompra de Acciones — {ticker}**")
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=buybacks.index.astype(str), 
        y=buybacks.values, 
        name="Recompra de Acciones",
        marker_color="#ff6d01"
    ))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="USD",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="#141f41",
        plot_bgcolor="#141f41",
        font=dict(color="#ffffff"),
    )
    fig.update_yaxes(showgrid=False, zeroline=False)
    fig.update_xaxes(showgrid=False, zeroline=False)
    st.plotly_chart(fig, use_container_width=True, key=f"buybacks_{ticker}")


# =========================================================
# Valoración por múltiplos Section
# =========================================================
def _plot_debt_fcf_evolution(ticker: str, balance_df: pd.DataFrame, cashflow_df: pd.DataFrame) -> None:
    """Plot debt evolution with FCF and Net Debt/FCF ratio"""
    import numpy as np
    
    st.markdown("### Evolución de la Deuda")
    
    try:
        # Get total debt
        total_debt_col = None
        for col in balance_df.columns:
            if "total debt" in str(col).lower():
                total_debt_col = col
                break
        
        if total_debt_col is None:
            # Try Long Term Debt as alternative
            for col in balance_df.columns:
                if "long term debt" in str(col).lower():
                    total_debt_col = col
                    break
        
        total_debt = pd.to_numeric(balance_df[total_debt_col], errors="coerce") if total_debt_col else None
        
        # Get cash
        cash_col = None
        for col in balance_df.columns:
            if "cash and cash equivalents" in str(col).lower():
                cash_col = col
                break
        
        if cash_col is None:
            # Try just Cash as alternative
            for col in balance_df.columns:
                if str(col).lower() == "cash":
                    cash_col = col
                    break
        
        cash = pd.to_numeric(balance_df[cash_col], errors="coerce") if cash_col else None
        
        # Get FCF from cashflow
        fcf_col = None
        for col in cashflow_df.columns:
            if "free cash flow" in str(col).lower():
                fcf_col = col
                break
        
        fcf = pd.to_numeric(cashflow_df[fcf_col], errors="coerce") if fcf_col else None
        
        # Create dataframe
        df_deuda = pd.DataFrame()
        if fcf is not None:
            df_deuda["FCF"] = fcf
        if total_debt is not None and cash is not None:
            df_deuda["Deuda Neta"] = total_debt - cash
        
        df_deuda = df_deuda.dropna(how="all")
        
        if not df_deuda.empty and "FCF" in df_deuda.columns and "Deuda Neta" in df_deuda.columns:
            df_deuda["Deuda Neta/FCF"] = df_deuda["Deuda Neta"] / df_deuda["FCF"]
            df_deuda = df_deuda.replace([np.inf, -np.inf], np.nan).dropna()
        
        if df_deuda.empty:
            st.warning("No hay datos suficientes para generar el gráfico de deuda.")
            return
        
        # Colors
        color_primary = "#ff6d01"    # Orange
        color_secondary = "#ff00ff"  # Magenta
        color_tertiary = "#01c2ef"   # Cyan
        
        fig_deuda = go.Figure()
        if "FCF" in df_deuda.columns:
            fig_deuda.add_trace(
                go.Bar(
                    x=df_deuda.index.astype(str),
                    y=df_deuda["FCF"],
                    name="FCF",
                    marker_color=color_primary,
                    text=df_deuda["FCF"].apply(lambda x: f"{x/1e6:.0f}M" if abs(x) >= 1e6 else f"{x:.0f}"),
                    textposition="outside",
                )
            )
        if "Deuda Neta" in df_deuda.columns:
            fig_deuda.add_trace(
                go.Bar(
                    x=df_deuda.index.astype(str),
                    y=df_deuda["Deuda Neta"],
                    name="Deuda Neta",
                    marker_color=color_secondary,
                    text=df_deuda["Deuda Neta"].apply(lambda x: f"{x/1e6:.0f}M" if abs(x) >= 1e6 else f"{x:.0f}"),
                    textposition="outside",
                )
            )
        if "Deuda Neta/FCF" in df_deuda.columns:
            fig_deuda.add_trace(
                go.Scatter(
                    x=df_deuda.index.astype(str),
                    y=df_deuda["Deuda Neta/FCF"],
                    name="Deuda Neta/FCF",
                    mode="lines+markers+text",
                    yaxis="y2",
                    line=dict(color=color_tertiary),
                    text=[f"{v:.2f}" for v in df_deuda["Deuda Neta/FCF"]],
                    textposition="top right",
                )
            )
        
        fig_deuda.update_layout(
            title="Evolución de Deuda, FCF y Deuda Neta/FCF",
            xaxis_title="Año",
            yaxis_title="Millones USD",
            yaxis2=dict(title="Deuda Neta/FCF", overlaying="y", side="right"),
            barmode="group",
            height=500,
            margin=dict(l=30, r=30, t=60, b=30),
            paper_bgcolor="#141f41",
            plot_bgcolor="#141f41",
            font=dict(color="#ffffff"),
        )
        fig_deuda.update_yaxes(showgrid=False, zeroline=False)
        fig_deuda.update_xaxes(showgrid=False, zeroline=False)
        st.plotly_chart(fig_deuda, use_container_width=True, key=f"plotly_chart_deuda_{ticker}")
    except Exception as e:
        st.warning(f"No se pudo generar el gráfico de deuda: {e}")


def _plot_per_evolution(ticker: str, income_df: pd.DataFrame, info: Dict[str, Any]) -> None:
    """Plot P/E ratio evolution with EPS and Price"""
    import numpy as np
    
    st.markdown("### Histórico del PER, EPS y Precio")
    
    try:
        # Get current P/E ratio
        pe_ratio = info.get("trailingPE")
        if pe_ratio and isinstance(pe_ratio, (int, float)):
            st.markdown(f"**📌 El PER actual es de {pe_ratio:.2f}x**")
        
        # Get EPS
        eps_col = None
        for col in income_df.columns:
            if "basic eps" in str(col).lower():
                eps_col = col
                break
        
        if not eps_col:
            st.warning("No se encontró 'Basic EPS'.")
            return
        
        eps_series = pd.to_numeric(income_df[eps_col], errors="coerce")
        
        # Get price data
        t = yf.Ticker(ticker)
        price_data = t.history(period="max")
        if price_data.empty:
            st.warning("No hay datos de precio disponibles.")
            return
        
        price_yearly = price_data.resample("Y").last()["Close"]
        price_yearly.index = price_yearly.index.year
        
        # Create dataframe
        df_per = pd.DataFrame({"EPS": eps_series, "Precio": price_yearly}).dropna()
        if df_per.empty:
            st.warning("No hay datos suficientes para calcular el PER histórico.")
            return
        
        df_per["PER"] = df_per["Precio"] / df_per["EPS"]
        df_per = df_per.replace([np.inf, -np.inf], np.nan).dropna()
        
        if df_per.empty:
            st.warning("No hay datos suficientes para graficar el PER.")
            return
        
        # Colors
        color_primary = "#ff6d01"    # Orange
        color_secondary = "#ff00ff"  # Magenta
        color_tertiary = "#01c2ef"   # Cyan
        
        fig_combined = go.Figure()
        fig_combined.add_trace(
            go.Bar(
                x=df_per.index.astype(str),
                y=df_per["EPS"],
                name="EPS",
                marker_color=color_primary,
                text=df_per["EPS"].round(2),
                textposition="outside",
            )
        )
        fig_combined.add_trace(
            go.Bar(
                x=df_per.index.astype(str),
                y=df_per["Precio"],
                name="Precio",
                marker_color=color_secondary,
                text=df_per["Precio"].round(2),
                textposition="outside",
            )
        )
        fig_combined.add_trace(
            go.Scatter(
                x=df_per.index.astype(str),
                y=df_per["PER"],
                name="PER",
                mode="lines+markers+text",
                yaxis="y2",
                line=dict(color=color_tertiary),
                text=[f"{v:.2f}" for v in df_per["PER"]],
                textposition="top right",
            )
        )
        
        # Add horizontal line for current P/E ratio (if available from yfinance info)
        if pe_ratio and isinstance(pe_ratio, (int, float)):
            fig_combined.add_hline(
                y=pe_ratio,
                line_dash="dash",
                line_color="#ffff00",  # Yellow color for visibility
                annotation_text=f"PER Actual: {pe_ratio:.2f}",
                annotation_position="right",
                yref="y2"  # IMPORTANTE: referencia al eje Y2 porque PER está en el eje secundario
            )
        
        fig_combined.update_layout(
            title="Histórico del EPS, Precio y PER",
            xaxis_title="Año",
            yaxis=dict(title="EPS / Precio"),
            yaxis2=dict(title="PER", overlaying="y", side="right"),
            barmode="group",
            height=450,
            margin=dict(l=30, r=30, t=60, b=30),
            paper_bgcolor="#141f41",
            plot_bgcolor="#141f41",
            font=dict(color="#ffffff"),
        )
        fig_combined.update_yaxes(showgrid=False, zeroline=False)
        fig_combined.update_xaxes(showgrid=False, zeroline=False)
        st.plotly_chart(fig_combined, use_container_width=True, key=f"plotly_chart_per_{ticker}")
    except Exception as e:
        st.warning(f"No se pudo generar el gráfico PER: {e}")


def _plot_ev_ebitda_evolution(ticker: str, income_df: pd.DataFrame, balance_df: pd.DataFrame, info: Dict[str, Any]) -> None:
    """Plot EV/EBITDA evolution"""
    import numpy as np
    
    st.markdown("### Evolución de EV, EBITDA y EV/EBITDA")
    
    try:
        # Get EBITDA
        ebitda_col = None
        for col in income_df.columns:
            if "ebitda" in str(col).lower():
                ebitda_col = col
                break
        
        ebitda = pd.to_numeric(income_df[ebitda_col], errors="coerce") if ebitda_col else None
        
        if ebitda is None:
            st.warning("No se encontró EBITDA en los datos financieros.")
            return
        
        # Get total debt
        total_debt_col = None
        for col in balance_df.columns:
            if "total debt" in str(col).lower():
                total_debt_col = col
                break
        
        if total_debt_col is None:
            for col in balance_df.columns:
                if "long term debt" in str(col).lower():
                    total_debt_col = col
                    break
        
        total_debt = pd.to_numeric(balance_df[total_debt_col], errors="coerce") if total_debt_col else None
        
        # Get cash
        cash_col = None
        for col in balance_df.columns:
            if "cash and cash equivalents" in str(col).lower():
                cash_col = col
                break
        
        if cash_col is None:
            for col in balance_df.columns:
                if str(col).lower() == "cash":
                    cash_col = col
                    break
        
        cash = pd.to_numeric(balance_df[cash_col], errors="coerce") if cash_col else None
        
        # Calculate net debt
        net_debt = None
        if total_debt is not None and cash is not None:
            net_debt = total_debt - cash
        
        # Get market cap
        market_cap = info.get("marketCap")
        
        # Calculate EV and EV/EBITDA
        # Note: We need historical market cap for accurate EV calculation
        # Try to get historical market cap by using shares outstanding and historical prices
        ev = None
        ev_ebitda = None
        used_historical_mcap = False  # Track if we use historical or current market cap
        
        # Get shares outstanding from balance sheet or income statement
        shares_col = None
        for col in balance_df.columns:
            if "ordinary shares" in str(col).lower() or "shares outstanding" in str(col).lower():
                shares_col = col
                break
        
        if shares_col is None and not income_df.empty:
            for col in income_df.columns:
                if "ordinary shares" in str(col).lower() or "shares outstanding" in str(col).lower():
                    shares_col = col
                    break
        
        # Try to calculate historical market cap
        historical_market_cap = None
        if shares_col is not None:
            shares_data = pd.to_numeric(balance_df[shares_col] if shares_col in balance_df.columns 
                                       else income_df[shares_col], errors="coerce")
            
            # Get historical year-end prices
            t = yf.Ticker(ticker)
            price_data = t.history(period="max")
            if not price_data.empty:
                price_yearly = price_data.resample("Y").last()["Close"]
                price_yearly.index = price_yearly.index.year
                
                # Calculate historical market cap = shares * price
                # Align indices
                common_years = shares_data.index.intersection(price_yearly.index)
                if len(common_years) > 0:
                    historical_market_cap = shares_data[common_years] * price_yearly[common_years]
        
        if historical_market_cap is not None and net_debt is not None:
            # Use historical market cap where available
            ev = historical_market_cap + net_debt
            ev_ebitda = ev / ebitda
            used_historical_mcap = True
        elif market_cap is not None and net_debt is not None:
            # Fallback: Use current market cap for all years (limitation noted)
            # Note: This is a simplification - ideally we'd use historical market cap
            ev = pd.Series([market_cap + net_debt.iloc[i] if i < len(net_debt) else None 
                          for i in range(len(ebitda))], 
                          index=ebitda.index)
            ev_ebitda = ev / ebitda
            used_historical_mcap = False
        
        df_ev = pd.DataFrame({"EBITDA": ebitda, "EV": ev, "EV/EBITDA": ev_ebitda}).dropna(how="all")
        
        if df_ev.empty:
            st.warning("No hay datos suficientes para generar el gráfico EV/EBITDA.")
            return
        
        # Show current EV/EBITDA
        current_ev_ebitda = (
            df_ev["EV/EBITDA"].dropna().iloc[-1]
            if "EV/EBITDA" in df_ev.columns and not df_ev["EV/EBITDA"].dropna().empty
            else None
        )
        if current_ev_ebitda is not None:
            st.markdown(f"**📌 EV/EBITDA actual: {current_ev_ebitda:.2f}**")
        else:
            st.markdown("**📌 EV/EBITDA actual no disponible**")
        
        # Show info message if using current market cap fallback
        if not used_historical_mcap:
            st.info("ℹ️ Usando capitalización de mercado actual para todos los años (EV histórico aproximado)")
        
        # Colors
        color_primary = "#ff6d01"    # Orange
        color_secondary = "#ff00ff"  # Magenta
        color_tertiary = "#01c2ef"   # Cyan
        
        fig_ev = go.Figure()
        if "EBITDA" in df_ev.columns:
            fig_ev.add_trace(
                go.Bar(
                    x=df_ev.index.astype(str),
                    y=df_ev["EBITDA"],
                    name="EBITDA",
                    marker_color=color_primary,
                    text=df_ev["EBITDA"].apply(lambda x: f"{x/1e6:.0f}M" if abs(x) >= 1e6 else f"{x:.0f}"),
                    textposition="outside",
                )
            )
        if "EV" in df_ev.columns:
            fig_ev.add_trace(
                go.Bar(
                    x=df_ev.index.astype(str),
                    y=df_ev["EV"],
                    name="EV",
                    marker_color=color_secondary,
                    text=df_ev["EV"].apply(lambda x: f"{x/1e9:.1f}B" if abs(x) >= 1e9 else f"{x/1e6:.0f}M"),
                    textposition="outside",
                )
            )
        if "EV/EBITDA" in df_ev.columns:
            fig_ev.add_trace(
                go.Scatter(
                    x=df_ev.index.astype(str),
                    y=df_ev["EV/EBITDA"],
                    name="EV/EBITDA",
                    mode="lines+markers+text",
                    yaxis="y2",
                    line=dict(color=color_tertiary),
                    text=[f"{v:.2f}" for v in df_ev["EV/EBITDA"]],
                    textposition="top right",
                )
            )
        fig_ev.update_layout(
            title="Evolución de EV, EBITDA y EV/EBITDA",
            xaxis_title="Año",
            yaxis_title="Valor (USD)",
            yaxis2=dict(title="EV/EBITDA", overlaying="y", side="right"),
            barmode="group",
            height=500,
            margin=dict(l=30, r=30, t=60, b=30),
            paper_bgcolor="#141f41",
            plot_bgcolor="#141f41",
            font=dict(color="#ffffff"),
        )
        fig_ev.update_yaxes(showgrid=False, zeroline=False)
        fig_ev.update_xaxes(showgrid=False, zeroline=False)
        st.plotly_chart(fig_ev, use_container_width=True, key=f"plotly_chart_ev_{ticker}")
    except Exception as e:
        st.warning(f"No se pudo generar el gráfico EV/EBITDA: {e}")


def _plot_fc_usage(ticker: str, cashflow_df: pd.DataFrame) -> None:
    """Plot Cash Flow Usage: CapEx, Dividends, Share Buybacks, and Debt Repayment"""
    
    st.markdown("### Uso del Flujo de Caja")
    
    try:
        # Find CapEx column
        capex_col = None
        capex_candidates = ["Capital Expenditures", "CapitalExpenditures", "capex"]
        for col in cashflow_df.columns:
            if col in capex_candidates or "capital expenditure" in str(col).lower():
                capex_col = col
                break
        
        # Find Dividends column
        div_col = None
        div_candidates = [
            "Cash Dividends Paid",
            "CashDividendsPaid",
            "cashDividendsPaid",
            "Dividends Paid",
            "DividendsPaid",
        ]
        for col in cashflow_df.columns:
            if col in div_candidates:
                div_col = col
                break
        
        # Find Share Buybacks column
        buyback_col = None
        for col in cashflow_df.columns:
            col_lower = str(col).lower()
            if ("repurchase" in col_lower and "stock" in col_lower) or "buyback" in col_lower or "treasury stock" in col_lower:
                buyback_col = col
                break
        
        # Find Debt Repayment column
        debt_repay_col = None
        for col in cashflow_df.columns:
            col_lower = str(col).lower()
            if "repayment of debt" in col_lower or "long term debt repayment" in col_lower or "debt repayment" in col_lower:
                debt_repay_col = col
                break
        
        # Extract data
        capex = pd.to_numeric(cashflow_df[capex_col], errors="coerce").abs() if capex_col else None
        dividends = pd.to_numeric(cashflow_df[div_col], errors="coerce").abs() if div_col else None
        buybacks = pd.to_numeric(cashflow_df[buyback_col], errors="coerce").abs() if buyback_col else None
        debt_repay = pd.to_numeric(cashflow_df[debt_repay_col], errors="coerce").abs() if debt_repay_col else None
        
        # Build dataframe with available data
        df_fc_usage = pd.DataFrame()
        if capex is not None:
            df_fc_usage["CapEx"] = capex
        if dividends is not None:
            df_fc_usage["Dividendos"] = dividends
        if buybacks is not None:
            df_fc_usage["Recompra de Acciones"] = buybacks
        if debt_repay is not None:
            df_fc_usage["Pago de Deuda"] = debt_repay
        
        df_fc_usage = df_fc_usage.dropna(how="all")
        
        if df_fc_usage.empty:
            st.warning("No hay datos suficientes para generar el gráfico de uso del flujo de caja.")
            return
        
        # Colors matching the style
        colors = {
            "CapEx": "#ff6d01",         # Orange
            "Dividendos": "#ff00ff",    # Magenta
            "Recompra de Acciones": "#01c2ef",  # Cyan
            "Pago de Deuda": "#00ff00"  # Green
        }
        
        fig_fc = go.Figure()
        
        # Add bars for each category
        for col in df_fc_usage.columns:
            y_values = df_fc_usage[col] / 1e6  # Convert to millions
            fig_fc.add_trace(
                go.Bar(
                    x=df_fc_usage.index.astype(str),
                    y=y_values,
                    name=col,
                    marker_color=colors.get(col, "#ffffff"),
                    text=y_values.apply(lambda x: f"{x:.1f}M" if pd.notna(x) else ""),
                    textposition="outside",
                )
            )
        
        fig_fc.update_layout(
            title="Uso del Flujo de Caja",
            xaxis_title="Año",
            yaxis_title="Millones USD",
            barmode="group",
            height=500,
            margin=dict(l=30, r=30, t=60, b=30),
            paper_bgcolor="#141f41",
            plot_bgcolor="#141f41",
            font=dict(color="#ffffff"),
        )
        fig_fc.update_yaxes(showgrid=False, zeroline=False)
        fig_fc.update_xaxes(showgrid=False, zeroline=False)
        st.plotly_chart(fig_fc, use_container_width=True, key=f"plotly_chart_fc_usage_{ticker}")
    except Exception as e:
        st.warning(f"No se pudo generar el gráfico de uso del flujo de caja: {e}")


# Constants for Gurufocus valuation image suffixes
GURUFOCUS_D_SUFFIX = " - D.png"
GURUFOCUS_V_SUFFIX = " - V.png"


def _render_gurufocus_valuation_charts(ticker: str) -> None:
    """
    Display custom Gurufocus valuation charts for ANY ticker with images.
    Shows D (Desempeño) and V (Valoración) charts.
    Charts are loaded from: src/assets/{TICKER} - D.png and {TICKER} - V.png
    """
    from pathlib import Path
    
    # Path to assets folder
    assets_path = Path(__file__).parent.parent / "assets"
    
    # Look for D and V images
    d_path = assets_path / f"{ticker}{GURUFOCUS_D_SUFFIX}"
    v_path = assets_path / f"{ticker}{GURUFOCUS_V_SUFFIX}"
    
    # Collect available images
    image_paths = []
    if d_path.exists():
        image_paths.append(("Desempeño", d_path))
    if v_path.exists():
        image_paths.append(("Valoración", v_path))
    
    if not image_paths:
        # No valuation images found, fail silently
        return
    
    # Display images
    st.markdown("### Análisis de Gurufocus")
    st.caption(f"Gráficos de desempeño y valoración para {ticker}")
    
    # Display images in 2 columns (grid)
    if len(image_paths) == 1:
        # Only one image, center it
        try:
            st.image(str(image_paths[0][1]), caption=image_paths[0][0], use_container_width=True)
        except Exception:
            pass
    else:
        # Two images, side by side
        col1, col2 = st.columns(2)
        for idx, (caption, img_path) in enumerate(image_paths):
            with col1 if idx == 0 else col2:
                try:
                    st.image(str(img_path), caption=caption, use_container_width=True)
                except Exception:
                    pass


# =========================================================
# Financial Ratios Section (Análisis Razonado)
# =========================================================
def _calculate_financial_ratios(balance_df: pd.DataFrame, income_df: pd.DataFrame, 
                                 cashflow_df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Calculate comprehensive financial ratios"""
    
    ratios = pd.DataFrame()
    
    if balance_df.empty:
        return ratios
    
    def _find_column(df: pd.DataFrame, keywords: list) -> Optional[str]:
        """
        Find a column in a dataframe by matching keywords (case-insensitive).
        
        Args:
            df: DataFrame to search
            keywords: List of keyword strings to match in column names
            
        Returns:
            Column name if found, None otherwise
        """
        for col in df.columns:
            col_lower = str(col).lower()
            if any(kw in col_lower for kw in keywords):
                return col
        return None
    
    # Balance sheet columns
    current_assets_col = _find_column(balance_df, ["current assets"])
    current_assets = pd.to_numeric(balance_df[current_assets_col], errors="coerce") if current_assets_col else None
    
    current_liab_col = _find_column(balance_df, ["current liabilities"])
    current_liab = pd.to_numeric(balance_df[current_liab_col], errors="coerce") if current_liab_col else None
    
    total_assets_col = _find_column(balance_df, ["total assets"])
    total_assets = pd.to_numeric(balance_df[total_assets_col], errors="coerce") if total_assets_col else None
    
    total_liab_col = _find_column(balance_df, ["total liabilities"])
    total_liab = pd.to_numeric(balance_df[total_liab_col], errors="coerce") if total_liab_col else None
    
    equity_col = _find_column(balance_df, ["stockholders equity", "shareholders equity", "total equity"])
    equity = pd.to_numeric(balance_df[equity_col], errors="coerce") if equity_col else None
    
    total_debt_col = _find_column(balance_df, ["total debt"])
    total_debt = pd.to_numeric(balance_df[total_debt_col], errors="coerce") if total_debt_col else None
    
    inventory_col = _find_column(balance_df, ["inventory", "inventories", "inventarios", "existencias"])
    inventory = pd.to_numeric(balance_df[inventory_col], errors="coerce") if inventory_col else None
    
    receivables_col = _find_column(balance_df, ["accounts receivable", "receivables"])
    receivables = pd.to_numeric(balance_df[receivables_col], errors="coerce") if receivables_col else None
    
    payables_col = _find_column(balance_df, ["accounts payable", "payables"])
    payables = pd.to_numeric(balance_df[payables_col], errors="coerce") if payables_col else None
    
    # Income statement columns
    revenue_col = _find_column(income_df, ["total revenue"]) if not income_df.empty else None
    revenue = pd.to_numeric(income_df[revenue_col], errors="coerce") if revenue_col else None
    
    net_income_col = _find_column(income_df, ["net income"]) if not income_df.empty else None
    net_income = pd.to_numeric(income_df[net_income_col], errors="coerce") if net_income_col else None
    
    cogs_col = _find_column(income_df, ["cost of revenue", "cogs"]) if not income_df.empty else None
    cogs = pd.to_numeric(income_df[cogs_col], errors="coerce") if cogs_col else None
    
    # For ROIC calculation
    ebit_col = _find_column(income_df, ["ebit"]) if not income_df.empty else None
    ebit = pd.to_numeric(income_df[ebit_col], errors="coerce") if ebit_col else None
    
    tax_col = _find_column(income_df, ["tax provision", "income tax"]) if not income_df.empty else None
    tax = pd.to_numeric(income_df[tax_col], errors="coerce") if tax_col else None
    
    # Calculate ratios
    if current_assets is not None and current_liab is not None:
        ratios["Razón Corriente"] = current_assets / current_liab
    
    if current_assets is not None and inventory is not None and current_liab is not None:
        ratios["Razón Ácida"] = (current_assets - inventory) / current_liab
    
    if current_assets is not None and current_liab is not None:
        ratios["Capital de Trabajo"] = current_assets - current_liab
    
    if total_debt is not None and equity is not None:
        ratios["Deuda/Patrimonio"] = total_debt / equity
    
    if total_debt is not None and total_assets is not None:
        ratios["Deuda/Activos"] = total_debt / total_assets
    
    if revenue is not None and inventory is not None:
        ratios["Rotación de Inventarios"] = revenue / inventory
    
    if revenue is not None and total_assets is not None:
        ratios["Rotación de Activos"] = revenue / total_assets
    
    if receivables is not None and revenue is not None:
        ratios["Días de Cobro"] = (receivables / revenue) * 365
    
    if payables is not None and cogs is not None:
        ratios["Días de Pago"] = (payables / cogs) * 365
    
    if net_income is not None and total_assets is not None:
        ratios["ROA (%)"] = (net_income / total_assets) * 100
    
    if net_income is not None and equity is not None:
        ratios["ROE (%)"] = (net_income / equity) * 100

    # ROIC = NOPAT / Invested Capital
    # NOPAT = EBIT * (1 - Tax Rate)
    # Invested Capital = Total Assets - Current Liabilities
    if ebit is not None and total_assets is not None and current_liab is not None:
        # Calculate tax rate from financial data if available
        if net_income is not None and tax is not None:
            # EBIT - Tax = Net Income (approximately)
            # Tax rate = Tax / (EBIT)
            tax_rate = tax / ebit
            tax_rate = tax_rate.clip(0, 1)  # Keep tax rate between 0 and 1
        elif net_income is not None:
            # Approximate tax rate from net income and EBIT
            tax_rate = 1 - (net_income / ebit)
            tax_rate = tax_rate.clip(0, 1)
        else:
            # Default tax rate: 21% (U.S. federal corporate statutory tax rate)
            # Note: This is the statutory rate. Actual effective tax rates may vary
            # significantly due to deductions, credits, tax havens, and other factors.
            # For international stocks, statutory rates vary by jurisdiction (0% to 35%+).
            # When possible, the actual tax is calculated from financial statements above.
            tax_rate = 0.21
        
        nopat = ebit * (1 - tax_rate)
        invested_capital = total_assets - current_liab
        ratios["ROIC (%)"] = (nopat / invested_capital) * 100
    
    if net_income is not None and revenue is not None:
        ratios["Margen de Utilidad (%)"] = (net_income / revenue) * 100
    
    if total_assets is not None and equity is not None:
        ratios["Apalancamiento"] = total_assets / equity
    
    return ratios


def _plot_ratio_evolution(ticker: str, ratio_name: str, ratio_data: pd.Series) -> None:
    """Generic function to plot a single ratio evolution"""
    if ratio_data is None or ratio_data.empty:
        return
    
    ratio_data = ratio_data.dropna()
    if ratio_data.empty:
        return
    
    st.markdown(f"**{ratio_name} — {ticker}**")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=ratio_data.index.astype(str), 
        y=ratio_data.values, 
        mode="lines+markers",
        name=ratio_name,
        line=dict(color="#ff6d01"),
        text=[f"{v:.2f}" for v in ratio_data.values],
        textposition="top center"
    ))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title=ratio_name,
        height=400,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="#141f41",
        plot_bgcolor="#141f41",
        font=dict(color="#ffffff"),
    )
    fig.update_yaxes(showgrid=False, zeroline=False)
    fig.update_xaxes(showgrid=False, zeroline=False)
    st.plotly_chart(fig, use_container_width=True, key=f"ratio_{ratio_name}_{ticker}")


def _render_interactive_valuation_board(ticker: str, logo_url: str) -> None:
    """
    Renders a static valuation board using HTML/CSS/JavaScript.
    Users can click anywhere on the board to position the company logo.
    The board remains static (no page rerun) and logo position is saved in localStorage.
    
    Click behavior: Click anywhere on the board to place the logo at that position.
    Position is persistent across page loads using localStorage.
    """
    import base64
    from pathlib import Path
    import html
    
    # Sanitize inputs to prevent XSS attacks
    ticker_safe = html.escape(ticker)
    
    # Validate logo URL - only allow http, https, and data URIs
    logo_url_safe = ""
    if logo_url:
        if logo_url.startswith(("http://", "https://", "data:")):
            # Basic validation passed, escape for HTML
            logo_url_safe = html.escape(logo_url)
        else:
            st.warning("URL del logo no válida. Solo se permiten URLs con protocolo http, https o data.")
            return
    
    # Load the background image
    assets_path = Path(__file__).parent.parent / "assets" / "PizarraFondo.png"
    
    if not assets_path.exists():
        st.error(f"No se encontró la imagen de fondo en: {assets_path}")
        return
    
    # Convert image to base64 for embedding
    with open(assets_path, "rb") as f:
        img_bytes = f.read()
    board_base64 = base64.b64encode(img_bytes).decode()
    
    # Display header and instructions
    st.markdown(f"**Pizarra de Valoración Interactiva — {ticker_safe}**")
    st.caption("💡 Haz clic en cualquier punto de la pizarra para posicionar el logo de la empresa. La posición se guarda automáticamente.")
    
    # Create the HTML/CSS/JavaScript component
    html_code = f"""
    <style>
        #valuation-board-container {{
            position: relative;
            width: 100%;
            max-width: 1200px;
            margin: 0 auto;
            background-color: #141f41;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
        }}
        
        #valuation-board {{
            position: relative;
            width: 100%;
            cursor: crosshair;
            display: block;
        }}
        
        #company-logo {{
            position: absolute;
            width: 80px;
            height: 80px;
            object-fit: contain;
            pointer-events: none;
            display: none;
            border: 2px solid #ff6d01;
            border-radius: 8px;
            background-color: rgba(255, 255, 255, 0.9);
            padding: 4px;
            box-shadow: 0 2px 8px rgba(255, 109, 1, 0.5);
            transform: translate(-50%, -50%);
        }}
        
        #position-info {{
            margin-top: 10px;
            padding: 10px;
            background-color: rgba(255, 255, 255, 0.1);
            border-radius: 4px;
            color: #ffffff;
            font-family: monospace;
            font-size: 14px;
        }}
    </style>
    
    <div id="valuation-board-container">
        <img id="valuation-board" 
             src="data:image/png;base64,{board_base64}" 
             alt="Pizarra de Valoración">
        <img id="company-logo" 
             src="{logo_url_safe}" 
             alt="Logo de {ticker_safe}"
             onerror="console.error('Failed to load company logo'); this.style.display='none';">
    </div>
    
    <div id="position-info">
        📍 <span id="position-text">Haz clic en la pizarra para posicionar el logo</span>
    </div>
    
    <script>
        (function() {{
            const board = document.getElementById('valuation-board');
            const logo = document.getElementById('company-logo');
            const positionText = document.getElementById('position-text');
            const ticker = '{ticker_safe}';
            // Note: Using string concatenation instead of template literals.
            // In JavaScript, template literals use backticks and dollar-brace syntax.
            // To use them inside a Python f-string would require complex escaping.
            // The ticker value is HTML-escaped on the Python side for security.
            const storageKey = 'valuation_board_position_' + ticker;
            
            // Load saved position from localStorage
            function loadPosition() {{
                try {{
                    const saved = localStorage.getItem(storageKey);
                    if (saved) {{
                        const pos = JSON.parse(saved);
                        placeLogo(pos.x, pos.y);
                        return true;
                    }}
                }} catch (e) {{
                    console.error('Error loading position from localStorage (localStorage may be unavailable or disabled)');
                }}
                return false;
            }}
            
            // Save position to localStorage
            function savePosition(x, y) {{
                try {{
                    localStorage.setItem(storageKey, JSON.stringify({{ x: x, y: y }}));
                }} catch (e) {{
                    console.error('Error saving position to localStorage (localStorage may be full or unavailable)');
                }}
            }}
            
            // Place logo at specified position (percentage)
            function placeLogo(xPercent, yPercent) {{
                logo.style.left = xPercent + '%';
                logo.style.top = yPercent + '%';
                logo.style.display = 'block';
                // String concatenation for consistency
                positionText.textContent = 'Posición del logo: X=' + xPercent.toFixed(1) + '%, Y=' + yPercent.toFixed(1) + '%';
            }}
            
            // Handle click on board
            board.addEventListener('click', function(event) {{
                const rect = board.getBoundingClientRect();
                const x = ((event.clientX - rect.left) / rect.width) * 100;
                const y = ((event.clientY - rect.top) / rect.height) * 100;
                
                // Clamp to valid range
                const xClamped = Math.max(0, Math.min(100, x));
                const yClamped = Math.max(0, Math.min(100, y));
                
                placeLogo(xClamped, yClamped);
                savePosition(xClamped, yClamped);
            }});
            
            // Initialize position - called after setup
            function initializePosition() {{
                if (!loadPosition()) {{
                    // Default to center if no saved position exists
                    placeLogo(50, 50);
                }}
            }}
            
            // Initialize when logo image loads successfully
            logo.addEventListener('load', function() {{
                initializePosition();
            }});
            
            // Also initialize if logo fails to load (fallback)
            logo.addEventListener('error', function() {{
                console.warn('Logo image failed to load, initializing position anyway');
                initializePosition();
            }});
        }})();
    </script>
    """
    
    # Render the HTML component
    st.components.v1.html(html_code, height=750, scrolling=False)



def _generate_gpt_summary(ticker: str, api_key: str) -> str:
    """Generate a financial summary using GPT API with caching (3 months)."""
    if not api_key:
        return "⚠️ No se ha configurado una API KEY de GPT. Por favor, ingrese su API KEY en el sidebar."
    
    # Sanitize ticker input to prevent prompt injection
    # Stock tickers typically consist of uppercase letters and numbers only
    # Dots are common in some international tickers (e.g., BRK.B)
    sanitized_ticker = "".join(c for c in ticker if c.isalnum() or c == ".").upper()[:20]
    if not sanitized_ticker or not sanitized_ticker.replace(".", "").isalnum():
        return "⚠️ Ticker inválido."
    
    # Check cache first
    cache_key = f"gpt_summary_{sanitized_ticker}"
    cached_summary = cache_get(cache_key)
    if cached_summary:
        return cached_summary
    
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        
        # Use sanitized ticker in prompt
        prompt = f"Haz un resumen financiero de la empresa según el ticker ingresado {sanitized_ticker}, señalando a qué se dedica, cómo gana dinero y aspectos en los que destaca, el que debe ser escueto y resumido."
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Eres un analista financiero experto que proporciona resúmenes concisos y precisos sobre empresas."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=300,
            temperature=0.7
        )
        
        summary = response.choices[0].message.content.strip()
        
        # Cache the summary for 3 months
        cache_set(cache_key, summary, ttl_seconds=60 * 60 * 24 * 90)  # 3 months
        
        return summary
    except ImportError:
        return "⚠️ La librería openai no está instalada. Por favor, instálela para usar esta funcionalidad."
    except Exception as e:
        return f"⚠️ Error al generar el resumen: {str(e)}"


def _generate_perplexity_news_analysis(ticker: str, company_name: str, api_key: str) -> str:
    """Generate news analysis using Perplexity API."""
    if not api_key:
        return ""
    
    # Sanitize inputs to prevent prompt injection
    # Ticker: only alphanumeric and dots (e.g., BRK.B)
    sanitized_ticker = "".join(c for c in ticker if c.isalnum() or c == ".").upper()[:20]
    # Company name: allow alphanumeric, spaces, commas, and periods only
    sanitized_company = "".join(c for c in company_name if c.isalnum() or c in " .,").strip()[:100]
    
    if not sanitized_ticker or not sanitized_ticker.replace(".", "").isalnum():
        return ""
    
    # Check cache first (6 hours)
    cache_key = f"perplexity_news_{sanitized_ticker}"
    cached = cache_get(cache_key)
    if cached:
        return cached
    
    try:
        from openai import OpenAI
        
        client = OpenAI(
            api_key=api_key,
            base_url="https://api.perplexity.ai"
        )
        
        # Use sanitized inputs in prompt
        prompt = f"""Proporciona un análisis conciso de las noticias financieras más relevantes sobre {sanitized_ticker} ({sanitized_company}). 

Incluye:
- Eventos importantes del último mes
- Cambios significativos en valoración o perspectivas
- Anuncios corporativos relevantes
- Sentimiento general del mercado

Cita las fuentes principales."""
        
        response = client.chat.completions.create(
            model="llama-3.1-sonar-large-128k-online",
            messages=[
                {"role": "system", "content": "Eres un analista financiero experto que proporciona análisis de noticias concisos y bien fundamentados."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=500,
            temperature=0.3
        )
        
        analysis = response.choices[0].message.content.strip()
        
        # Cache for 6 hours
        cache_set(cache_key, analysis, ttl_seconds=60 * 60 * 6)
        
        return analysis
    except Exception as e:
        return f"⚠️ Error al generar análisis de noticias: {str(e)}"


def _plot_price_variation_5y(ticker: str) -> None:
    """Plot 5-year price variation chart with caching (24 hours)."""
    # Check cache first
    cache_key = f"price_chart_data_{ticker}"
    cached_data = cache_get(cache_key)
    
    if cached_data:
        # Reconstruct DataFrame with proper metadata using 'tight' orientation
        hist = pd.DataFrame.from_dict(cached_data, orient='tight')
    else:
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="5y", interval="1d")
            
            if hist.empty:
                st.warning("No hay datos de precio disponibles para los últimos 5 años.")
                return
            
            # Cache the data for 24 hours using 'tight' orientation to preserve structure
            cache_data = hist.to_dict(orient='tight')
            cache_set(cache_key, cache_data, ttl_seconds=60 * 60 * 24)  # 24 hours
        except Exception as e:
            st.error(f"Error al generar el gráfico de precio: {str(e)}")
            return
    
    try:
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=hist.index,
                y=hist['Close'],
                mode='lines',
                name='Precio',
                line=dict(color="#ff6d01", width=2),
            )
        )
        
        fig.update_layout(
            title=f"Variación del precio — {ticker} (5 años)",
            xaxis_title="Fecha",
            yaxis_title="Precio ($)",
            height=400,
            margin=dict(l=20, r=20, t=40, b=30),
            paper_bgcolor="#141f41",
            plot_bgcolor="#141f41",
            font=dict(color="#ffffff"),
            showlegend=False,
        )
        fig.update_yaxes(showgrid=False, zeroline=False)
        fig.update_xaxes(showgrid=False, zeroline=False)
        
        st.plotly_chart(fig, use_container_width=True, key=f"price_5y_{ticker}")
    except Exception as e:
        st.error(f"Error al generar el gráfico de precio: {str(e)}")


def _plot_drawdown(ticker: str) -> None:
    """Plot drawdown chart with caching (24 hours)."""
    # Check cache first
    cache_key = f"drawdown_chart_data_{ticker}"
    cached_data = cache_get(cache_key)
    
    if cached_data:
        # Reconstruct DataFrame with proper metadata using 'tight' orientation
        hist = pd.DataFrame.from_dict(cached_data, orient='tight')
    else:
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="5y", interval="1d")
            
            if hist.empty:
                st.warning("No hay datos disponibles para calcular el drawdown.")
                return
            
            # Cache the data for 24 hours using 'tight' orientation to preserve structure
            cache_data = hist.to_dict(orient='tight')
            cache_set(cache_key, cache_data, ttl_seconds=60 * 60 * 24)  # 24 hours
        except Exception as e:
            st.error(f"Error al generar el gráfico de drawdown: {str(e)}")
            return
    
    try:
        # Calculate drawdown
        close = hist['Close']
        running_max = close.cummax()
        drawdown = ((close - running_max) / running_max) * 100
        
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=drawdown.index,
                y=drawdown,
                mode='lines',
                name='Drawdown',
                line=dict(color="#ff00ff", width=2),
                fill='tozeroy',
                fillcolor='rgba(255, 0, 255, 0.3)',
            )
        )
        
        fig.update_layout(
            title=f"Drawdown — {ticker} (5 años)",
            xaxis_title="Fecha",
            yaxis_title="Drawdown (%)",
            height=400,
            margin=dict(l=20, r=20, t=40, b=30),
            paper_bgcolor="#141f41",
            plot_bgcolor="#141f41",
            font=dict(color="#ffffff"),
            showlegend=False,
        )
        fig.update_yaxes(showgrid=False, zeroline=False)
        fig.update_xaxes(showgrid=False, zeroline=False)
        
        st.plotly_chart(fig, use_container_width=True, key=f"drawdown_{ticker}")
    except Exception as e:
        st.error(f"Error al generar el gráfico de drawdown: {str(e)}")


def _hex_to_rgba(hex_color: str, alpha: float = 1.0) -> str:
    """Convert hex color to rgba string."""
    hex_color = hex_color.lstrip('#')
    r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    return f'rgba({r}, {g}, {b}, {alpha})'


def _render_52w_gauge(ticker: str, current_price: float, low_52w: float, high_52w: float) -> None:
    """
    Render 52-week range gauge chart.
    Shows current price position within the 52-week range.
    """
    try:
        # Validate data
        if low_52w is None or high_52w is None or current_price is None:
            st.info("No hay datos suficientes para mostrar el rango de 52 semanas.")
            return
        
        # Avoid division by zero
        if high_52w == low_52w:
            st.info("El rango de 52 semanas es muy estrecho para mostrar el gráfico.")
            return
        
        # Calculate position percentage
        range_52w = high_52w - low_52w
        position_pct = ((current_price - low_52w) / range_52w) * 100
        
        # Create gauge chart
        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=current_price,
            title={'text': f"Rango 52 Semanas — {ticker}", 'font': {'size': 20, 'color': "#ffffff"}},
            number={'prefix': "$", 'font': {'size': 28, 'color': "#ffffff"}},
            gauge={
                'axis': {
                    'range': [low_52w, high_52w],
                    'tickwidth': 1,
                    'tickcolor': "#ffffff",
                    'tickfont': {'color': "#ffffff", 'size': 12}
                },
                'bar': {'color': "#ff6d01", 'thickness': 0.75},
                'bgcolor': "#141f41",
                'borderwidth': 2,
                'bordercolor': "#ffffff",
                'steps': [
                    {'range': [low_52w, low_52w + range_52w * 0.33], 'color': _hex_to_rgba("#ff00ff", 0.3)},
                    {'range': [low_52w + range_52w * 0.33, low_52w + range_52w * 0.67], 'color': _hex_to_rgba("#01c2ef", 0.3)},
                    {'range': [low_52w + range_52w * 0.67, high_52w], 'color': _hex_to_rgba("#ff6d01", 0.3)},
                ],
                'threshold': {
                    'line': {'color': "#01c2ef", 'width': 4},
                    'thickness': 0.75,
                    'value': current_price
                }
            }
        ))
        
        fig.update_layout(
            height=300,
            margin=dict(l=20, r=20, t=60, b=20),
            paper_bgcolor="#141f41",
            font=dict(color="#ffffff"),
        )
        
        st.plotly_chart(fig, use_container_width=True, key=f"52w_gauge_{ticker}")
        
        # Display text summary below gauge
        st.markdown(
            f"""
            <div style='text-align: center; color: #ffffff; margin-top: -10px;'>
                <strong>52W Low:</strong> ${low_52w:,.2f} | 
                <strong>52W High:</strong> ${high_52w:,.2f} | 
                <strong>Actual:</strong> ${current_price:,.2f}<br>
                <strong>Posición:</strong> {position_pct:.1f}% del rango
            </div>
            """,
            unsafe_allow_html=True
        )
    except Exception as e:
        st.error(f"Error al generar el gráfico de rango 52 semanas: {str(e)}")


def _render_gurufocus_charts(ticker: str) -> None:
    """
    Display custom Gurufocus business model charts for ANY ticker with images.
    Shows HMM (How Makes Money) and BPS (Beneficio Por Segmento) charts.
    Charts are loaded from: src/assets/{TICKER} - HMM.png and {TICKER} - BPS.png
    """
    from pathlib import Path
    
    # Constants for Gurufocus image suffixes
    GURUFOCUS_HMM_SUFFIX = " - HMM.png"
    GURUFOCUS_BPS_SUFFIX = " - BPS.png"
    
    # Path to assets folder
    assets_path = Path(__file__).parent.parent / "assets"
    
    # Look for HMM and BPS images
    hmm_path = assets_path / f"{ticker}{GURUFOCUS_HMM_SUFFIX}"
    bps_path = assets_path / f"{ticker}{GURUFOCUS_BPS_SUFFIX}"
    
    # Collect available images
    image_paths = []
    if hmm_path.exists():
        image_paths.append(("How Makes Money", hmm_path))
    if bps_path.exists():
        image_paths.append(("Beneficio por Segmento", bps_path))
    
    if not image_paths:
        # No business model images found, fail silently
        return
    
    # Display section
    st.markdown("## 📊 Modelo de Negocio (Gurufocus)")
    st.caption(f"Análisis del modelo de negocio de {ticker}")
    
    # Display images in 2 columns (or 1 if only 1 image exists)
    if len(image_paths) == 1:
        # Only one image, center it
        try:
            st.image(str(image_paths[0][1]), caption=image_paths[0][0], use_container_width=True)
        except Exception:
            pass
    else:
        # Two images, side by side
        col1, col2 = st.columns(2)
        for idx, (caption, img_path) in enumerate(image_paths):
            with col1 if idx == 0 else col2:
                try:
                    st.image(str(img_path), caption=caption, use_container_width=True)
                except Exception:
                    pass
    
    st.divider()


# =========================================================
# Página principal
# =========================================================
def page_analysis() -> None:
    DAILY_LIMIT = 3
    user_email = _get_user_email()
    admin = is_admin()

    # CSS — sin sombras en KPIs, tarjetas individuales ni gráficos
    st.markdown(
        """
        <style>
        .search-middle > div[data-testid="stTextInput"] { max-width: 640px; margin: 0 auto; }
        div[data-testid="stTextInput"] input { border: none !important; box-shadow:none !important; }

        /* Contenedor de KPIs: sin sombra ni fondo */
        .kpis-container {
            background: transparent;
            border-radius: 0;
            padding: 0;
            box-shadow: none;
            margin-bottom: 16px;
        }

        /* KPI cards individuales: sin sombra, solo fondo y padding */
        .kpi-card {
          background: transparent;
          border-radius: 10px;
          padding: 12px;
          display: block;
          margin-bottom: 8px;
        }
        .kpi-label { font-size: 0.78rem; color: #ffffff; margin-bottom:6px; }
        .kpi-value { font-size: 1.4rem; font-weight:700; color: #01c2ef; }

        /* pequeño ajuste para los metrics bajo los charts */
        .stMetric { background: transparent; }

        /* Quitar sombras a contenedores de gráficos */
        div[data-testid="stPlotlyChart"] {
            box-shadow: none !important;
        }

        div[data-testid="stForm"] { max-width: 520px !important; margin: 0 auto !important; border-radius: 10px; }
        
        /* Logo with white square background with rounded corners */
        .logo-circle {
            width: 85px;
            height: 85px;
            border-radius: 12px;
            background-color: #ffffff;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 10px;
        }
        .logo-circle img {
            width: 100%;
            height: 100%;
            object-fit: contain;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Buscador (Enter activa) - MOVED FROM page_resumen
    c_left, c_mid, c_right = st.columns([1, 2, 1])
    with c_mid:
        st.markdown('<div class="search-middle">', unsafe_allow_html=True)
        
        def _submit_search():
            val = (st.session_state.get("ticker_main") or "").strip().upper()
            if val:
                st.session_state["ticker"] = val

        st.text_input(
            "Ticker (ej: AAPL, MSFT, KO)",
            key="ticker_main",
            label_visibility="visible",
            placeholder="Buscar ticker y presiona Enter (ej: AAPL, MSFT, KO)",
            on_change=_submit_search,
        )
        st.markdown("</div>", unsafe_allow_html=True)

    if "ticker" not in st.session_state:
        st.info("Escribe un ticker y presiona Enter para cargar datos.")
        return

    ticker = (st.session_state.get("ticker") or "").strip().upper()
    if not ticker:
        st.error("Ticker vacío.")
        return

    # Track last searched ticker to only consume counter on NEW ticker searches
    last_ticker = st.session_state.get("last_searched_ticker", None)
    is_new_ticker = (ticker != last_ticker)
    
    # Consumo límite - ONLY on new ticker entry
    if (not admin) and user_email and is_new_ticker:
        ok, rem_after = consume_search(user_email, DAILY_LIMIT, cost=1)
        if not ok:
            st.error("🚫 Búsquedas diarias alcanzadas. Vuelve mañana.")
            return
        # Update last searched ticker after successful consumption
        st.session_state["last_searched_ticker"] = ticker
    elif is_new_ticker:
        # For admin or other cases, just track the ticker without consuming
        st.session_state["last_searched_ticker"] = ticker
    
    # Carga datos - This uses cache, so repeated calls are efficient
    price = get_price_data(ticker) or {}
    profile = get_profile_data(ticker) or {}
    raw = profile.get("raw") if isinstance(profile, dict) else {}
    stats = get_key_stats(ticker) or {}
    divk = get_dividend_kpis(ticker) or {}

    # Company name for display in titles
    company_name = raw.get("longName") or raw.get("shortName") or profile.get("shortName") or ticker

    # Additional data for header display
    last_price = price.get("last_price")
    currency = price.get("currency") or ""
    delta_txt, pct_val = _fmt_delta(price.get("net_change"), price.get("pct_change"))

    website = (profile.get("website") or raw.get("website") or "") if isinstance(profile, dict) else ""
    logos = logo_candidates(website) if website else []
    logo_url = next((u for u in logos if isinstance(u, str) and u.startswith(("http://", "https://"))), "")

    # Header: logo left
    left, right = st.columns([1.15, 0.85], gap="large")
    with left:
        c_logo, c_text = st.columns([0.12, 0.88], gap="small", vertical_alignment="center")
        with c_logo:
            if logo_url:
                st.markdown(f'<div class="logo-circle"><img src="{logo_url}" /></div>', unsafe_allow_html=True)
        with c_text:
            st.markdown(f"### {ticker} — {company_name}")
            st.markdown(f"## {_fmt_price(last_price, currency)}")
            if delta_txt:
                color = "#01c2ef" if (pct_val is not None and pct_val >= 0) else "#ff00ff"
                st.markdown(f"<div style='margin-top:-6px; color:{color}; font-weight:600'>{delta_txt}</div>", unsafe_allow_html=True)

    # ---------- KPIs (reordenados: 4 arriba + 4 abajo) ----------
    with right:
        st.markdown("### KPIs clave")
        
        # Contenedor único con sombra para todos los KPIs
        st.markdown('<div class="kpis-container">', unsafe_allow_html=True)
        
        try:
            # Fila superior: 4 KPIs generales
            top_cols = st.columns(4, gap="large")
            with top_cols[0]:
                _kpi_card("Beta", _fmt_kpi(stats.get("beta")))
            with top_cols[1]:
                pe = stats.get("pe_ttm")
                pe_txt = (_fmt_kpi(pe) + "x") if isinstance(pe, (int, float)) else "N/D"
                _kpi_card("PER (TTM)", pe_txt)
            with top_cols[2]:
                _kpi_card("EPS (TTM)", _fmt_kpi(stats.get("eps_ttm")))
            with top_cols[3]:
                _kpi_card("Target 1Y", _fmt_kpi(stats.get("target_1y")))

            # Fila inferior: 4 KPIs relacionados con dividendos (incluye PayOut)
            bottom_cols = st.columns(4, gap="large")

            div_yield = _divk_get(divk, "div_yield", "dividend_yield", "dividendYield", "dividend_yield_pct")
            fwd_div_yield = _divk_get(divk, "fwd_div_yield", "forward_div_yield", "forward_dividend_yield")
            annual_div = _divk_get(divk, "annual_dividend", "annual_div", "annualDividend")
            payout = _divk_get(divk, "payout_ratio", "payout", "payoutRatio")

            with bottom_cols[0]:
                val = "N/D"
                if isinstance(div_yield, (int, float)):
                    val = _fmt_kpi(div_yield, suffix="%", decimals=2)
                elif div_yield:
                    val = _fmt_kpi(div_yield)
                _kpi_card("Dividend Yield", val)

            with bottom_cols[1]:
                val = "N/D"
                if isinstance(fwd_div_yield, (int, float)):
                    val = _fmt_kpi(fwd_div_yield, suffix="%", decimals=2)
                elif fwd_div_yield:
                    val = _fmt_kpi(fwd_div_yield)
                _kpi_card("Fwd Div Yield", val)

            with bottom_cols[2]:
                val = "N/D"
                if isinstance(annual_div, (int, float)):
                    val = _fmt_kpi(annual_div, decimals=2)
                elif annual_div:
                    val = _fmt_kpi(annual_div)
                _kpi_card("Div. anual ($)", val)

            with bottom_cols[3]:
                val = "N/D"
                if isinstance(payout, (int, float)):
                    val = _fmt_kpi(payout, suffix="%", decimals=0)
                elif payout:
                    val = _fmt_kpi(payout)
                _kpi_card("PayOut Ratio", val)
        finally:
            # Cerrar contenedor de KPIs (siempre se ejecuta)
            st.markdown('</div>', unsafe_allow_html=True)

    st.divider()

    # GPT Summary Section
    st.markdown("## Resumen Financiero")
    
    api_key = get_user_gpt_api_key(user_email)
    if api_key:
        # Use session state to store the summary for the current ticker
        # This ensures the summary persists when switching modules
        # Note: session_summary_key (gpt_summary_display_) is separate from cache_key (gpt_summary_)
        # - cache_key: shared across all users, persists 3 months in SQLite database (via cache_store)
        # - session_summary_key: per-user session, avoids re-generating on module switch
        session_summary_key = f"gpt_summary_display_{ticker}"
        
        # Only generate if not in session state or ticker changed
        if session_summary_key not in st.session_state:
            with st.spinner("Generando resumen con GPT..."):
                summary = _generate_gpt_summary(ticker, api_key)
                st.session_state[session_summary_key] = summary
        
        # Display the summary from session state
        st.markdown(st.session_state[session_summary_key])
    else:
        st.info("⚠️ Para ver el resumen generado por GPT, configure su API KEY en el sidebar.")

    st.divider()
    
    # Perplexity News Analysis (after GPT summary, before related posts)
    perplexity_key = get_user_perplexity_api_key(user_email)
    if perplexity_key:
        st.markdown("### 📰 Análisis de Noticias Recientes")
        
        session_news_key = f"perplexity_news_display_{ticker}"
        if session_news_key not in st.session_state:
            with st.spinner("Analizando noticias recientes con Perplexity..."):
                news = _generate_perplexity_news_analysis(ticker, company_name, perplexity_key)
                st.session_state[session_news_key] = news
        
        st.markdown(st.session_state[session_news_key])
        st.divider()
    
    # Show related blog posts
    related_posts = get_blog_posts_by_ticker(ticker)
    if related_posts:
        st.markdown("### 📰 Artículos relacionados")
        
        # Helper function to navigate to blog post
        def _navigate_to_blog_post(post_id: int):
            """Navigate to blog post detail view."""
            st.session_state["page_section"] = "Blogs"
            st.session_state["blog_view"] = "detail"
            st.session_state["selected_blog_post"] = post_id
        
        for post in related_posts[:3]:  # Mostrar máximo 3
            with st.container(border=True):
                st.markdown(f"**{post['title']}**")
                # Preview: primeros 100 caracteres
                preview = post['content'][:100].replace('\n', ' ') + "..."
                st.caption(preview)
                
                st.button(
                    "📖 Leer artículo completo",
                    key=f"read_blog_{post['id']}",
                    use_container_width=True,
                    on_click=_navigate_to_blog_post,
                    args=(post['id'],)
                )
        st.divider()

    # Charts Section
    st.markdown("## Análisis de Precio")
    col1, col2 = st.columns(2)
    
    with col1:
        _plot_price_variation_5y(ticker)
    
    with col2:
        _plot_drawdown(ticker)
    
    # 52-Week Range Gauge
    st.markdown("### Rango 52 Semanas")
    range_data = get_52w_range(ticker)
    _render_52w_gauge(
        ticker,
        range_data.get("current_price"),
        range_data.get("low_52w"),
        range_data.get("high_52w")
    )
    
    # Custom Gurufocus charts for specific tickers
    _render_gurufocus_charts(ticker)
