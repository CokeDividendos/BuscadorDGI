# src/pages/analysis.py
import streamlit as st

from src.services.usage_limits import remaining_searches, consume_search
from src.services.finance_data import (
    get_price_data,
    get_profile_data,
    get_key_stats,
    get_dividend_kpis,   # ✅ NUEVO
)
from src.services.logos import logo_candidates
from src.auth import logout_button
from src.services.cache_store import cache_clear_all


def _get_user_email() -> str:
    for key in ["auth_email", "user_email", "email", "username", "user", "logged_email"]:
        v = st.session_state.get(key)
        if isinstance(v, str) and "@" in v:
            return v.strip().lower()
    return ""


def _get_user_role() -> str:
    for key in ["auth_role", "role", "user_role", "logged_role"]:
        v = st.session_state.get(key)
        if isinstance(v, str) and v:
            return v.strip().lower()
    return ""


def _is_admin() -> bool:
    return _get_user_role() == "admin" or st.session_state.get("is_admin") is True


def _fmt_price(x, currency: str) -> str:
    if not isinstance(x, (int, float)):
        return "N/D"
    # 1.234,56 estilo ES
    s = f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} {currency}".strip()


def _fmt_delta(net, pct) -> tuple[str | None, float | None]:
    """
    Retorna (texto_delta, pct_float) para colorear.
    """
    if isinstance(net, (int, float)) and isinstance(pct, (int, float)):
        return f"{net:+.2f} ({pct:+.2f}%)", float(pct)
    return None, None


def _fmt_kpi(x, suffix: str = "", decimals: int = 2) -> str:
    return f"{x:.{decimals}f}{suffix}" if isinstance(x, (int, float)) else "N/D"


def _fmt_pct(x, decimals: int = 2) -> str:
    return f"{x:.{decimals}f}%" if isinstance(x, (int, float)) else "N/D"


