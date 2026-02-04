# src/pages/analysis.py
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

# IMPORTAR sólo is_admin desde auth — _get_user_email se define localmente
from src.auth import is_admin
from src.services.cache_store import cache_clear_all
from src.services.finance_data import (
    get_key_stats,
    get_price_data,
    get_profile_data,
    get_dividend_kpis,
)
from src.services.logos import logo_candidates
from src.services.usage_limits import consume_search, remaining_searches

# =========================================================
# Constantes
# =========================================================
YEARS = 5
DIVIDENDS_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 días

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


def _plot_geraldine_weiss(ticker: str, price_daily: pd.DataFrame, dividends: pd.Series) -> None:
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
    last_div = float(annual.loc[last_year])

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

    cols = st.columns(6)
    cols[0].metric("Precio actual", f"${current_price:,.2f}")
    cols[1].metric("Div. anual (último)", f"${last_div:,.2f}")
    cols[2].metric("CAGR div.", f"{cagr:.2f}%" if cagr is not None else "N/D")
    cols[3].metric("Yield mín.", f"{y_min:.2%}")
    cols[4].metric("Yield máx.", f"{y_max:.2%}")
    cols[5].metric("Infravalorado (teórico)", f"${(last_div / y_max):,.2f}" if y_max > 0 else "N/D")

    with st.expander("Ver tabla mensual (GW)"):
        show = monthly[["Close", "DivAnual", "Yield", "Sobrevalorado", "Infravalorado"]].copy()
        st.dataframe(show, use_container_width=True)


# =========================================================
# Financial Statements Data Loaders
# =========================================================
@st.cache_data(ttl=DIVIDENDS_CACHE_TTL_SECONDS, show_spinner=False)
def _load_financial_statements(ticker: str) -> Dict[str, Any]:
    """Load balance sheet, income statement, and cash flow data"""
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
    
    return {
        "balance_sheet": balance_sheet,
        "income_stmt": income_stmt,
        "cashflow": cashflow,
    }


