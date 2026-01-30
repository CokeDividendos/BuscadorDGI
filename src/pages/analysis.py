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
    """Try multiple candidate keys for dividend kpis (some variants exist)."""
    for k in keys:
        if not isinstance(divk, dict):
            continue
        v = divk.get(k)
        if v is not None:
            return v
    return None


# =========================================================
# Datos dividendos (cache)
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
# Gráficos (mismos helpers de antes)
# =========================================================
def _plot_dividend_evolution(ticker: str, price_daily: pd.DataFrame, dividends: pd.Series) -> None:
    annual = _annual_dividends_last_years(dividends, YEARS)

    if annual.empty:
        st.warning("No hay dividendos suficientes para graficar la evolución (últimos 5 años).")
        return

    cagr = _cagr_from_annual(annual)
    if cagr is None:
        title = f"Evolución del dividendo anual — {ticker} (últimos {YEARS} años)"
    else:
        title = f"Evolución del dividendo anual — {ticker} | CAGR: {cagr:.2f}% (últimos {YEARS} años)"

    # modern card wrapper start
    st.markdown('<div class="tab-card">', unsafe_allow_html=True)

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
        title=title,
        xaxis_title="Año",
        yaxis_title="Dividendo ($)",
        height=460,
        margin=dict(l=20, r=20, t=60, b=30),
    )
    st.plotly_chart(fig, use_container_width=True, key=f"div_evo_{ticker}")

    with st.expander("Ver tabla (últimos 5 años)"):
        st.dataframe(pd.DataFrame({"Año": annual.index, "Dividendo anual": annual.values}).set_index("Año"), use_container_width=True)

    st.markdown('</div>', unsafe_allow_html=True)
    # modern card wrapper end


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

    st.markdown('<div class="tab-card">', unsafe_allow_html=True)

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
        title=f"Seguridad del dividendo — {ticker} (últimos {YEARS} años disponibles)",
        xaxis_title="Año",
        yaxis_title="USD",
        yaxis2=dict(title="FCF Payout (%)", overlaying="y", side="right"),
        barmode="group",
        height=520,
        margin=dict(l=20, r=20, t=60, b=30),
    )
    st.plotly_chart(fig, use_container_width=True, key=f"div_safe_{ticker}")

    with st.expander("Ver tabla (últimos 5 años)"):
        st.dataframe(out, use_container_width=True)

    st.markdown('</div>', unsafe_allow_html=True)


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

    st.markdown('<div class="tab-card">', unsafe_allow_html=True)

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

    title = f"Geraldine Weiss — {ticker} (últimos {YEARS} años)"
    fig.update_layout(
        title=title,
        xaxis_title="Fecha",
        yaxis_title="Precio ($)",
        height=520,
        margin=dict(l=20, r=20, t=60, b=40),
    )
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

    st.markdown('</div>', unsafe_allow_html=True)


