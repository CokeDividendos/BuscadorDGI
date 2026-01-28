# src/ui/router.py
import streamlit as st

from src.db import init_db
from src.auth import require_login, is_admin, logout_button
from src.pages.analysis import page_analysis
from src.pages.admin_users import page_admin_users


def run_app():
    # ------------------------------------------------------------
    # CSS GLOBAL (aplica a todas las páginas: login + post-login)
    # ------------------------------------------------------------
    st.markdown(
        """
        <style>
          /* Oculta el header superior de Streamlit (reduce el “aire fantasma”) */
          header[data-testid="stHeader"] {
            height: 0 !important;
            visibility: hidden;
          }
          div[data-testid="stToolbar"] { height: 0 !important; }

          /* Sidebar “fijo”: oculta el botón de colapsar/expandir */
          [data-testid="collapsedControl"] { display: none !important; }

          /* Ajuste opcional: deja el main pegado arriba */
          section.main { padding-top: 0rem !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    init_db()

    # ⛔ Si no está logueado, require_login dibuja la UI y detenemos
    if not require_login():
        st.stop()

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
