# src/pages/analysis.py
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from src.auth import is_admin
from src.services.cache_store import cache_clear_all
from src.services.finance_data import (
    get_dividend_kpis,
    get_key_stats,
    get_price_data,
    get_profile_data,
)
from src.services.logos import logo_candidates
from src.services.usage_limits import consume_search, remaining_searches

# =========================================================
# Constantes
# =========================================================
YEARS_BACK = 5
TTL_30D = 60 * 60 * 24 * 30  # 30 días


# =========================================================
# Helpers generales
# =========================================================
def _get_user_email() -> str:
    for key in ["auth_email", "user_email", "email", "username", "user", "logged_email"]:
        v = st.session_state.get(key)
        if isinstance(v, str) and "@" in v:
            return v.strip().lower()
    return ""


def _fmt_price(x, currency: str) -> str:
    if not isinstance(x, (int, float)):
        return "N/D"
    s = f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} {currency}".strip()


def _fmt_delta(net, pct) -> tuple[str | None, float | None]:
    if isinstance(net, (int, float)) and isinstance(pct, (int, float)):
        return f"{net:+.2f} ({pct:+.2f}%)", float(pct)
    return None, None


def _fmt_kpi(x, suffix: str = "", decimals: int = 2) -> str:
    return f"{x:.{decimals}f}{suffix}" if isinstance(x, (int, float)) else "N/D"


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


def _years_ago_start(years: int) -> date:
    # Buffer ~2 meses para asegurar data del primer año
    return date.today() - timedelta(days=int(years * 365.25) + 60)


def _safe_float(x) -> float | None:
    try:
        if x is None:
            return None
        v = float(x)
        if pd.isna(v):
            return None
        return v
    except Exception:
        return None


# =========================================================
# Cache (30 días) — datos para gráficos Dividendos
# =========================================================
@st.cache_data(ttl=TTL_30D, show_spinner=False)
def _yf_history_5y(ticker: str) -> pd.DataFrame:
    tk = yf.Ticker(ticker)
    df = tk.history(period=f"{YEARS_BACK}y", interval="1d", auto_adjust=False)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.reset_index().rename(columns={"Date": "date"})
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


@st.cache_data(ttl=TTL_30D, show_spinner=False)
def _yf_dividends(ticker: str) -> pd.Series:
    tk = yf.Ticker(ticker)
    s = tk.dividends
    if s is None or len(s) == 0:
        return pd.Series(dtype="float64")
    s.index = pd.to_datetime(s.index)
    start = pd.Timestamp(_years_ago_start(YEARS_BACK))
    return s[s.index >= start]


@st.cache_data(ttl=TTL_30D, show_spinner=False)
def _yf_cashflow_annual(ticker: str) -> pd.DataFrame:
    tk = yf.Ticker(ticker)
    cf = tk.cashflow
    if cf is None or cf.empty:
        return pd.DataFrame()

    df = cf.transpose().copy()
    # índice a año
    try:
        df.index = pd.to_datetime(df.index).year
    except Exception:
        df.index = pd.Index([int(str(x)[:4]) for x in df.index])

    df = df.sort_index()
    return df.tail(YEARS_BACK)


@st.cache_data(ttl=TTL_30D, show_spinner=False)
def _yf_info(ticker: str) -> dict:
    tk = yf.Ticker(ticker)
    try:
        return dict(tk.info or {})
    except Exception:
        return {}


# =========================================================
# Dividendos — cálculos y gráficos (últimos 5 años)
# =========================================================
def _annual_dividends_5y(divs: pd.Series) -> pd.Series:
    if divs is None or divs.empty:
        return pd.Series(dtype="float64")

    annual = divs.resample("Y").sum().astype(float).dropna()
    annual.index = annual.index.year

    current_year = datetime.today().year
    min_year = current_year - YEARS_BACK
    annual = annual[(annual.index >= min_year) & (annual.index <= current_year)]
    return annual


