# src/pages/analysis.py
from __future__ import annotations

import math
from datetime import datetime

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
    get_dividend_kpis,  # mantiene tu versión actual (si existe en tu repo)
)
from src.services.logos import logo_candidates
from src.services.usage_limits import consume_search, remaining_searches


# =========================================================
# Constantes (estandarización)
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


def _fmt_price(x, currency: str) -> str:
    if not isinstance(x, (int, float)) or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "N/D"
    s = f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} {currency}".strip()


def _fmt_delta(net, pct) -> tuple[str | None, float | None]:
    if isinstance(net, (int, float)) and isinstance(pct, (int, float)):
        return f"{net:+.2f} ({pct:+.2f}%)", float(pct)
    return None, None


def _fmt_kpi(x, suffix: str = "", decimals: int = 2) -> str:
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


# =========================================================
# Dividendos: carga y cálculos (cache 30 días)
# =========================================================
@st.cache_data(ttl=DIVIDENDS_CACHE_TTL_SECONDS, show_spinner=False)
def _load_dividend_inputs(ticker: str, years: int) -> dict:
    """
    Datos que cambian como mucho trimestralmente -> cache 30 días.
    OJO: al cambiar entre gráficos, esto se re-ejecuta pero pega al cache (no consume API).
    """
    t = yf.Ticker(ticker)

    # Precio diario últimos N años
    price_daily = t.history(period=f"{years}y", interval="1d", auto_adjust=False)
    if isinstance(price_daily, pd.DataFrame) and not price_daily.empty:
        if "Close" not in price_daily.columns:
            # fallback típico por si viene distinto
            close_cols = [c for c in price_daily.columns if str(c).lower() == "close"]
            if close_cols:
                price_daily["Close"] = price_daily[close_cols[0]]
        price_daily = price_daily[["Close"]].dropna()
    else:
        price_daily = pd.DataFrame(columns=["Close"])

    # Dividendos (serie completa; filtraremos a 5y)
    dividends = t.dividends
    if dividends is None or not isinstance(dividends, pd.Series):
        dividends = pd.Series(dtype=float)
    else:
        dividends = dividends.dropna().astype(float)

    # Cashflow (normalmente anual; yfinance suele traer 4 años)
    cashflow = t.cashflow
    if cashflow is None or not isinstance(cashflow, pd.DataFrame):
        cashflow = pd.DataFrame()

    return {"price_daily": price_daily, "dividends": dividends, "cashflow": cashflow}


def _annual_dividends_last_years(dividends: pd.Series, years: int) -> pd.Series:
    if dividends.empty:
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


def _cagr_from_annual(annual: pd.Series) -> float | None:
    """
    CAGR usando primer año vs último año del rango (ya filtrado a N años).
    """
    if annual is None or len(annual) < 2:
        return None
    first = float(annual.iloc[0])
    last = float(annual.iloc[-1])
    n = (int(annual.index[-1]) - int(annual.index[0]))
    if first <= 0 or n <= 0:
        return None
    return ((last / first) ** (1 / n) - 1) * 100


# =========================================================
# Gráficos Dividendos (últimos 5 años)
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
        st.dataframe(
            pd.DataFrame({"Año": annual.index, "Dividendo anual": annual.values}).set_index("Año"),
            use_container_width=True,
        )


def _pick_cashflow_cols(df: pd.DataFrame) -> tuple[str | None, str | None]:
    """
    Intenta mapear columnas típicas de yfinance cashflow.
    """
    if df is None or df.empty:
        return None, None

    cols = set(df.columns)

    fcf_candidates = [
        "Free Cash Flow",
        "FreeCashFlow",
        "freeCashFlow",
    ]
    div_candidates = [
        "Cash Dividends Paid",
        "CashDividendsPaid",
        "cashDividendsPaid",
        "Dividends Paid",
        "DividendsPaid",
    ]

    fcf_col = next((c for c in fcf_candidates if c in cols), None)
    div_col = next((c for c in div_candidates if c in cols), None)

    # Si no existe FCF, intentar aproximar con OCF - CapEx
    if fcf_col is None:
        ocf_candidates = ["Total Cash From Operating Activities", "Operating Cash Flow", "OperatingCashFlow"]
        capex_candidates = ["Capital Expenditures", "CapitalExpenditures", "capex"]
        ocf = next((c for c in ocf_candidates if c in cols), None)
        capex = next((c for c in capex_candidates if c in cols), None)
        if ocf and capex:
            # creamos columna temporal en copia, pero fuera es mejor computar directo en chart
            fcf_col = "__FCF_DERIVED__"
    return fcf_col, div_col