def _prepare_financial_df(df: pd.DataFrame, years: int = YEARS) -> pd.DataFrame:
    """Transpose and prepare financial statement dataframe"""
    if df is None or df.empty:
        return pd.DataFrame()
    
    result = df.transpose().copy()
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
    import numpy as np
    
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
            fig_fc.add_trace(
                go.Bar(
                    x=df_fc_usage.index.astype(str),
                    y=df_fc_usage[col],
                    name=col,
                    marker_color=colors.get(col, "#ffffff"),
                    text=df_fc_usage[col].apply(lambda x: f"{x/1e6:.0f}M" if abs(x) >= 1e6 else f"{x:.0f}" if pd.notna(x) else ""),
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
    
    inventory_col = _find_column(balance_df, ["inventory"])
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
        
        /* Logo with white circle background */
        .logo-circle {
            width: 90px;
            height: 90px;
            border-radius: 20%;
            background-color: #ffffff;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 8px;
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

    # Note: Sidebar sections are now handled in router.py
    # No sidebar logic needed here anymore

    # Buscador (Enter activa)
    c_left, c_mid, c_right = st.columns([1, 2, 1])
    with c_mid:
        st.markdown('<div class="search-middle">', unsafe_allow_html=True)
        if "ticker_main" not in st.session_state:
            st.session_state["ticker_main"] = "AAPL"

        def _submit_search():
            val = (st.session_state.get("ticker_main") or "").strip().upper()
            if val:
                st.session_state["ticker"] = val

        st.text_input(
            "Ticker (ej: AAPL, MSFT, KO)",
            key="ticker_main",
            value=st.session_state.get("ticker_main", "AAPL"),
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
    
    # Consumo límite - ONLY on new ticker entry, not on section changes
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

    company_name = raw.get("longName") or raw.get("shortName") or profile.get("shortName") or ticker
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
            # Try-finally ensures HTML closing tag is always rendered, even if data processing fails
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

    # Display content based on selected section
    selected_section = st.session_state.get("analysis_section", "Dividendos")
    
    if selected_section == "Dividendos":
        inputs = _load_dividend_inputs(ticker, YEARS)
        price_daily = inputs["price_daily"]
        dividends = inputs["dividends"]
        cashflow = inputs["cashflow"]

        st.markdown("## Valoración por dividendo")
        sub_tabs = st.tabs(["📈 Evolución del dividendo", "🛡️ Seguridad del dividendo", "📌 Geraldine Weiss"])
        with sub_tabs[0]:
            _plot_dividend_evolution(ticker, price_daily, dividends)
        with sub_tabs[1]:
            _plot_dividend_safety(ticker, cashflow)
        with sub_tabs[2]:
            _plot_geraldine_weiss(ticker, price_daily, dividends)
    
    elif selected_section == "Balance":
        st.markdown("## Balance")
        financial_data = _load_financial_statements(ticker)
        balance_df = _prepare_financial_df(financial_data["balance_sheet"], YEARS)
        
        if balance_df.empty:
            st.warning("No hay datos de balance disponibles para este ticker.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                _plot_assets_evolution(ticker, balance_df)
                _plot_debt_evolution(ticker, balance_df)
            with col2:
                _plot_liabilities_evolution(ticker, balance_df)
                _plot_equity_evolution(ticker, balance_df)
    
    elif selected_section == "EERR":
        st.markdown("## Estado de Resultados")
        financial_data = _load_financial_statements(ticker)
        income_df = _prepare_financial_df(financial_data["income_stmt"], YEARS)
        
        if income_df.empty:
            st.warning("No hay datos de estado de resultados disponibles para este ticker.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                _plot_revenue_evolution(ticker, income_df)
                _plot_eps_evolution(ticker, income_df)
            with col2:
                _plot_margins_evolution(ticker, income_df)
                _plot_shares_outstanding(ticker, income_df)
    
    elif selected_section == "EFE":
        st.markdown("## Estado de Flujo de Efectivo")
        financial_data = _load_financial_statements(ticker)
        cashflow_df = _prepare_financial_df(financial_data["cashflow"], YEARS)
        
        if cashflow_df.empty:
            st.warning("No hay datos de flujo de efectivo disponibles para este ticker.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                _plot_cashflow_vs_capex(ticker, cashflow_df)
                _plot_debt_repayment(ticker, cashflow_df)
            with col2:
                _plot_debt_issuance(ticker, cashflow_df)
                _plot_share_buybacks(ticker, cashflow_df)
    
    elif selected_section == "Valoración por múltiplos":
        st.markdown("## Valoración por múltiplos")
        financial_data = _load_financial_statements(ticker)
        balance_df = _prepare_financial_df(financial_data["balance_sheet"], YEARS)
        income_df = _prepare_financial_df(financial_data["income_stmt"], YEARS)
        cashflow_df = _prepare_financial_df(financial_data["cashflow"], YEARS)
        
        # Get ticker info for market cap and PE ratio
        t = yf.Ticker(ticker)
        info = t.info
        
        if balance_df.empty and income_df.empty and cashflow_df.empty:
            st.warning("No hay datos financieros suficientes para la valoración por múltiplos.")
        else:
            # Create tabs for each chart
            sub_tabs = st.tabs(["💰 Evolución de la Deuda", "📊 Evolución del PER", "📈 Evolución EV/EBITDA", "📊 Uso del FC"])
            with sub_tabs[0]:
                if not balance_df.empty and not cashflow_df.empty:
                    _plot_debt_fcf_evolution(ticker, balance_df, cashflow_df)
                else:
                    st.warning("No hay datos suficientes de balance y flujo de efectivo para este análisis.")
            with sub_tabs[1]:
                if not income_df.empty:
                    _plot_per_evolution(ticker, income_df, info)
                else:
                    st.warning("No hay datos suficientes de estado de resultados para este análisis.")
            with sub_tabs[2]:
                if not income_df.empty and not balance_df.empty:
                    _plot_ev_ebitda_evolution(ticker, income_df, balance_df, info)
                else:
                    st.warning("No hay datos suficientes para este análisis.")
            with sub_tabs[3]:
                if not cashflow_df.empty:
                    _plot_fc_usage(ticker, cashflow_df)
                else:
                    st.warning("No hay datos suficientes de flujo de efectivo para este análisis.")
    
    elif selected_section == "Análisis Razonado":
        st.markdown("## Análisis Razonado")
        financial_data = _load_financial_statements(ticker)
        balance_df = _prepare_financial_df(financial_data["balance_sheet"], YEARS)
        income_df = _prepare_financial_df(financial_data["income_stmt"], YEARS)
        cashflow_df = _prepare_financial_df(financial_data["cashflow"], YEARS)
        
        if balance_df.empty and income_df.empty:
            st.warning("No hay datos financieros suficientes para el análisis razonado.")
        else:
            ratios = _calculate_financial_ratios(balance_df, income_df, cashflow_df, ticker)
            
            if ratios.empty:
                st.info("No se pudieron calcular ratios financieros con los datos disponibles.")
            else:
                # Display ratios in a two-column layout: table on left, chart on right
                ratio_cols = list(ratios.columns)
                
                # Check if we have any ratios to display
                if not ratio_cols:
                    st.info("No se pudieron calcular ratios financieros con los datos disponibles.")
                else:
                    # Transpose ratios DataFrame for better table display
                    # Rows will be metrics, columns will be years
                    ratios_transposed = ratios.T
                    
                    # Initialize selected metric in session state if not exists
                    session_key = f"selected_ratio_{ticker}"
                    if session_key not in st.session_state or st.session_state[session_key] not in ratio_cols:
                        st.session_state[session_key] = ratio_cols[0]
                    
                    # Create two columns: left for table, right for chart
                    col_table, col_chart = st.columns([1, 1])
                    
                    with col_table:
                        st.markdown("### Métricas Financieras")
                        
                        # Display the table with clickable rows
                        # Create a formatted DataFrame for display
                        display_df = ratios_transposed.copy()
                        
                        # Format values to 2 decimal places
                        try:
                            # Use map() for pandas >= 2.1, applymap() for older versions
                            display_df = display_df.map(lambda x: f"{x:.2f}" if pd.notna(x) else "N/D")
                        except AttributeError:
                            # Fallback to applymap for older pandas versions
                            display_df = display_df.applymap(lambda x: f"{x:.2f}" if pd.notna(x) else "N/D")
                        
                        # Display the dataframe
                        st.dataframe(
                            display_df,
                            use_container_width=True,
                            height=400
                        )
                        
                        # Add dropdown (selectbox) for metric selection
                        st.markdown("**Seleccione una métrica para visualizar:**")
                        
                        # Calculate default index for selectbox
                        default_index = ratio_cols.index(st.session_state[session_key])
                        
                        selected_metric = st.selectbox(
                            "Métrica",
                            ratio_cols,
                            index=default_index,
                            key=f"ratio_selector_{ticker}",
                            label_visibility="collapsed"
                        )
                        
                        # Update session state
                        st.session_state[session_key] = selected_metric
                    
                    with col_chart:
                        st.markdown("### Gráfico de Evolución")
                        
                        # Plot the selected ratio
                        selected_ratio_name = st.session_state[session_key]
                        selected_ratio_data = ratios[selected_ratio_name]
                        _plot_ratio_evolution(ticker, selected_ratio_name, selected_ratio_data)