# =========================================================
# Página principal
# =========================================================
def page_analysis() -> None:
    DAILY_LIMIT = 3
    user_email = _get_user_email()
    admin = is_admin()

    # CSS: search / cards / login adjustments (applies site-wide)
    st.markdown(
        """
        <style>
        /* Search input: centered and limited to 50% width */
        .search-middle > div[data-testid="stTextInput"] { max-width: 640px; margin: 0 auto; }
        /* Remove inner border of the search input */
        div[data-testid="stTextInput"] input { border: none !important; box-shadow:none !important; }
        /* Modern card for tabs */
        .tab-card {
          background: #ffffff;
          border-radius: 12px;
          padding: 12px;
          box-shadow: 0 6px 18px rgba(20,20,20,0.08);
          margin-bottom: 12px;
        }
        /* KPI card styling */
        .kpi-card { background: transparent; border: none; padding: 10px 6px; }
        .kpi-label { font-size: 0.78rem; color: rgba(0,0,0,0.55); margin-bottom:6px; }
        .kpi-value { font-size: 1.4rem; font-weight:700; }
        /* Narrow forms (affects login) */
        div[data-testid="stForm"] { max-width: 520px !important; margin: 0 auto !important; border-radius: 10px; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Sidebar
    with st.sidebar:
        if admin:
            if st.button("🧹 Limpiar caché", key="clear_cache_btn", use_container_width=True):
                cache_clear_all()
                st.success("Caché limpiado.")
                st.rerun()

        limit_box = st.empty()
        if admin:
            limit_box.success("👑 Admin: sin límite diario (alimenta el caché global).")
        else:
            if user_email:
                rem = remaining_searches(user_email, DAILY_LIMIT)
                limit_box.info(f"🔎 Búsquedas restantes hoy: {rem}/{DAILY_LIMIT}")
            else:
                limit_box.warning("No se detectó el correo del usuario.")

    # ---------- Buscador (sin botón, Enter activa) ----------
    st.markdown("## 🔎 Buscador")
    # columns to keep the input centered and not full width
    c_left, c_mid, c_right = st.columns([1, 2, 1])
    with c_mid:
        # wrapper class to limit width via CSS above
        st.markdown('<div class="search-middle">', unsafe_allow_html=True)
        if "ticker_main" not in st.session_state:
            st.session_state["ticker_main"] = "AAPL"

        def _submit_search():
            val = (st.session_state.get("ticker_main") or "").strip().upper()
            if val:
                st.session_state["ticker"] = val
                # rerun happens automatically on_change

        st.text_input(
            "Ticker (ej: AAPL, MSFT, KO)",
            key="ticker_main",
            value=st.session_state.get("ticker_main", "AAPL"),
            label_visibility="visible",
            placeholder="Buscar ticker y presiona Enter (ej: AAPL, MSFT, KO)",
            on_change=_submit_search,
        )
        st.markdown("</div>", unsafe_allow_html=True)

    # If user has not triggered search yet, inform
    if "ticker" not in st.session_state:
        st.info("Escribe un ticker y presiona Enter para cargar datos.")
        return

    ticker = (st.session_state.get("ticker") or "").strip().upper()
    if not ticker:
        st.error("Ticker vacío.")
        return

    # Consumo límite
    if (not admin) and user_email:
        ok, rem_after = consume_search(user_email, DAILY_LIMIT, cost=1)
        if not ok:
            st.sidebar.error("🚫 Búsquedas diarias alcanzadas. Vuelve mañana.")
            return
        st.sidebar.info(f"🔎 Búsquedas restantes hoy: {rem_after}/{DAILY_LIMIT}")

    # -----------------------------
    # Carga datos
    # -----------------------------
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

    # ---------- Header: logo to the LEFT of name/price ----------
    left, right = st.columns([1.15, 0.85], gap="large")
    with left:
        c_logo, c_text = st.columns([0.12, 0.88], gap="small", vertical_alignment="center")
        with c_logo:
            if logo_url:
                st.image(logo_url, width=72)  # larger logo
        with c_text:
            st.markdown(f"### {ticker} — {company_name}")
            st.markdown(f"## {_fmt_price(last_price, currency)}")
            if delta_txt:
                color = "#16a34a" if (pct_val is not None and pct_val >= 0) else "#dc2626"
                st.markdown(f\"<div style='margin-top:-6px; color:{color}; font-weight:600'>{delta_txt}</div>\", unsafe_allow_html=True)

    # KPIs (incluye 4 dividendos dentro de KPIs)
    with right:
        st.markdown("### KPIs clave")
        r1c1, r1c2, r1c3 = st.columns(3, gap="large")
        r2c1, r2c2, r2c3 = st.columns(3, gap="large")

        with r1c1:
            _kpi_card("Beta", _fmt_kpi(stats.get("beta")))
        with r1c2:
            pe = stats.get("pe_ttm")
            pe_txt = (_fmt_kpi(pe) + "x") if isinstance(pe, (int, float)) else "N/D"
            _kpi_card("PER (TTM)", pe_txt)
        with r1c3:
            _kpi_card("EPS (TTM)", _fmt_kpi(stats.get("eps_ttm")))

        # Dividend Kpis (otros KPIs migrados aquí)
        div_yield = _divk_get(divk, "div_yield", "dividend_yield", "dividendYield", "dividend_yield_pct")
        fwd_div_yield = _divk_get(divk, "fwd_div_yield", "forward_div_yield", "forward_dividend_yield")
        annual_div = _divk_get(divk, "annual_dividend", "annual_div", "annualDividend")
        payout = _divk_get(divk, "payout_ratio", "payout", "payoutRatio")

        with r2c1:
            _kpi_card("Dividend Yield", _fmt_kpi(div_yield, suffix="%", decimals=2) if isinstance(div_yield, (int, float)) else (_fmt_kpi(div_yield) if div_yield else "N/D"))
        with r2c2:
            _kpi_card("Forward Div. Yield", _fmt_kpi(fwd_div_yield, suffix="%", decimals=2) if isinstance(fwd_div_yield, (int, float)) else (_fmt_kpi(fwd_div_yield) if fwd_div_yield else "N/D"))
        with r2c3:
            _kpi_card("Div. anual ($)", _fmt_kpi(annual_div, decimals=2) if isinstance(annual_div, (int, float)) else (_fmt_kpi(annual_div) if annual_div else "N/D"))

        # Un pequeño KPI adicional (payout)
        with r1c1:
            # reutilizamos r1c1 solo para mostrar payout en otra linea (visual)
            pass
        # display payout under the KPIs as plain text next to others:
        with r2c1:
            st.caption("PayOut Ratio")
            st.markdown(f"**{_fmt_kpi(payout,suffix='%',decimals=0) if isinstance(payout,(int,float)) else (_fmt_kpi(payout) if payout else 'N/D')}**")

    st.divider()

    # -----------------------------
    # Main tabs (restauradas)
    # -----------------------------
    main_tabs = st.tabs(
        [
            "Dividendos",
            "Múltiplos",
            "Balance",
            "Estado de Resultados",
            "Estado de Flujo de Efectivo",
            "Otro",
        ]
    )

    # TAB Dividendos con sub-tabs (tarjetas modernizadas)
    with main_tabs[0]:
        inputs = _load_dividend_inputs(ticker, YEARS)
        price_daily = inputs["price_daily"]
        dividends = inputs["dividends"]
        cashflow = inputs["cashflow"]

        sub_tabs = st.tabs(["📌 Geraldine Weiss", "📈 Evolución del dividendo", "🛡️ Seguridad del dividendo"])
        with sub_tabs[0]:
            _plot_geraldine_weiss(ticker, price_daily, dividends)
        with sub_tabs[1]:
            _plot_dividend_evolution(ticker, price_daily, dividends)
        with sub_tabs[2]:
            _plot_dividend_safety(ticker, cashflow)

    # Otros tabs: placeholders
    with main_tabs[1]:
        st.info("Aquí irán los gráficos de Múltiplos (pendiente).")
    with main_tabs[2]:
        st.info("Aquí irán los gráficos de Balance (pendiente).")
    with main_tabs[3]:
        st.info("Aquí irán los gráficos de Estado de Resultados (pendiente).")
    with main_tabs[4]:
        st.info("Aquí irán los gráficos de Flujo de Efectivo (pendiente).")
    with main_tabs[5]:
        st.info("Sección 'Otro' (pendiente).")
