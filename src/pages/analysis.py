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
            text=[f"${v:.2f}" for v in annual.values],
            textposition="outside",
        )
    )
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="Dividendo anual ($)",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(showgrid=False)
    fig.update_xaxes(showgrid=False)
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
    fig.add_trace(go.Bar(x=out.index.astype(str), y=out["FCF"], name="FCF", text=out["FCF"].round(0), textposition="outside"))
    fig.add_trace(
        go.Bar(
            x=out.index.astype(str),
            y=out["Dividendos pagados"],
            name="Dividendos pagados",
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
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    # quitar líneas horizontales
    fig.update_yaxes(showgrid=False)
    fig.update_xaxes(showgrid=False)
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
    fig.add_trace(go.Scatter(x=price_daily.index, y=price_daily["Close"], mode="lines", name="Precio (diario)"))
    fig.add_trace(go.Scatter(x=monthly.index, y=monthly["Sobrevalorado"], mode="lines", name="Banda sobrevalorado", line=dict(dash="dot")))
    fig.add_trace(go.Scatter(x=monthly.index, y=monthly["Infravalorado"], mode="lines", name="Banda infravalorado", line=dict(dash="dot")))

    current_price = float(price_daily["Close"].iloc[-1])
    fig.add_trace(
        go.Scatter(
            x=[price_daily.index[-1]],
            y=[current_price],
            mode="markers+text",
            name="Precio actual",
            text=[f"${current_price:.2f}"],
            textposition="top center",
        )
    )

    fig.update_layout(
        xaxis_title="Fecha",
        yaxis_title="Precio ($)",
        height=520,
        margin=dict(l=20, r=20, t=10, b=40),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    # quitar líneas horizontales
    fig.update_yaxes(showgrid=False)
    fig.update_xaxes(showgrid=False)
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
    fig.add_trace(go.Bar(x=data.index.astype(str), y=data["Activos Totales"], name="Activos Totales"))
    fig.add_trace(go.Bar(x=data.index.astype(str), y=data["Activos Corrientes"], name="Activos Corrientes"))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="USD",
        barmode="group",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(showgrid=False)
    fig.update_xaxes(showgrid=False)
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
    fig.add_trace(go.Bar(x=data.index.astype(str), y=data["Pasivos Totales"], name="Pasivos Totales"))
    fig.add_trace(go.Bar(x=data.index.astype(str), y=data["Pasivos Corrientes"], name="Pasivos Corrientes"))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="USD",
        barmode="group",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(showgrid=False)
    fig.update_xaxes(showgrid=False)
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
    fig.add_trace(go.Bar(x=data.index.astype(str), y=data["Deuda Total"], name="Deuda Total"))
    fig.add_trace(go.Bar(x=data.index.astype(str), y=data["Deuda Neta"], name="Deuda Neta"))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="USD",
        barmode="group",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(showgrid=False)
    fig.update_xaxes(showgrid=False)
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
        text=[_fmt_large_number(v) for v in equity.values],
        textposition="outside"
    ))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="USD",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(showgrid=False)
    fig.update_xaxes(showgrid=False)
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
        text=[_fmt_large_number(v) for v in revenue.values],
        textposition="outside"
    ))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="USD",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(showgrid=False)
    fig.update_xaxes(showgrid=False)
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
    
    for col in margins.columns:
        fig.add_trace(go.Scatter(
            x=margins.index.astype(str), 
            y=margins[col].values, 
            mode="lines+markers",
            name=col
        ))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="Porcentaje (%)",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(showgrid=False)
    fig.update_xaxes(showgrid=False)
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
        text=[f"${v:.2f}" for v in eps.values],
        textposition="outside"
    ))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="USD",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(showgrid=False)
    fig.update_xaxes(showgrid=False)
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
        text=[f"{v/1e9:.2f}B" if abs(v) >= 1e9 else f"{v/1e6:.2f}M" for v in shares.values],
        textposition="outside"
    ))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="Número de Acciones",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(showgrid=False)
    fig.update_xaxes(showgrid=False)
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
    
    st.markdown(f"**Flujo de Caja Operativo vs CapEx — {ticker}**")
    fig = go.Figure()
    fig.add_trace(go.Bar(x=data.index.astype(str), y=data["Flujo de Caja Operativo"], name="Flujo de Caja Operativo"))
    fig.add_trace(go.Bar(x=data.index.astype(str), y=data["CapEx"], name="CapEx"))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="USD",
        barmode="group",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(showgrid=False)
    fig.update_xaxes(showgrid=False)
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
        marker_color=["green" if v > 0 else "red" for v in debt_issued.values]
    ))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="USD",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(showgrid=False)
    fig.update_xaxes(showgrid=False)
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
        name="Pago de Deuda"
    ))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="USD",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(showgrid=False)
    fig.update_xaxes(showgrid=False)
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
        name="Recompra de Acciones"
    ))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title="USD",
        height=460,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(showgrid=False)
    fig.update_xaxes(showgrid=False)
    st.plotly_chart(fig, use_container_width=True, key=f"buybacks_{ticker}")


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
        text=[f"{v:.2f}" for v in ratio_data.values],
        textposition="top center"
    ))
    
    fig.update_layout(
        xaxis_title="Año",
        yaxis_title=ratio_name,
        height=400,
        margin=dict(l=20, r=20, t=10, b=30),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(showgrid=False)
    fig.update_xaxes(showgrid=False)
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
        .kpi-label { font-size: 0.78rem; color: rgba(0,0,0,0.55); margin-bottom:6px; }
        .kpi-value { font-size: 1.4rem; font-weight:700; }

        /* pequeño ajuste para los metrics bajo los charts */
        .stMetric { background: transparent; }

        /* Quitar sombras a contenedores de gráficos */
        div[data-testid="stPlotlyChart"] {
            box-shadow: none !important;
        }

        div[data-testid="stForm"] { max-width: 520px !important; margin: 0 auto !important; border-radius: 10px; }
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
                # Mark that a new ticker was just submitted
                st.session_state["ticker_just_submitted"] = True

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
        # Clear the submission flag if it exists
        st.session_state.pop("ticker_just_submitted", None)
    elif is_new_ticker and admin:
        # For admin, just track the ticker without consuming
        st.session_state["last_searched_ticker"] = ticker
        st.session_state.pop("ticker_just_submitted", None)
    else:
        # Same ticker, just clear the flag
        st.session_state.pop("ticker_just_submitted", None)
    
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
                st.image(logo_url, width=72)
        with c_text:
            st.markdown(f"### {ticker} — {company_name}")
            st.markdown(f"## {_fmt_price(last_price, currency)}")
            if delta_txt:
                color = "#16a34a" if (pct_val is not None and pct_val >= 0) else "#dc2626"
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
                # Display ratios in a grid layout (2 columns)
                ratio_cols = list(ratios.columns)
                num_ratios = len(ratio_cols)
                
                for i in range(0, num_ratios, 2):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        if i < num_ratios:
                            _plot_ratio_evolution(ticker, ratio_cols[i], ratios[ratio_cols[i]])
                    
                    with col2:
                        if i + 1 < num_ratios:
                            _plot_ratio_evolution(ticker, ratio_cols[i + 1], ratios[ratio_cols[i + 1]])
