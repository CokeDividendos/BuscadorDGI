# src/pages/analysis.py
import streamlit as st

from src.services.usage_limits import remaining_searches, consume_search
from src.services.finance_data import get_price_data, get_profile_data, get_key_stats, get_dividend_kpis
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

def page_analysis():
    DAILY_LIMIT = 3
    user_email = _get_user_email()
    admin = is_admin()

     st.sidebar:
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

    st.markdown(
        """
        <style>
          div[data-testid="stAppViewContainer"] section.main div.block-container {
            max-width: 980px !important;
            margin: 0 auto !important;
            padding-left: 18px !important;
            padding-right: 18px !important;
          }
          h2, h3 { margin-bottom: 0.25rem !important; }
          [data-testid="stCaptionContainer"] { margin-top: -6px !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    pad_l, center, pad_r = st.columns([1, 3, 1], gap="large")

     center:
        ticker = (st.session_state.get("ticker") or "").strip().upper()
        submitted = bool(st.session_state.pop("do_search", False))
        
        # Si nunca han buscado aún, no mostramos nada
        if not ticker:
            st.info("Ingresa un ticker en el buscador del sidebar.")
            return
        
        # Solo consume límite cuando realmente se presionó “Buscar”
        if not submitted:
            return


        if not ticker:
            st.warning("Ingresa un ticker.")
            return

        if (not admin) and user_email:
            ok, rem_after = consume_search(user_email, DAILY_LIMIT, cost=1)
            if not ok:
                limit_box.error("🚫 Búsquedas diarias alcanzadas. Vuelve mañana.")
                return
            limit_box.info(f"🔎 Búsquedas restantes hoy: {rem_after}/{DAILY_LIMIT}")

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

        st.write("")

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

        st.divider()

        # ✅ NUEVOS KPIs (2 filas x 3 columnas) para evitar compresión
        r1c1, r1c2, r1c3 = st.columns(3, gap="large")
        r2c1, r2c2, r2c3 = st.columns(3, gap="large")

        with r1c1:
            st.caption("Dividend Yield")
            st.markdown(f"### {_fmt_kpi(divk.get('div_yield'), suffix='%', decimals=2)}")

        with r1c2:
            st.caption("Forward Div. Yield")
            st.markdown(f"### {_fmt_kpi(divk.get('fwd_div_yield'), suffix='%', decimals=2)}")

        with r1c3:
            st.caption("Dividendo Anual $")
            st.markdown(f"### {_fmt_kpi(divk.get('annual_div'), decimals=2)}")

        with r2c1:
            st.caption("PayOut Ratio %")
            st.markdown(f"### {_fmt_kpi(divk.get('payout'), suffix='%', decimals=2)}")

        with r2c2:
            st.caption("Ex-Date")
            st.markdown(f"### {divk.get('ex_date') or 'N/D'}")

        with r2c3:
            st.caption("Próximo Dividendo")
            st.markdown(f"### {divk.get('next_div') or 'N/D'}")
