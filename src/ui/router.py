import streamlit as st
from src.db import init_db
from src.auth import require_login, is_admin, logout_button
from src.pages.analysis import page_analysis

# NUEVO: admin page
from src.pages.admin_users import page_admin_users


def run_app():
    init_db()

    # --- BUSCADOR (debajo del usuario) ---
    with st.sidebar.form("sidebar_search", clear_on_submit=False):
        st.caption("Ticker")
        _t = st.text_input(
            label="",
            value=st.session_state.get("ticker", "AAPL"),
            key="ticker_sidebar",
            placeholder="Ej: AAPL",
        ).strip().upper()

        do_search = st.form_submit_button("🔎 Buscar", use_container_width=True)

    if do_search and _t:
        st.session_state["ticker"] = _t
        st.session_state["do_search"] = True
        st.rerun()

    # ⛔ Si no está logueado, require_login dibuja la UI y cortamos
    if not require_login():
        st.stop()

    # -----------------------------
    # SIDEBAR navegación (post-login)
    # -----------------------------
    with st.sidebar:
        st.markdown(f"**Usuario:** {st.session_state.get('auth_email','')}")
        st.divider()

        sections = ["Análisis"]
        if is_admin():
            sections.append("Admin · Usuarios")

        section = st.radio("Secciones", sections, index=0)

        # ✅ Cerrar sesión (al final)
        st.divider()
        logout_button("🚪 Cerrar sesión")

    # -----------------------------
    # CONTENIDO PRINCIPAL
    # -----------------------------
    if section == "Análisis":
        page_analysis()
    elif section == "Admin · Usuarios":
        page_admin_users()
