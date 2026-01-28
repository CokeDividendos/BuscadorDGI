# src/ui/router.py
import streamlit as st

from src.db import init_db
from src.auth import require_login, is_admin, logout_button
from src.pages.analysis import page_analysis
from src.pages.admin_users import page_admin_users


def run_app():
    init_db()

    # ⛔ Si no está logueado, require_login dibuja la UI y detenemos
    if not require_login():
        st.stop()

    # =========================================================
    # CSS GLOBAL (incluye: sidebar SIEMPRE visible)
    # =========================================================
    st.markdown(
        """
        <style>
        /* --- Forzar sidebar visible siempre --- */
        section[data-testid="stSidebar"] {
            transform: none !important;
            margin-left: 0 !important;
            visibility: visible !important;
            min-width: 290px !important;
            max-width: 290px !important;
        }

        /* Oculta el control para colapsar/expandir (evita que lo cierren) */
        button[data-testid="collapsedControl"] {
            display: none !important;
        }

        /* Ajusta padding superior general */
        div[data-testid="stAppViewContainer"] section.main div.block-container {
            padding-top: 0rem !important;
            padding-left: 2.0rem !important;
            padding-right: 2.0rem !important;
            max-width: 100% !important;
        }

        section.main { padding-top: 0rem !important; }

        h2, h3 { margin-bottom: 0.25rem !important; }
        [data-testid="stCaptionContainer"] { margin-top: -6px !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Sidebar navegación (solo post-login)
    with st.sidebar:
        st.markdown(f"**Usuario:** {st.session_state.get('auth_email','')}")
        st.divider()

        sections = ["Análisis"]
        if is_admin():
            sections.append("Admin · Usuarios")

        section = st.radio("Secciones", sections, index=0)

        st.divider()
        logout_button()

    if section == "Análisis":
        page_analysis()
    elif section == "Admin · Usuarios":
        page_admin_users()
