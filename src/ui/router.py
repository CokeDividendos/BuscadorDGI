# src/ui/router.py  <-- reemplaza temporalmente con esto para debug
import streamlit as st
import traceback

# Intentamos importar src.db y capturar cualquier excepción para mostrarla en UI
try:
    from src.db import init_db
except Exception as e:
    st.markdown("## ❌ Error importando src.db")
    st.error("Se ha producido una excepción al importar src.db. Abajo está el traceback completo:")
    tb = traceback.format_exc()
    # Mostrar el traceback en la app (útil en Streamlit Cloud)
    st.code(tb, language="text")
    # También lanzamos de nuevo para que el proceso termine (opcional)
    raise

# Si src.db importó bien, el resto de router se ejecuta normalmente
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
        \"\"\"\n
        <style>
        /* --- Forzar sidebar visible siempre --- */
        section[data-testid=\"stSidebar\"] {
            transform: none !important;
            margin-left: 0 !important;
            visibility: visible !important;
            min-width: 290px !important;
            max-width: 290px !important;
        }

        /* Oculta el control para colapsar/expandir (evita que lo cierren) */
        button[data-testid=\"collapsedControl\"] {
            display: none !important;
        }

        /* Ajusta padding superior general */
        div[data-testid=\"stAppViewContainer\"] section.main div.block-container {
            padding-top: 0rem !important;
            padding-left: 2.0rem !important;
            padding-right: 2.0rem !important;
            max-width: 100% !important;
        }

        section.main { padding-top: 0rem !important; }

        h2, h3 { margin-bottom: 0.25rem !important; }
        [data-testid=\"stCaptionContainer\"] { margin-top: -6px !important; }
        </style>
        \"\"\",
        unsafe_allow_html=True,
    )

    # Sidebar navegación (solo post-login)
    with st.sidebar:
        st.markdown(f\"**Usuario:** {st.session_state.get('auth_email','')}\")
        st.divider()

        sections = [\"Análisis\"]
        if is_admin():
            sections.append(\"Admin · Usuarios\")

        section = st.radio(\"Secciones\", sections, index=0)

        st.divider()
        logout_button()

    if section == \"Análisis\":
        page_analysis()
    elif section == \"Admin · Usuarios\":
        page_admin_users()
