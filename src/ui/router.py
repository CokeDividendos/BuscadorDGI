# src/ui/router.py
import streamlit as st

from src.db import init_db
from src.auth import require_login, is_admin, logout_button
from src.pages.analysis import page_analysis
from src.pages.admin_users import page_admin_users
from src.services.cache_store import cache_clear_all
from src.services.usage_limits import remaining_searches


def run_app():
    init_db()

    # ⛔ Si no está logueado, require_login dibuja la UI y detenemos
    if not require_login():
        st.stop()

    # =========================================================
    # CSS GLOBAL
    # =========================================================
    st.markdown(
        """
        <style>
        /* --- Sidebar collapsible --- */
        section[data-testid="stSidebar"] {
            min-width: 290px !important;
            max-width: 290px !important;
        }

        /* Dashboard background color (excluding sidebar) */
        section.main {
            background-color: #141f41 !important;
            padding-top: 0rem !important;
        }

        /* Ajusta padding superior general */
        div[data-testid="stAppViewContainer"] section.main div.block-container {
            padding-top: 0rem !important;
            padding-left: 2.0rem !important;
            padding-right: 2.0rem !important;
            max-width: 100% !important;
        }

        /* All titles and text to white */
        h1, h2, h3, h4, h5, h6 {
            color: #ffffff !important;
            margin-bottom: 0.25rem !important;
        }
        
        /* Chart titles and labels */
        .js-plotly-plot .plotly text {
            fill: #ffffff !important;
        }
        
        /* All text elements white */
        p, span, div {
            color: #ffffff !important;
        }

        [data-testid="stCaptionContainer"] { 
            margin-top: -6px !important;
            color: #ffffff !important;
        }
        
        /* Markdown text */
        .stMarkdown {
            color: #ffffff !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Sidebar navegación (solo post-login)
    DAILY_LIMIT = 3
    user_email = st.session_state.get('auth_email', '')
    admin = is_admin()
    
    with st.sidebar:
        # 1. User email at the top
        st.markdown(f"**Usuario:** {user_email}")
        st.divider()

        # 2. Data sections (Dividendos, Balance, etc.) - Only in Análisis page
        # Initialize page selection if not exists
        if "page_section" not in st.session_state:
            st.session_state["page_section"] = "Análisis"
        
        # Initialize analysis section state if not exists (for page_analysis)
        if "analysis_section" not in st.session_state:
            st.session_state["analysis_section"] = "Dividendos"
        
        # Show data sections only when in Análisis page
        current_page = st.session_state.get("page_section", "Análisis")
        if current_page == "Análisis":
            st.markdown("### Secciones de datos")
            data_sections = [
                "Dividendos",
                "Balance",
                "EERR",
                "EFE",
                "Valoración por múltiplos",
                "Análisis Razonado",
            ]
            
            # Get the current analysis section, validate it's in the list
            current_analysis_section = st.session_state.get("analysis_section", "Dividendos")
            if current_analysis_section not in data_sections:
                current_analysis_section = "Dividendos"
            
            selected_data_section = st.radio(
                "Seleccione una sección de datos:",
                data_sections,
                index=data_sections.index(current_analysis_section),
                key="data_section_selector",
                label_visibility="collapsed"
            )
            
            st.session_state["analysis_section"] = selected_data_section
            st.divider()

        # 3. Page navigation sections (Análisis, Admin)
        st.markdown("### Navegación")
        page_sections = ["Análisis"]
        if admin:
            page_sections.append("Admin · Usuarios")

        # Get current index for page selection
        try:
            current_idx = page_sections.index(current_page) if current_page in page_sections else 0
        except ValueError:
            current_idx = 0

        page_section = st.radio(
            "Secciones de página",
            page_sections,
            index=current_idx,
            key="page_section_radio",
            label_visibility="collapsed"
        )
        
        # Update page section in session state
        st.session_state["page_section"] = page_section
        
        st.divider()

        # 4. Counter display (for non-admin users) - above buttons
        if not admin and user_email:
            rem = remaining_searches(user_email, DAILY_LIMIT)
            st.info(f"🔎 Búsquedas restantes hoy: {rem}/{DAILY_LIMIT}")
        elif admin:
            st.success("👑 Admin: sin límite diario (alimenta el caché global).")

        # 5. Logout and clear cache buttons at the bottom
        logout_button()
        if admin:
            if st.button("🧹 Limpiar caché", key="clear_cache_btn", use_container_width=True):
                cache_clear_all()
                st.success("Caché limpiado.")
                st.rerun()

    # Route to the appropriate page
    if page_section == "Análisis":
        page_analysis()
    elif page_section == "Admin · Usuarios":
        page_admin_users()