def _cagr_from_annual_divs(annual: pd.Series) -> float | None:
    # CAGR usando primer año vs penúltimo (evita año incompleto actual)
    if annual is None or len(annual) < 3:
        return None
    first = _safe_float(annual.iloc[0])
    penultimate = _safe_float(annual.iloc[-2])
    if not first or not penultimate or first <= 0:
        return None
    n_years = int(annual.index[-2] - annual.index[0])
    if n_years <= 0:
        return None
    return ((penultimate / first) ** (1 / n_years) - 1) * 100


def _dividend_panel_selector() -> str:
    """
    Selector estilo 'cards' (sin radio circular).
    Devuelve: 'gw' | 'evol' | 'seg'
    """
    st.markdown(
        """
        <style>
          /* estiliza botones "card" sólo dentro de este panel */
          .div-card button {
            border-radius: 14px !important;
            padding: 12px 12px !important;
            text-align: left !important;
            white-space: pre-line !important;
            border: 1px solid rgba(0,0,0,0.12) !important;
          }
          .div-card button:hover {
            border-color: rgba(0,0,0,0.25) !important;
          }
          .div-card-active button {
            border-color: rgba(255,140,0,0.65) !important;
            box-shadow: 0 0 0 3px rgba(255,140,0,0.12) !important;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )

    if "div_panel" not in st.session_state:
        st.session_state["div_panel"] = "gw"

    c1, c2, c3 = st.columns(3, gap="large")

    def render_card(col, key: str, title: str, subtitle: str, emoji: str) -> None:
        active = st.session_state.get("div_panel") == key
        cls = "div-card div-card-active" if active else "div-card"
        with col:
            st.markdown(f'<div class="{cls}">', unsafe_allow_html=True)
            clicked = st.button(f"{emoji}  {title}\n{subtitle}", key=f"divsel_{key}", use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)
            if clicked:
                st.session_state["div_panel"] = key

    render_card(c1, "gw", "Geraldine Weiss", "Bandas de valoración por yield", "📈")
    render_card(c2, "evol", "Evolución del dividendo", "Dividendo anual + CAGR", "💵")
    render_card(c3, "seg", "Seguridad del dividendo", "FCF vs dividendos + payout", "🛡️")

    return str(st.session_state.get("div_panel") or "gw")


def _render_dividend_chart_evolution(ticker: str) -> None:
    divs = _yf_dividends(ticker)
    annual = _annual_dividends_5y(divs)

    if annual.empty:
        st.warning("No hay datos suficientes de dividendos para este ticker.")
        return

    cagr = _cagr_from_annual_divs(annual)
    title = f"📌 CAGR {cagr:.2f}% anual (últimos {YEARS_BACK} años)" if cagr is not None else "📌 CAGR no disponible"

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=annual.index,
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
        height=450,
        margin=dict(l=30, r=30, t=60, b=30),
    )
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Ver tabla anual", expanded=False):
        st.dataframe(
            pd.DataFrame({"Año": annual.index.astype(int), "Dividendo anual ($)": annual.values.round(4)}),
            use_container_width=True,
            hide_index=True,
        )


def _render_dividend_chart_safety(ticker: str) -> None:
    cf = _yf_cashflow_annual(ticker)
    if cf.empty:
        st.warning("No hay datos de cashflow disponibles para este ticker.")
        return

    fcf_col, div_col = "Free Cash Flow", "Cash Dividends Paid"
    if fcf_col not in cf.columns or div_col not in cf.columns:
        st.warning("No se encontraron columnas de FCF o Dividendos en el cash-flow (yfinance).")
        return

    fcf = pd.to_numeric(cf[fcf_col], errors="coerce")
    div_paid = pd.to_numeric(cf[div_col], errors="coerce").abs()

    df = pd.DataFrame({"FCF": fcf, "Dividendos Pagados": div_paid}).dropna()
    if df.empty:
        st.warning("No hay datos suficientes para calcular la sostenibilidad del dividendo.")
        return

    df["FCF Payout (%)"] = (df["Dividendos Pagados"] / df["FCF"].replace(0, pd.NA)) * 100

    fig = go.Figure()
    fig.add_trace(go.Bar(x=df.index, y=df["FCF"], name="FCF", text=df["FCF"].round(0), textposition="outside"))
    fig.add_trace(
        go.Bar(
            x=df.index,
            y=df["Dividendos Pagados"],
            name="Dividendos Pagados",
            text=df["Dividendos Pagados"].round(0),
            textposition="outside",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["FCF Payout (%)"],
            name="FCF Payout (%)",
            mode="lines+markers+text",
            yaxis="y2",
            text=[f"{v:.0f}%" if pd.notna(v) else "" for v in df["FCF Payout (%)"]],
            textposition="top right",
        )
    )
    fig.update_layout(
        title=f"FCF vs Dividendos Pagados y FCF Payout (últimos {YEARS_BACK} años)",
        xaxis_title="Año fiscal",
        yaxis_title="USD",
        yaxis2=dict(title="FCF Payout (%)", overlaying="y", side="right"),
        barmode="group",
        height=500,
        margin=dict(l=30, r=30, t=60, b=30),
    )
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Ver datos", expanded=False):
        st.dataframe(df.reset_index().rename(columns={"index": "Año"}), use_container_width=True, hide_index=True)


def _render_dividend_chart_gw(ticker: str) -> None:
    price = _yf_history_5y(ticker)
    divs = _yf_dividends(ticker)
    annual = _annual_dividends_5y(divs)

    if price.empty or annual.empty:
        st.warning("No hay datos suficientes para calcular el Método Geraldine Weiss.")
        return

    cagr = _cagr_from_annual_divs(annual)
    current_year = datetime.today().year

    def div_for_year(year: int) -> float | None:
        if year in annual.index:
            return _safe_float(annual.loc[year])
        if year == current_year and cagr is not None:
            prev_year = year - 1
            if prev_year in annual.index:
                base = _safe_float(annual.loc[prev_year])
                if base is not None:
                    return base * (1 + cagr / 100)
        return None

    monthly = price[["Close"]].resample("M").last().dropna().reset_index()
    monthly["Año"] = monthly["date"].dt.year
    monthly["Dividendo Anual"] = monthly["Año"].apply(lambda y: div_for_year(int(y)))
    monthly = monthly.dropna(subset=["Dividendo Anual"])
    if monthly.empty:
        st.warning("No fue posible construir la serie mensual para Geraldine Weiss.")
        return

    monthly["Yield"] = monthly["Dividendo Anual"] / monthly["Close"]
    y_min = float(monthly["Yield"].min())
    y_max = float(monthly["Yield"].max())

    info = _yf_info(ticker)
    current_price = _safe_float(info.get("currentPrice")) or _safe_float(price["Close"].iloc[-1])

    last_year = int(monthly["Año"].max())
    last_div = _safe_float(monthly[monthly["Año"] == last_year]["Dividendo Anual"].iloc[-1]) or 0.0

    kcols = st.columns(6, gap="large")
    kcols[0].metric("Precio actual", f"${current_price:.2f}" if current_price else "N/D")
    kcols[1].metric("Dividendo anual", f"${last_div:.2f}")
    kcols[2].metric("CAGR 5y", f"{cagr:.2f}%" if cagr is not None else "N/D")
    kcols[3].metric("Yield máx", f"{y_max:.2%}")
    kcols[4].metric("Yield mín", f"{y_min:.2%}")
    kcols[5].metric("Infravalorado", f"${(last_div / y_max):.2f}" if y_max else "N/D")

    years = sorted(monthly["Año"].unique().tolist())
    x_sobre, y_sobre, x_infra, y_infra = [], [], [], []
    last_date = price.index.max()

    for yr in years:
        dv = div_for_year(int(yr))
        if dv is None:
            continue
        start = pd.to_datetime(f"{int(yr)}-01-01")
        end = pd.to_datetime(f"{int(yr) + 1}-01-01")
        if end > last_date:
            end = last_date
        x_sobre.extend([start, end])
        y_sobre.extend([dv / y_min, dv / y_min])
        x_infra.extend([start, end])
        y_infra.extend([dv / y_max, dv / y_max])

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=price.index, y=price["Close"], mode="lines", name="Precio"))
    fig.add_trace(go.Scatter(x=x_sobre, y=y_sobre, mode="lines", name="Sobrevalorado", line=dict(dash="dot")))
    fig.add_trace(go.Scatter(x=x_infra, y=y_infra, mode="lines", name="Infravalorado", line=dict(dash="dot")))

    if current_price is not None:
        fig.add_trace(
            go.Scatter(
                x=[price.index[-1]],
                y=[current_price],
                mode="markers+text",
                name="Precio actual",
                text=[f"${current_price:.2f}"],
                textposition="top center",
            )
        )

    fig.update_layout(
        title=f"Bandas de Geraldine Weiss (últimos {YEARS_BACK} años) — {ticker}",
        xaxis_title="Fecha",
        yaxis_title="Precio ($)",
        height=520,
        margin=dict(l=20, r=20, t=60, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Ver datos (mensual)", expanded=False):
        show = monthly.rename(columns={"Close": "Precio"}).copy()
        show["Yield"] = (show["Yield"] * 100).round(2)
        st.dataframe(show, use_container_width=True, hide_index=True)


def _render_dividend_tab(ticker: str) -> None:
    st.markdown(f"#### Dividendos — últimos {YEARS_BACK} años")

    choice = _dividend_panel_selector()
    st.markdown("---")

    if choice == "gw":
        _render_dividend_chart_gw(ticker)
    elif choice == "evol":
        _render_dividend_chart_evolution(ticker)
    else:
        _render_dividend_chart_safety(ticker)


# =========================================================
# Página principal
# =========================================================
def page_analysis() -> None:
    DAILY_LIMIT = 3
    user_email = _get_user_email()
    admin = is_admin()

    # -----------------------------
    # CSS base (mantener estilo validado + cards selector)
    # -----------------------------
    st.markdown(
        """
        <style>
          div[data-testid="stAppViewContainer"] section.main div.block-container {
            padding-top: 0.5rem !important;
            padding-left: 2.0rem !important;
            padding-right: 2.0rem !important;
            max-width: 100% !important;
          }

          div[data-testid="stForm"] { border: none !important; padding: 0 !important; margin: 0 !important; }

          div[data-testid="stTextInput"] > div { border-radius: 12px !important; }

          .kpi-card {
            background: transparent;
            border: none;
            border-radius: 14px;
            padding: 14px 14px 12px 14px;
            min-height: 86px;
          }
          .kpi-label { font-size: 0.78rem; color: rgba(0,0,0,0.55); margin-bottom: 6px; }
          .kpi-value { font-size: 1.55rem; font-weight: 700; line-height: 1.1; }

          .main-card { background: transparent; border: none; border-radius: 16px; padding: 0; }

          h2, h3 { margin-bottom: 0.25rem !important; }
          [data-testid="stCaptionContainer"] { margin-top: -6px !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # -----------------------------
    # SIDEBAR
    # -----------------------------
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

    # -----------------------------
    # BUSCADOR (arriba)
    # -----------------------------
    top_left, _ = st.columns([1.15, 0.85], gap="large")
    with top_left:
        with st.form("main_search", clear_on_submit=False, border=False):
            ticker_in = st.text_input(
                label="",
                value=(st.session_state.get("ticker") or "AAPL"),
                placeholder="Buscar ticker (ej: AAPL, MSFT, PEP)...",
                key="ticker_main",
            ).strip().upper()
            submitted = st.form_submit_button("🔎 Buscar")

        if submitted and ticker_in:
            st.session_state["ticker"] = ticker_in
            st.session_state["do_search"] = True
            st.rerun()

    # -----------------------------
    # Control de refresh (sin romper UI al cambiar selector)
    # -----------------------------
    ticker = (st.session_state.get("ticker") or "").strip().upper()
    did_search = bool(st.session_state.pop("do_search", False))

    if not ticker:
        st.info("Ingresa un ticker en el buscador para cargar datos.")
        return

    last_loaded = st.session_state.get("last_loaded_ticker")
    has_loaded = bool(st.session_state.get("has_loaded_data", False))

    # OJO: ya NO retornamos si did_search=False
    needs_refresh = bool(did_search) or (not has_loaded) or (last_loaded != ticker)

    # Consume SOLO cuando el usuario presiona Buscar (did_search)
    if needs_refresh and did_search and (not admin) and user_email:
        ok, rem_after = consume_search(user_email, DAILY_LIMIT, cost=1)
        if not ok:
            st.sidebar.error("🚫 Búsquedas diarias alcanzadas. Vuelve mañana.")
            return
        st.sidebar.info(f"🔎 Búsquedas restantes hoy: {rem_after}/{DAILY_LIMIT}")

    # -----------------------------
    # DATA (servicios actuales)
    # -----------------------------
    price = get_price_data(ticker) or {}
    profile = get_profile_data(ticker) or {}
    raw = profile.get("raw") if isinstance(profile, dict) else {}
    stats = get_key_stats(ticker) or {}
    divk = get_dividend_kpis(ticker) or {}

    st.session_state["last_loaded_ticker"] = ticker
    st.session_state["has_loaded_data"] = True

    company_name = raw.get("longName") or raw.get("shortName") or profile.get("shortName") or ticker
    last_price = price.get("last_price")
    currency = price.get("currency") or ""
    delta_txt, pct_val = _fmt_delta(price.get("net_change"), price.get("pct_change"))

    website = (profile.get("website") or raw.get("website") or "") if isinstance(profile, dict) else ""
    logos = logo_candidates(website) if website else []
    logo_url = next((u for u in logos if isinstance(u, str) and u.startswith(("http://", "https://"))), "")

    # -----------------------------
    # BLOQUE SUPERIOR
    # -----------------------------
    left, right = st.columns([1.15, 0.85], gap="large")

    with left:
        st.markdown('<div class="main-card">', unsafe_allow_html=True)

        a1, a2 = st.columns([0.10, 0.90], gap="small", vertical_alignment="center")
        with a1:
            if logo_url:
                st.image(logo_url, width=44)
        with a2:
            st.markdown(f"### {ticker} — {company_name}")

        st.markdown(f"## {_fmt_price(last_price, currency)}")

        if delta_txt:
            color = "#16a34a" if (pct_val is not None and pct_val >= 0) else "#dc2626"
            st.markdown(
                f"<div style='margin-top:-6px; font-size:0.95rem; color:{color}; font-weight:600;'>{delta_txt}</div>",
                unsafe_allow_html=True,
            )

        st.markdown("</div>", unsafe_allow_html=True)

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

        with r2c1:
            _kpi_card("Target 1Y", _fmt_kpi(stats.get("target_1y")))
        with r2c2:
            _kpi_card("Dividend Yield", _fmt_kpi(divk.get("div_yield"), suffix="%", decimals=2))
        with r2c3:
            _kpi_card("Forward Div. Yield", _fmt_kpi(divk.get("fwd_div_yield"), suffix="%", decimals=2))

    st.write("")

    # -----------------------------
    # TABS
    # -----------------------------
    tabs = st.tabs(
        [
            "Dividendos",
            "Múltiplos",
            "Balance",
            "Estado de Resultados",
            "Estado de Flujo de Efectivo",
            "Otro",
        ]
    )

    with tabs[0]:
        _render_dividend_tab(ticker)

    with tabs[1]:
        st.info("Aquí irán los gráficos de Múltiplos (pendiente).")
    with tabs[2]:
        st.info("Aquí irán los gráficos de Balance (pendiente).")
    with tabs[3]:
        st.info("Aquí irán los gráficos de Estado de Resultados (pendiente).")
    with tabs[4]:
        st.info("Aquí irán los gráficos de Flujo de Efectivo (pendiente).")
    with tabs[5]:
        st.info("Sección 'Otro' (pendiente).")
