# src/pages/analysis.py
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


def _kpi_card(title: str, value: str) -> None:
    # “card” simple con borde nativo (Streamlit moderno)
    with st.container(border=True):
        st.caption(title)
        st.markdown(f"### {value}")


def page_analysis():
    DAILY_LIMIT = 3
    user_email = _get_user_email()
    admin = is_admin()

    # -----------------------------
    # SIDEBAR (solo acciones + límite)
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
    # BUSCADOR (arriba, en el dashboard)
    # -----------------------------
    # Fila superior: buscador limitado a ~media pantalla (estilo SeekingAlpha)
    left_search, right_blank = st.columns([1.2, 1], gap="large")
    with left_search:
        with st.form("top_search", clear_on_submit=False):
            st.caption("Buscar ticker")
            t = st.text_input(
                label="",
                value=st.session_state.get("ticker", "AAPL"),
                placeholder="Ej: AAPL",
            ).strip().upper()

            do_search = st.form_submit_button("🔎 Buscar", use_container_width=False)

        if do_search and t:
            st.session_state["ticker"] = t
            st.session_state["do_search"] = True
            st.rerun()

    st.write("")  # pequeño aire

    # -----------------------------
    # Ticker y control de submit
    # -----------------------------
    ticker = (st.session_state.get("ticker") or "").strip().upper()
    submitted = bool(st.session_state.pop("do_search", False))

    if not ticker:
        st.info("Ingresa un ticker arriba para comenzar.")
        return

    # Si aún no presionan Buscar, mostramos dashboard “pendiente” sin llamadas
    if not submitted:
        # Layout 2 columnas (A: info empresa | B: cards KPIs)
        colA, colB = st.columns([1.6, 1], gap="large")

        with colA:
            with st.container(border=True):
                st.markdown("## Logo + Nombre + Precio + KPIs importantes")
                st.info("Ticker cargado. Presiona **Buscar** para actualizar datos.")

        with colB:
            with st.container(border=True):
                st.markdown("## KPIs clave")
                st.caption("Pendiente de búsqueda.")

        st.write("")
        tabs = st.tabs(["Dividendos", "Múltiplos", "Balance", "Estado de Resultados", "Estado de Flujo de Efectivo", "Otro"])
        for tab in tabs:
            with tab:
                st.info("Pendiente de búsqueda.")
        return

    # -----------------------------
    # Límite diario (solo si realmente se buscó)
    # -----------------------------
    if (not admin) and user_email:
        ok, rem_after = consume_search(user_email, DAILY_LIMIT, cost=1)
        if not ok:
            limit_box.error("🚫 Búsquedas diarias alcanzadas. Vuelve mañana.")
            return
        limit_box.info(f"🔎 Búsquedas restantes hoy: {rem_after}/{DAILY_LIMIT}")

    # -----------------------------
    # DATA (yfinance vía tus services)
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
    # LAYOUT PRINCIPAL (2 columnas)
    # -----------------------------
    colA, colB = st.columns([1.6, 1], gap="large")

    # A) Logo + Ticker/Nombre + Precio + Variación (sin “marco” extra arriba)
    with colA:
        with st.container(border=True):
            st.markdown("## Logo + Nombre + Precio + KPIs importantes")

            # 1) Ticker + Nombre
            st.caption("Ticker · Nombre")
            st.markdown(f"### {ticker} — {company_name}")

            # 2) Precio + variación debajo
            st.caption("Precio")
            st.markdown(f"## {_fmt_price(last_price, currency)}")

            if delta_txt:
                color = "#16a34a" if (pct_val is not None and pct_val >= 0) else "#dc2626"
                st.markdown(
                    f"<div style='margin-top:-10px; font-size:0.95rem; color:{color};'>{delta_txt}</div>",
                    unsafe_allow_html=True,
                )

            # Logo (opcional)
            if logo_url:
                st.image(logo_url, width=46)

    # B) Donde estaba Geraldine Weiss: 6 cards simétricas con KPIs
    with colB:
        st.markdown("## KPIs clave")

        # Elegimos 6 “de los de abajo” para que queden simétricos aquí
        beta = _fmt_kpi(stats.get("beta"))
        pe = stats.get("pe_ttm")
        pe_txt = (_fmt_kpi(pe) + "x") if isinstance(pe, (int, float)) else "N/D"
        eps = _fmt_kpi(stats.get("eps_ttm"))
        target = _fmt_kpi(stats.get("target_1y"))

        div_y = _fmt_kpi(divk.get("div_yield"), suffix="%", decimals=2)
        fwd_y = _fmt_kpi(divk.get("fwd_div_yield"), suffix="%", decimals=2)

        r1c1, r1c2, r1c3 = st.columns(3, gap="large")
        r2c1, r2c2, r2c3 = st.columns(3, gap="large")

        with r1c1:
            _kpi_card("Beta", beta)
        with r1c2:
            _kpi_card("PER (TTM)", pe_txt)
        with r1c3:
            _kpi_card("EPS (TTM)", eps)

        with r2c1:
            _kpi_card("Target 1Y", target)
        with r2c2:
            _kpi_card("Dividend Yield", div_y)
        with r2c3:
            _kpi_card("Forward Div. Yield", fwd_y)

    st.write("")

    # -----------------------------
    # NAV TABS (reemplaza los 2 cuadros inferiores)
    # -----------------------------
    tabs = st.tabs(["Dividendos", "Múltiplos", "Balance", "Estado de Resultados", "Estado de Flujo de Efectivo", "Otro"])

    with tabs[0]:
        st.info("Aquí irán los gráficos de Dividendos (pendiente).")
        # Ej: payout, dividend growth, yield bands, etc.

    with tabs[1]:
        st.info("Aquí irán los gráficos de Múltiplos (pendiente).")

    with tabs[2]:
        st.info("Aquí irán los gráficos de Balance (pendiente).")

    with tabs[3]:
        st.info("Aquí irán los gráficos de Estado de Resultados (pendiente).")

    with tabs[4]:
        st.info("Aquí irán los gráficos de Flujo de Efectivo (pendiente).")

    with tabs[5]:
        st.info("Sección Otro (pendiente).")
