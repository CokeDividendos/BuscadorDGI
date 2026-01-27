# src/pages/analysis.py
from __future__ import annotations

import streamlit as st

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
          /* Menos aire arriba: pega el buscador al top */
          div[data-testid="stAppViewContainer"] section.main div.block-container {
            padding-top: 0.5rem !important;
            padding-left: 2.0rem !important;
            padding-right: 2.0rem !important;
            max-width: 100% !important; /* que use el ancho completo */
          }

          /* Quitar “bordes”/marcos típicos de contenedores y forms */
          div[data-testid="stForm"] {
            border: none !important;
            padding: 0 !important;
            margin: 0 !important;
          }

          /* Inputs más limpios */
          div[data-testid="stTextInput"] > div {
            border-radius: 12px !important;
          }

          /* Cards KPI uniformes */
          .kpi-card {
            background: transparent;
            border: none;
            border-radius: 14px;
            padding: 14px 14px 12px 14px;
            min-height: 86px;
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

          /* Bloque Nombre/Precio sin borde */
          .main-card {
            background: transparent;
            border: none;
            border-radius: 16px;
            padding: 0;
          }

          /* Título compacto */
          h2, h3 { margin-bottom: 0.25rem !important; }
          [data-testid="stCaptionContainer"] { margin-top: -6px !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # -----------------------------
    # SIDEBAR (solo controles, NO buscador)
    # -----------------------------
    with st.sidebar:
        # Cache + límites
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
    # BUSCADOR (arriba, sin marco, ancho ~1/2 pantalla)
    # -----------------------------
    top_left, top_right = st.columns([1.15, 0.85], gap="large")
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
    # Lógica de “solo actualizar cuando se presiona Buscar”
    # -----------------------------
    ticker = (st.session_state.get("ticker") or "").strip().upper()
    did_search = bool(st.session_state.pop("do_search", False))

    # Si no hay ticker, no mostramos datos todavía (pero sí el layout base)
    if not ticker:
        st.info("Ingresa un ticker en el buscador para cargar datos.")
        return

    # Si todavía no presionaron Buscar en esta sesión, no consumimos límite ni refrescamos
    if not did_search:
        st.caption("Ticker cargado. Presiona **Buscar** para actualizar datos.")
        return

    # Consume SOLO si NO es admin
    if (not admin) and user_email:
        ok, rem_after = consume_search(user_email, DAILY_LIMIT, cost=1)
        if not ok:
            st.sidebar.error("🚫 Búsquedas diarias alcanzadas. Vuelve mañana.")
            return
        st.sidebar.info(f"🔎 Búsquedas restantes hoy: {rem_after}/{DAILY_LIMIT}")

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
    # BLOQUE SUPERIOR: (izq) nombre/precio + (der) KPIs en tarjetas
    # -----------------------------
    left, right = st.columns([1.15, 0.85], gap="large")

    with left:
        st.markdown('<div class="main-card">', unsafe_allow_html=True)

        # Logo + Ticker—Nombre en la MISMA línea
        a1, a2 = st.columns([0.10, 0.90], gap="small", vertical_alignment="center")
        with a1:
            if logo_url:
                st.image(logo_url, width=40)
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

    st.write("")  # pequeño respiro

    # -----------------------------
    # TABS de navegación (gráficos abajo)
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
        st.info("Aquí irán los gráficos de Dividendos (pendiente).")
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
