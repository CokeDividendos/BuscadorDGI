# src/pages/analysis.py
from __future__ import annotations

import streamlit as st

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import yfinance as yf

PRIMARY_ORANGE = "#f97316"
PRIMARY_BLUE = "#0ea5e9"
PRIMARY_PINK = "#ec4899"


@st.cache_data(ttl=60 * 60, show_spinner=False)
def _load_dividend_inputs(ticker: str):
    """
    Carga base para dividendos. Cacheado para no reventar yfinance.
    Retorna: dividends (Series), cashflow (DataFrame), price_daily (DataFrame)
    """
    t = yf.Ticker(ticker)
    dividends = t.dividends.copy()
    cashflow = t.cashflow.copy()
    price_daily = t.history(period="max", interval="1d", auto_adjust=False).copy()
    return dividends, cashflow, price_daily


def _annual_dividends(dividends: pd.Series, price_daily: pd.DataFrame) -> pd.Series:
    if dividends is None or dividends.empty:
        return pd.Series(dtype=float)

    annual = dividends.resample("Y").sum().astype(float).dropna()
    annual.index = annual.index.year

    if price_daily is not None and not price_daily.empty:
        start_year, end_year = price_daily.index[[0, -1]].year
        annual = annual.loc[start_year:end_year]

    return annual


def _div_cagr_from_annual(annual: pd.Series, years: int = 5) -> float | None:
    """
    CAGR de dividendos basado en dividendos anuales.
    Toma el último año COMPLETO (current_year-1) si existe.
    """
    if annual is None or annual.empty:
        return None

    current_year = pd.Timestamp.today().year
    last_full_year = current_year - 1

    # necesitamos (years + 1) puntos: ej 5y => 6 años de datos
    available = annual.dropna().sort_index()
    if last_full_year in available.index:
        available = available.loc[:last_full_year]

    if len(available) < (years + 1):
        return None

    window = available.iloc[-(years + 1):]
    first = float(window.iloc[0])
    last = float(window.iloc[-1])
    if first <= 0 or last <= 0:
        return None

    cagr = ((last / first) ** (1 / years) - 1) * 100.0
    return float(cagr)


def _build_dividend_evolution_chart(annual: pd.Series, cagr_5y: float | None) -> go.Figure:
    title = "Evolución del dividendo anual"
    if cagr_5y is not None:
        title = f"Evolución del dividendo anual — CAGR 5Y: {cagr_5y:.2f}%"

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=annual.index.tolist(),
            y=annual.values.tolist(),
            name="Dividendo Anual ($)",
            marker_color=PRIMARY_ORANGE,
            text=[f"${v:.2f}" for v in annual.values],
            textposition="outside",
        )
    )
    fig.update_layout(
        title=title,
        xaxis_title="Año",
        yaxis_title="Dividendo ($)",
        height=520,
        margin=dict(l=20, r=20, t=70, b=30),
    )
    return fig


def _build_dividend_safety_chart(cashflow: pd.DataFrame) -> tuple[go.Figure | None, pd.DataFrame | None, str | None]:
    """
    Sostenibilidad: FCF vs Dividendos Pagados + FCF Payout (%)
    Retorna (fig, df_fcf, warning_msg)
    """
    if cashflow is None or cashflow.empty:
        return None, None, "No hay datos de cash-flow disponibles."

    try:
        cf = cashflow.transpose().copy()
        cf.index = cf.index.year

        fcf_col, div_col = "Free Cash Flow", "Cash Dividends Paid"
        if fcf_col not in cf.columns or div_col not in cf.columns:
            return None, None, "No se encontraron columnas de FCF o Dividendos en el cash-flow."

        fcf = pd.to_numeric(cf[fcf_col], errors="coerce")
        div_paid = pd.to_numeric(cf[div_col], errors="coerce").abs()

        df = pd.DataFrame({"FCF": fcf, "Dividendos Pagados": div_paid}).dropna()
        if df.empty:
            return None, None, "No hay datos suficientes para construir el gráfico de sostenibilidad."

        df["FCF Payout (%)"] = (df["Dividendos Pagados"] / df["FCF"]) * 100

        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=df.index,
                y=df["FCF"],
                name="FCF",
                marker_color=PRIMARY_ORANGE,
            )
        )
        fig.add_trace(
            go.Bar(
                x=df.index,
                y=df["Dividendos Pagados"],
                name="Dividendos Pagados",
                marker_color=PRIMARY_BLUE,
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["FCF Payout (%)"],
                name="FCF Payout (%)",
                mode="lines+markers",
                yaxis="y2",
                line=dict(color=PRIMARY_PINK),
            )
        )

        fig.update_layout(
            title="FCF vs Dividendos Pagados y FCF Payout Ratio",
            xaxis_title="Año",
            yaxis_title="USD",
            yaxis2=dict(title="FCF Payout (%)", overlaying="y", side="right"),
            barmode="group",
            height=560,
            margin=dict(l=20, r=20, t=70, b=30),
        )
        return fig, df, None

    except Exception as e:
        return None, None, f"No se pudo generar el gráfico de sostenibilidad: {e}"


