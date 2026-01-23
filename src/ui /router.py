# src/ui/router.py
from __future__ import annotations

import streamlit as st

# Imports con fallback para evitar colisiones de "src"
try:
    from src.db import init_db  # type: ignore
    from src.pages.login import page_login  # type: ignore
    from src.pages.analysis import page_analysis  # type: ignore
    from src.pages.admin_users import page_admin_users  # type: ignore
except ModuleNotFoundError:
    from db import init_db  # type: ignore
    from pages.login import page_login  # type: ignore
    from pages.analysis import page_analysis  # type: ignore
    from pages.admin_users import page_admin_users  # type: ignore


def run_app():
    # Bootstrap DB/cache/users
    init_db()

    # Si tu login usa otra clave, ajusta aquí.
    # (Mantengo esto estándar para no romper tu flujo.)
    is_authed = st.session_state.get("is_authenticated") is True

    if not is_authed:
        page_login()
        return

    # Sidebar navegación
    with st.sidebar:
        st.caption("Secciones")
        section = st.radio(
            label="",
            options=["Análisis", "Admin - Usuarios"],
            key="nav_section",
        )

    if section == "Admin - Usuarios":
        page_admin_users()
    else:
        page_analysis()
