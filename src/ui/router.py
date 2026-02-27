# src/ui/router.py
import streamlit as st

from src.db import init_db, verify_database_integrity
from src.auth import require_login, is_admin, logout_button
from src.pages.analysis import page_analysis
from src.pages.resumen import page_resumen
from src.pages.blogs import page_blogs
from src.pages.api_keys import page_api_keys
from src.pages.admin_users import page_admin_users
from src.pages.etf_comparator import page_etf_comparator
from src.pages.dividend_simulator import page_dividend_simulator
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
        
        /* Specific text elements */
        .stMarkdown, [data-testid="stMarkdownContainer"] {
            color: #ffffff !important;
        }

        [data-testid="stCaptionContainer"] { 
            margin-top: -6px !important;
            color: #ffffff !important;
        }
        
        /* Orange buttons in sidebar (logout and clear cache) with white text */
        section[data-testid="stSidebar"] button[kind="secondary"] {
            background-color: #ff6d01 !important;
            color: white !important;
            border: none !important;
        }
        section[data-testid="stSidebar"] button[kind="secondary"]:hover {
            background-color: #e66101 !important;
            color: white !important;
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
        
        # 2. Main navigation sections
        if "page_section" not in st.session_state:
            st.session_state["page_section"] = "Buscador"  # Default to Buscador
        
        # Build page sections list
        page_sections = ["Buscador", "Buscador CL", "Comparador ETF", "Simulador de Dividendos", "Blogs", "🔑 API Keys"]
        if admin:
            page_sections.append("Admin · Usuarios")

        # Get current index for page selection
        current_page = st.session_state.get("page_section", "Buscador")
        try:
            current_idx = page_sections.index(current_page) if current_page in page_sections else 0
        except ValueError:
            current_idx = 0

        # Menú navegación principal como lista vertical (st.radio)
        page_section = st.radio(
            "### Navegación",
            page_sections,
            index=current_idx,
            key="page_section_radio"
        )
        
        # Update page section in session state
        st.session_state["page_section"] = page_section
        
        st.divider()

        # 4. Data sections (Dividendos, Balance, etc.) - Only in Buscador page
        # Initialize analysis section state if not exists (for page_analysis)
        if "analysis_section" not in st.session_state:
            st.session_state["analysis_section"] = "Resumen"
        
        # Show data sections only when in Buscador page (formerly shown in Análisis page)
        if page_section in ["Buscador", "Buscador CL"]:
            st.markdown("### Secciones de datos")
            data_sections = [
                "Resumen",  # anteriormente "Análisis"
                "Dividendos",
                "Balance",
                "EERR",
                "EFE",
                "Valoración por múltiplos",
                "Pizarra de Valoración",
                "Análisis Razonado",
            ]
            
            # Get the current analysis section, validate it's in the list
            current_analysis_section = st.session_state.get("analysis_section", "Resumen")
            if current_analysis_section not in data_sections:
                current_analysis_section = "Resumen"
            
            selected_data_section = st.selectbox(
                "Seleccione una sección de datos:",
                data_sections,
                index=data_sections.index(current_analysis_section),
                key="data_section_selector"
            )
            
            st.session_state["analysis_section"] = selected_data_section
            st.divider()

        # 5. Counter display (for non-admin users) - above buttons
        if not admin and user_email:
            rem = remaining_searches(user_email, DAILY_LIMIT)
            st.info(f"🔎 Búsquedas restantes hoy: {rem}/{DAILY_LIMIT}")
        elif admin:
            st.success("👑 Admin: sin límite diario (alimenta el caché global).")

        # 6. Logout and clear cache buttons at the bottom
        logout_button()
        if admin:
            if st.button("🧹 Limpiar caché", key="clear_cache_btn", use_container_width=True):
                cache_clear_all()
                st.success("Caché limpiado.")
                st.rerun()

    # Route to the appropriate page
    if page_section == "Buscador":
        # When in Buscador, render the appropriate subsection
        selected_data_section = st.session_state.get("analysis_section", "Resumen")
        
        if selected_data_section == "Resumen":
            # This is the former "Análisis" page
            page_analysis()
        else:
            # All other data sections (Dividendos, Balance, etc.) are rendered by page_resumen
            page_resumen()
            
    elif page_section == "Comparador ETF":
        page_etf_comparator()
    elif page_section == "Simulador de Dividendos":
        page_dividend_simulator()
    elif page_section == "Blogs":
        page_blogs()
    elif page_section == "🔑 API Keys":
        page_api_keys()
    elif page_section == "Admin · Usuarios":
        page_admin_users()