def _build_geraldine_weiss_chart(
    price_daily: pd.DataFrame,
    annual: pd.Series,
    cagr_5y: float | None,
) -> tuple[go.Figure | None, dict | None, str | None]:
    """
    Bandas Geraldine Weiss (sobrevalorado / infravalorado) usando yields históricos.
    Retorna (fig, metrics_dict, warning_msg)
    """
    if price_daily is None or price_daily.empty or annual is None or annual.empty:
        return None, None, "No hay datos suficientes para calcular Geraldine Weiss."

    try:
        df = price_daily.copy()
        close_col = "Close" if "Close" in df.columns else None
        if close_col is None:
            return None, None, "No se encontró columna Close en el histórico."

        # mensual
        monthly = df[[close_col]].resample("M").last().reset_index()
        monthly.rename(columns={close_col: "Precio", "Date": "Fecha"}, inplace=True)
        monthly["Año"] = monthly["Date"].dt.year if "Date" in monthly.columns else monthly.iloc[:, 0].dt.year

        # map dividend anual por año
        div_map = annual.to_dict()
        current_year = pd.Timestamp.today().year

        def div_year(y: int) -> float | None:
            # si estamos en año corriente, estimar desde el último año completo con CAGR (si existe)
            if y == current_year and cagr_5y is not None and (y - 1) in div_map:
                return float(div_map[y - 1]) * (1 + cagr_5y / 100.0)
            return float(div_map.get(y)) if y in div_map else None

        monthly["Dividendo Anual"] = monthly["Año"].apply(div_year)
        monthly = monthly.dropna(subset=["Dividendo Anual", "Precio"])
        if monthly.empty:
            return None, None, "No hay datos suficientes (mensual) para calcular bandas."

        monthly["Yield"] = monthly["Dividendo Anual"] / monthly["Precio"]

        overall_yield_min = float(monthly["Yield"].min())
        overall_yield_max = float(monthly["Yield"].max())

        # bandas “teóricas” por cada fecha mensual según el div anual del año
        monthly["Precio Sobrevalorado"] = monthly["Dividendo Anual"] / overall_yield_min
        monthly["Precio Infravalorado"] = monthly["Dividendo Anual"] / overall_yield_max

        # para graficar escalonado por año (bandas planas por año)
        annual_years = sorted(monthly["Año"].unique())
        bands = []
        for y in annual_years:
            d = div_year(int(y))
            if d is None:
                continue
            bands.append(
                {
                    "Año": int(y),
                    "Dividendo Anual": float(d),
                    "Precio Sobrevalorado": float(d) / overall_yield_min,
                    "Precio Infravalorado": float(d) / overall_yield_max,
                }
            )
        df_annual = pd.DataFrame(bands)
        if df_annual.empty:
            return None, None, "No se pudo construir la tabla anual para bandas."

        # líneas escalonadas
        x_sobre, y_sobre, x_infra, y_infra = [], [], [], []
        for i, row in df_annual.iterrows():
            year = int(row["Año"])
            start = pd.to_datetime(f"{year}-01-01")
            end = pd.to_datetime(f"{year+1}-01-01") if year != int(df_annual["Año"].max()) else price_daily.index[-1]
            x_sobre.extend([start, end])
            y_sobre.extend([row["Precio Sobrevalorado"], row["Precio Sobrevalorado"]])
            x_infra.extend([start, end])
            y_infra.extend([row["Precio Infravalorado"], row["Precio Infravalorado"]])

        current_price = float(price_daily["Close"].iloc[-1])
        last_year = int(df_annual["Año"].max())
        last_div = float(df_annual[df_annual["Año"] == last_year]["Dividendo Anual"].iloc[-1])

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=price_daily.index,
                y=price_daily["Close"],
                mode="lines",
                name="Precio Histórico",
                line=dict(color=PRIMARY_PINK),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=x_sobre,
                y=y_sobre,
                mode="lines",
                name="Banda Sobrevalorado",
                line=dict(color=PRIMARY_ORANGE, dash="dot"),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=x_infra,
                y=y_infra,
                mode="lines",
                name="Banda Infravalorado",
                line=dict(color=PRIMARY_BLUE, dash="dot"),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=[price_daily.index[-1]],
                y=[current_price],
                mode="markers+text",
                name="Precio Actual",
                marker=dict(color=PRIMARY_PINK, size=10),
                text=[f"${current_price:.2f}"],
                textposition="top center",
            )
        )
        fig.update_layout(
            title="Geraldine Weiss — Bandas de valoración histórica (yield)",
            xaxis_title="Fecha",
            yaxis_title="Precio ($)",
            height=560,
            margin=dict(l=20, r=20, t=70, b=30),
        )

        metrics = {
            "Precio Actual": current_price,
            "Dividendo Anual": last_div,
            "CAGR 5Y": cagr_5y,
            "Yield Máximo": overall_yield_max,
            "Yield Mínimo": overall_yield_min,
            "Sobrevalorado": last_div / overall_yield_min,
            "Infravalorado": last_div / overall_yield_max,
        }
        return fig, metrics, None

    except Exception as e:
        return None, None, f"No se pudo generar Geraldine Weiss: {e}"