def _plot_dividend_safety(ticker: str, cashflow: pd.DataFrame) -> None:
    if cashflow is None or cashflow.empty:
        st.warning("No hay datos de cashflow suficientes para graficar seguridad del dividendo.")
        return

    # yfinance suele traer columnas por periodo (datetime) y filas por concepto.
    df = cashflow.transpose().copy()
    df.index = pd.to_datetime(df.index, errors="coerce")
    # Evita crash: filtrar filas con índice NaT en lugar de usar dropna(subset=...)
    df = df.loc[df.index.notna()]
    df["Year"] = df.index.year
    df = df.set_index("Year")

    fcf_col, div_col = _pick_cashflow_cols(df)
    if div_col is None:
        st.warning("No se encontró la columna de dividendos pagados en cashflow.")
        return

    # Seleccionar últimos YEARS años disponibles
    df = df.sort_index()
    df = df.tail(YEARS)

    # FCF: directo o derivado
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


def _plot_geraldine_weiss(ticker: str, price_daily: pd.DataFrame, dividends: pd.Series) -> None:
    """
    Bandas GW: usa rendimientos (yield) min/max observados en el rango (últimos 5 años).
    """
    if price_daily is None or price_daily.empty:
        st.warning("No hay precio diario suficiente para Geraldine Weiss.")
        return

    annual = _annual_dividends_last_years(dividends, YEARS)
    if annual.empty:
        st.warning("No hay dividendos suficientes para Geraldine Weiss (últimos 5 años).")
        return

    cagr = _cagr_from_annual(annual)

    # Mensual: último precio del mes
    monthly = price_daily.resample("M").last().copy()
    monthly["Year"] = monthly.index.year

    current_year = datetime.now().year
    last_year = int(annual.index.max())
    last_div = float(annual.loc[last_year])

    def _adj_div(year: int) -> float | None:
        if year in annual.index:
            return float(annual.loc[year])
        # Proyección simple para año actual si no está cerrado
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

    # Bandas (precio teórico)
    monthly["Sobrevalorado"] = monthly["DivAnual"] / y_min if y_min > 0 else None
    monthly["Infravalorado"] = monthly["DivAnual"] / y_max if y_max > 0 else None

    # Plot: precio diario + bandas mensuales (step-like)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=price_daily.index, y=price_daily["Close"], mode="lines", name="Precio (diario)"))
    fig.add_trace(go.Scatter(x=monthly.index, y=monthly["Sobrevalorado"], mode="lines", name="Banda sobrevalorado", line=dict(dash="dot")))
    fig.add_trace(go.Scatter(x=monthly.index, y=monthly["Infravalorado"], mode="lines", name="Banda infravalorado", line=dict(dash="dot")))

    # Precio actual (último close)
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

    # métricas rápidas
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
# Página principal
# =========================================================
def page_analysis() -> None:
    DAILY_LIMIT = 3
    user_email = _get_user_email()
    admin = is_admin()

    # -----------------------------
    # CSS (incluye tabs estilo “pills” + bordes limpio)
    # -----------------------------
    # Reemplaza el bloque st.markdown(...) que contiene CSS global por ESTE bloque:
    st.markdown(
        """
        <style>
          /* Contenedor principal */
          div[data-testid="stAppViewContainer"] section.main div.block-container {
            padding-top: 0.35rem !important;
            padding-left: 2.0rem !important;
            padding-right: 2.0rem !important;
            max-width: 100% !important;
          }
    
          /* Quitar borde de forms */
          div[data-testid="stForm"] {
            border: none !important;
            padding: 0 !important;
            margin: 0 !important;
          }
    
          /* Inputs más limpios */
          div[data-testid="stTextInput"] > div {
            border-radius: 12px !important;
          }
    
          /* KPI cards: rectangulares y sin borde inferior */
          .kpi-card {
            background: transparent;
            border: 1px solid rgba(0,0,0,0.06); /* poner 'none' si quieres sin marco */
            border-radius: 0 !important;
            padding: 14px 14px 12px 14px;
            min-height: 86px;
            box-shadow: none !important;
            border-bottom: none !important;
          }
          .kpi-label {
            font-size: 0.78rem;
            color: rgba(0,0,0,0.55);
            margin-bottom: 6px;
          }
          .kpi-value {
            font-size: 1.55rem;
            font-weight: 700;
            line-height: 1.1;
          }
    
          /* Bloque principal */
          .main-card {
            background: transparent;
            border: none;
            border-radius: 0 !important;
            padding: 0;
          }
    
          /* Títulos compactos */
          h2, h3 { margin-bottom: 0.25rem !important; }
          [data-testid="stCaptionContainer"] { margin-top: -6px !important; }
    
          /* ---- Tabs: simple tab style (no pills) ---- */
          div[data-testid="stTabs"] button[role="tab"] {
            border-radius: 6px !important;
            padding: 8px 14px !important;
            margin-right: 6px !important;
            border: none !important;
            background: transparent !important;
            box-shadow: none !important;
            border-bottom: 2px solid transparent !important;
          }
          div[data-testid="stTabs"] button[role="tab"][aria-selected="true"]{
            border-bottom: 3px solid #ff7a18 !important;
            font-weight: 700 !important;
            background: transparent !important;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # -----------------------------
    # Sidebar (controles + límites) — FIX duplicado: usamos un solo box
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
    # Buscador (Enter) — sin botón y sin warnings de label vacío
    # -----------------------------
    if "ticker" not in st.session_state:
        st.session_state["ticker"] = "AAPL"
    if "ticker_main" not in st.session_state:
        st.session_state["ticker_main"] = st.session_state.get("ticker", "AAPL")
    if "loaded_ticker" not in st.session_state:
        st.session_state["loaded_ticker"] = ""

    def _submit_search_enter() -> None:
        val = (st.session_state.get("ticker_main") or "").strip().upper()
        if val:
            st.session_state["ticker"] = val
            st.session_state["do_search"] = True

    # input ancho
    st.text_input(
        "Ticker",
        key="ticker_main",
        label_visibility="collapsed",
        placeholder="Buscar ticker (ej: AAPL, MSFT, PEP)...",
        on_change=_submit_search_enter,  # Enter / perder foco
    )

    ticker = (st.session_state.get("ticker") or "").strip().upper()
    did_search = bool(st.session_state.pop("do_search", False))

    if not ticker:
        st.info("Ingresa un ticker en el buscador para cargar datos.")
        return

    # Gate: solo consumir y “refrescar” cuando presionan Enter (do_search)
    # pero permitir navegar tabs sin reiniciar ni pedir re-ingreso
    if not did_search:
        # Si ya cargamos este ticker alguna vez, dejamos ver todo sin consumir
        if st.session_state.get("loaded_ticker") != ticker:
            st.caption("Ticker cargado. Presiona **Enter** para actualizar datos.")
            return

    # Si presionó Enter, consumir límite (no admin)
    if did_search:
        if (not admin) and user_email:
            ok, rem_after = consume_search(user_email, DAILY_LIMIT, cost=1)
            if not ok:
                # Reutiliza el mismo box (no duplica)
                with st.sidebar:
                    limit_box.error("🚫 Búsquedas diarias alcanzadas. Vuelve mañana.")
                return
            with st.sidebar:
                limit_box.info(f"🔎 Búsquedas restantes hoy: {rem_after}/{DAILY_LIMIT}")

    # (el resto del archivo continúa igual: carga de datos, creación de tabs/st.tabs, etc.)