def page_analysis():
    DAILY_LIMIT = 3
    user_email = _get_user_email()
    is_admin = _is_admin()

    # -----------------------------
    # SIDEBAR (una sola vez)
    # -----------------------------
    with st.sidebar:
        logout_button()  # auth.py ya tiene key="logout_button"

        if is_admin:
            if st.button("🧹 Limpiar caché", key="clear_cache_btn", use_container_width=True):
                cache_clear_all()
                st.success("Caché limpiado.")
                st.rerun()

        limit_box = st.empty()
        if is_admin:
            limit_box.success("👑 Admin: sin límite diario (alimenta el caché global).")
        else:
            if user_email:
                rem = remaining_searches(user_email, DAILY_LIMIT)
                limit_box.info(f"🔎 Búsquedas restantes hoy: {rem}/{DAILY_LIMIT}")
            else:
                limit_box.warning("No se detectó el correo del usuario.")

    # -----------------------------
    # CSS: fijar ancho REAL del contenido
    # -----------------------------
    st.markdown(
        """
        <style>
          div[data-testid="stAppViewContainer"] section.main div.block-container {
            max-width: 980px !important;
            margin: 0 auto !important;
            padding-left: 18px !important;
            padding-right: 18px !important;
          }
          div[data-testid="stVerticalBlock"] { max-width: 980px !important; }

          h2, h3 { margin-bottom: 0.25rem !important; }
          [data-testid="stCaptionContainer"] { margin-top: -6px !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # -----------------------------
    # CONTENIDO CENTRADO
    # -----------------------------
    pad_l, center, pad_r = st.columns([1, 3, 1], gap="large")

    with center:
        # NIVEL 1: TÍTULO (si lo tienes arriba en otra parte, déjalo vacío)
        # st.title("📊 Análisis Financiero")

        # NIVEL 2: BUSCADOR
        with st.form("search_form", clear_on_submit=False):
            ticker = st.text_input("Ticker", value="AAPL").strip().upper()
            submitted = st.form_submit_button("🔎 Buscar")

        if not submitted:
            return

        if not ticker:
            st.warning("Ingresa un ticker.")
            return

        # Consume SOLO si NO es admin
        if (not is_admin) and user_email:
            ok, rem_after = consume_search(user_email, DAILY_LIMIT, cost=1)
            if not ok:
                limit_box.error("🚫 Búsquedas diarias alcanzadas. Vuelve mañana.")
                return
            limit_box.info(f"🔎 Búsquedas restantes hoy: {rem_after}/{DAILY_LIMIT}")

        # -----------------------------
        # DATA
        # -----------------------------
        price = get_price_data(ticker) or {}
        profile = get_profile_data(ticker) or {}
        raw = profile.get("raw") if isinstance(profile, dict) else {}
        stats = get_key_stats(ticker) or {}
        divk = get_dividend_kpis(ticker) or {}  # ✅ NUEVO (cacheado)

        company_name = raw.get("longName") or raw.get("shortName") or profile.get("shortName") or ticker

        last_price = price.get("last_price")
        currency = price.get("currency") or ""
        delta_txt, pct_val = _fmt_delta(price.get("net_change"), price.get("pct_change"))

        # Logo (best effort)
        website = (profile.get("website") or raw.get("website") or "") if isinstance(profile, dict) else ""
        logos = logo_candidates(website) if website else []
        logo_url = next((u for u in logos if isinstance(u, str) and u.startswith(("http://", "https://"))), "")

        st.write("")  # respiro

        # NIVEL 3: LOGO (izq) + BLOQUE NOMBRE/PRECIO/VARIACIÓN (vertical)
        c1, c2 = st.columns([0.12, 0.88], gap="small", vertical_alignment="center")

        with c1:
            if logo_url:
                st.image(logo_url, width=46)

        with c2:
            st.caption("Nombre")
            st.markdown(f"### {company_name}")

            st.caption("Precio")
            st.markdown(f"### {_fmt_price(last_price, currency)}")

            if delta_txt:
                color = "#16a34a" if (pct_val is not None and pct_val >= 0) else "#dc2626"
                st.markdown(
                    f"<div style='margin-top:-6px; font-size:0.92rem; color:{color};'>{delta_txt}</div>",
                    unsafe_allow_html=True,
                )

        st.divider()

        # NIVEL 4: KPIs (grilla 4 col, sin bordes)
        k1, k2, k3, k4 = st.columns(4, gap="large")

        with k1:
            st.caption("Beta")
            st.markdown(f"### {_fmt_kpi(stats.get('beta'))}")

        with k2:
            st.caption("PER (TTM)")
            pe = stats.get("pe_ttm")
            pe_txt = (_fmt_kpi(pe) + "x") if isinstance(pe, (int, float)) else "N/D"
            st.markdown(f"### {pe_txt}")

        with k3:
            st.caption("EPS (TTM)")
            st.markdown(f"### {_fmt_kpi(stats.get('eps_ttm'))}")

        with k4:
            st.caption("Target 1Y (est.)")
            st.markdown(f"### {_fmt_kpi(stats.get('target_1y'))}")

        # -----------------------------
        # NIVEL 5: KPIs Dividendos (6 cards, cacheados)
        # -----------------------------
        st.divider()
   
        d1, d2, d3, = st.columns(3, gap="large")
        
        with d1: 
            st.markdown(f"#### {_fmt_pct(divk.get('dividend_yield'))}")
            st.caption("Dividend Yield")
            
        with d2:
            st.markdown(f"#### {_fmt_pct(divk.get('forward_div_yield'))}")
            st.caption("Forward Div. Yield")
        
        with d3:
            st.markdown(f"#### {_fmt_kpi(divk.get('annual_dividend'), decimals=2)}")
            st.caption("Dividendo Anual $")
        
        d4, d5, d6 = st.columns(3, gap="large")
        
        with d4:
            st.markdown(f"#### {_fmt_pct(divk.get('payout_ratio'))}")
            st.caption("PayOut Ratio %")
        
        with d5:
            exd = divk.get("ex_div_date")
            st.markdown(f"#### {exd if isinstance(exd, str) and exd else 'N/D'}")
            st.caption("Ex-Date fecha")
        
        with d6:
            st.markdown(f"#### {_fmt_kpi(divk.get('next_dividend'), decimals=2)}")
            st.caption("Próximo Dividendo $")