from src.services.usage_limits import remaining_searches, consume_search
from src.services.finance_data import (
    get_price_data,
    get_profile_data,
    get_key_stats,
    get_dividend_kpis,
)
from src.services.logos import logo_candidates
from src.auth import is_admin
from src.services.cache_store import cache_clear_all


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


def _submit_search_from_input() -> None:
    """Se dispara al presionar Enter en el input (on_change)."""
    raw = (st.session_state.get("ticker_main") or "").strip().upper()
    if not raw:
        return
    st.session_state["ticker"] = raw
    st.session_state["do_search"] = True


def page_analysis() -> None:
    DAILY_LIMIT = 3
    user_email = _get_user_email()
    admin = is_admin()

    # -----------------------------
    # CSS global (sin bordes + menos padding arriba + cards parejas)
    # -----------------------------
    st.markdown(
        """
        <style>
          /* =========================================================
             LAYOUT GENERAL — eliminar aire arriba y usar todo el ancho
             ========================================================= */

          div[data-testid="stAppViewContainer"] section.main div.block-container {
            padding-top: 0rem !important;
            padding-left: 2.0rem !important;
            padding-right: 2.0rem !important;
            max-width: 100% !important;
          }

          section.main { padding-top: 0rem !important; }

          /* Reduce margen del primer bloque */
          div[data-testid="stVerticalBlock"] > div:first-child {
            margin-top: -0.75rem !important;
          }

          /* Oculta header superior (responsable del “aire fantasma”) */
          header[data-testid="stHeader"] {
            height: 0 !important;
            visibility: hidden;
          }
          div[data-testid="stToolbar"] { height: 0 !important; }

          /* Mantener sidebar “siempre disponible”: ocultar botón de colapsar */
          [data-testid="collapsedControl"] { display: none !important; }

          /* =========================================================
             FORMS, INPUTS Y CONTENEDORES — sin bordes ni marcos
             ========================================================= */

          div[data-testid="stForm"] {
            border: none !important;
            padding: 0 !important;
            margin: 0 !important;
          }

          /* input limpio */
          div[data-testid="stTextInput"] > div {
            border-radius: 12px !important;
            border: none !important;
          }

          /* =========================================================
             BLOQUE NOMBRE / PRECIO
             ========================================================= */
          .main-card {
            background: transparent;
            border: none !important;
            border-radius: 16px;
            padding: 0;
          }

          /* =========================================================
             KPI CARDS — tamaño uniforme, sin borde
             ========================================================= */
          .kpi-card {
            background: transparent;
            border: none !important;
            border-radius: 14px;
            padding: 14px 14px 12px 14px;
            min-height: 86px;
            display: flex;
            flex-direction: column;
            justify-content: center;
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

          h2, h3 { margin-bottom: 0.25rem !important; }
          [data-testid="stCaptionContainer"] { margin-top: -6px !important; }
          div[data-testid="stTabs"] { margin-top: 0.75rem !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # -----------------------------
    # SIDEBAR (controles)
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
    # BUSCADOR (ENTER para buscar, sin botón)
    # -----------------------------
    def _submit_search() -> None:
        raw = (st.session_state.get("ticker_main") or "").strip().upper()
        if raw:
            st.session_state["ticker"] = raw
            st.session_state["do_search"] = True
    
    top_left, _top_right = st.columns([1.15, 0.85], gap="large")
    with top_left:
        st.text_input(
            "Ticker",
            value=(st.session_state.get("ticker") or "AAPL"),
            placeholder="Buscar ticker (ej: AAPL, MSFT, PEP)...",
            key="ticker_main",
            label_visibility="collapsed",
            on_change=_submit_search,  # <-- Enter dispara la búsqueda
        )
    
    # -----------------------------
    # Lógica de “solo actualizar cuando se presiona Enter”
    # -----------------------------
    ticker = (st.session_state.get("ticker") or "").strip().upper()
    did_search = bool(st.session_state.pop("do_search", False))

    if not ticker:
        st.info("Ingresa un ticker en el buscador para cargar datos.")
        return

    if not did_search:
        st.caption("Ticker cargado. Presiona **Enter** para actualizar datos.")
        return

    # Consume SOLO si NO es admin
    if (not admin) and user_email:
        ok, rem_after = consume_search(user_email, DAILY_LIMIT, cost=1)
        if not ok:
            st.sidebar.error("🚫 Búsquedas diarias alcanzadas. Vuelve mañana.")
            return
        limit_box.info(f"🔎 Búsquedas restantes hoy: {rem_after}/{DAILY_LIMIT}")

    # -----------------------------
    # DATA
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

    # -----------------------------
    # BLOQUE SUPERIOR
    # -----------------------------
    left, right = st.columns([1.15, 0.85], gap="large")

    with left:
        st.markdown('<div class="main-card">', unsafe_allow_html=True)

        # Logo (izq) ocupa visualmente 2 filas; Info (der) con 2 filas: arriba nombre, abajo precio+variación
        c_logo, c_info = st.columns([0.12, 0.88], gap="medium", vertical_alignment="center")
        
        with c_logo:
            if logo_url:
                st.image(logo_url, width=52)  # un poco más grande para que se note el "rowspan"
            else:
                st.write("")  # mantiene el espacio si no hay logo
        
        with c_info:
            # Fila superior: Ticker + Nombre
            st.markdown(f"### {ticker} — {company_name}")
            st.markdown(f"## {_fmt_price(last_price, currency)}")
            if delta_txt:
                color = "#16a34a" if (pct_val is not None and pct_val >= 0) else "#dc2626"
                st.markdown(
                    f"<div style='text-align:left; margin-top:10px; font-size:0.95rem; color:{color}; font-weight:600;'>{delta_txt}</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.write("")

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
        # ==========================
        # Dividendos — Opción B (Galería: eliges 1 y se expande)
        # ==========================
        st.markdown("### Dividendos")
    
        view = st.radio(
            "Selecciona un gráfico",
            ["Geraldine Weiss", "Evolución del dividendo", "Seguridad del dividendo"],
            horizontal=True,
            key="div_view_selector",
        )
    
        # Cargar inputs base (cacheados)
        dividends_s, cashflow_df, price_daily_df = _load_dividend_inputs(ticker)
        annual = _annual_dividends(dividends_s, price_daily_df)
        cagr_5y = _div_cagr_from_annual(annual, years=5)
    
        if view == "Evolución del dividendo":
            with st.container():
                if annual.empty:
                    st.warning("No hay dividendos suficientes para construir la evolución anual.")
                else:
                    fig = _build_dividend_evolution_chart(annual, cagr_5y)
                    st.plotly_chart(fig, use_container_width=True, key=f"div_evol_{ticker}")
    
                    # tabla resumen compacta
                    st.markdown("#### Resumen por año")
                    st.dataframe(
                        pd.DataFrame({"Dividendo Anual ($)": annual.round(4)}),
                        use_container_width=True,
                    )
    
        elif view == "Seguridad del dividendo":
            with st.container():
                fig, df_fcf, warn = _build_dividend_safety_chart(cashflow_df)
                if warn:
                    st.warning(warn)
                else:
                    st.plotly_chart(fig, use_container_width=True, key=f"div_safety_{ticker}")
    
                    # mini tabla (últimos años)
                    if df_fcf is not None and not df_fcf.empty:
                        st.markdown("#### Tabla (FCF, Dividendos Pagados, FCF Payout %)")
                        out = df_fcf.copy()
                        out["FCF Payout (%)"] = out["FCF Payout (%)"].round(2)
                        st.dataframe(out.tail(8), use_container_width=True)
    
        else:  # Geraldine Weiss
            with st.container():
                fig, m, warn = _build_geraldine_weiss_chart(price_daily_df, annual, cagr_5y)
                if warn:
                    st.warning(warn)
                else:
                    # métricas arriba (como tu UI antigua)
                    cols = st.columns(7)
                    cols[0].metric("Precio Actual", f"${m['Precio Actual']:.2f}")
                    cols[1].metric("Dividendo Anual", f"${m['Dividendo Anual']:.2f}")
                    cols[2].metric("CAGR 5Y", f"{m['CAGR 5Y']:.2f}%" if m["CAGR 5Y"] is not None else "N/D")
                    cols[3].metric("Yield Máximo", f"{m['Yield Máximo']*100:.2f}%")
                    cols[4].metric("Yield Mínimo", f"{m['Yield Mínimo']*100:.2f}%")
                    cols[5].metric("Sobrevalorado", f"${m['Sobrevalorado']:.2f}")
                    cols[6].metric("Infravalorado", f"${m['Infravalorado']:.2f}")
    
                    st.plotly_chart(fig, use_container_width=True, key=f"gw_{ticker}")
    

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
