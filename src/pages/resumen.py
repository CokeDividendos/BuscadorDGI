# src/pages/resumen.py
from __future__ import annotations

from typing import Any, Dict

import pandas as pd
import streamlit as st

from src.auth import is_admin
from src.services.finance_data import (
    get_dividend_kpis,
    get_key_stats,
    get_price_data,
    get_profile_data,
)
from src.services.logos import logo_candidates

# Import all necessary functions from analysis.py
from src.pages.analysis import (
    _load_dividend_inputs,
    _load_financial_statements,
    _prepare_financial_df,
    _render_financial_table_expander,
    _plot_dividend_evolution,
    _plot_dividend_safety,
    _plot_geraldine_weiss,
    _plot_assets_evolution,
    _plot_debt_evolution,
    _plot_liabilities_evolution,
    _plot_equity_evolution,
    _plot_revenue_evolution,
    _plot_margins_evolution,
    _plot_eps_evolution,
    _plot_shares_outstanding,
    _plot_cashflow_vs_capex,
    _plot_debt_repayment,
    _plot_debt_issuance,
    _plot_share_buybacks,
    _plot_debt_fcf_evolution,
    _plot_per_evolution,
    _plot_ev_ebitda_evolution,
    _plot_fc_usage,
    _render_gurufocus_valuation_charts,
    _render_interactive_valuation_board,
    _calculate_financial_ratios,
    _plot_ratio_evolution,
    _load_ticker_info,
    YEARS,
)

# =========================================================
# Página principal - Resumen
# =========================================================
def page_resumen() -> None:
    """Display analysis sections based on sidebar selection."""
    
    # Ticker validation (search input is now in Buscador > Resumen section, which calls page_analysis)
    if "ticker" not in st.session_state:
        st.info("Por favor, busque un ticker usando el buscador primero.")
        return

    ticker = (st.session_state.get("ticker") or "").strip().upper()
    if not ticker:
        st.error("Ticker vacío. Por favor, busque un ticker usando el buscador.")
        return
    
    # Get user info
    admin = is_admin()
    
    # Load data
    price = get_price_data(ticker) or {}
    profile = get_profile_data(ticker) or {}
    raw = profile.get("raw") if isinstance(profile, dict) else {}
    stats = get_key_stats(ticker) or {}
    divk = get_dividend_kpis(ticker) or {}

    # Company name for display in titles
    company_name = raw.get("longName") or raw.get("shortName") or profile.get("shortName") or ticker

    # Display a simple header with the ticker
    st.markdown(f"## {ticker} — {company_name}")
    st.divider()

    # Display content based on selected section
    selected_section = st.session_state.get("analysis_section", "Dividendos")
    
    # SPECIAL CASE: "Resumen" subsection is the entry point (with search) under "Buscador".
    # When user is on "Resumen", we default to showing Dividendos content.
    # This maintains backward compatibility with the old "Análisis" page structure.
    if selected_section == "Resumen":
        selected_section = "Dividendos"
    
    if selected_section == "Dividendos":
        try:
            inputs = _load_dividend_inputs(ticker, YEARS)
        except Exception as e:
            st.error(f"Error al cargar datos de dividendos: {type(e).__name__}. Intente nuevamente.")
            return
        price_daily = inputs["price_daily"]
        dividends = inputs["dividends"]
        cashflow = inputs["cashflow"]

        if dividends.empty:
            st.info(
                "ℹ️ No se encontraron dividendos históricos para este ticker. "
                "Es posible que no pague dividendos o que los datos no estén disponibles en este momento."
            )

        st.markdown("## Valoración por dividendo")
        sub_tabs = st.tabs(["📈 Evolución del dividendo", "🛡️ Seguridad del dividendo", "📌 Geraldine Weiss"])
        with sub_tabs[0]:
            try:
                _plot_dividend_evolution(ticker, price_daily, dividends)
            except Exception as e:
                st.warning(f"No se pudo graficar la evolución del dividendo ({type(e).__name__}).")
        with sub_tabs[1]:
            try:
                _plot_dividend_safety(ticker, cashflow)
            except Exception as e:
                st.warning(f"No se pudo graficar la seguridad del dividendo ({type(e).__name__}).")
        with sub_tabs[2]:
            try:
                _plot_geraldine_weiss(ticker, price_daily, dividends)
            except Exception as e:
                st.warning(f"No se pudo graficar el análisis Geraldine Weiss ({type(e).__name__}).")
    
    elif selected_section == "Balance":
        st.markdown("## Balance")
        financial_data = _load_financial_statements(ticker)
        balance_df = _prepare_financial_df(financial_data["balance_sheet"], YEARS)
        
        if balance_df.empty:
            st.warning("No hay datos de balance disponibles para este ticker.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                _plot_assets_evolution(ticker, balance_df)
                _plot_debt_evolution(ticker, balance_df)
            with col2:
                _plot_liabilities_evolution(ticker, balance_df)
                _plot_equity_evolution(ticker, balance_df)
            _render_financial_table_expander("📋 Ver tabla Balance", balance_df)
    
    elif selected_section == "EERR":
        st.markdown("## Estado de Resultados")
        financial_data = _load_financial_statements(ticker)
        income_df = _prepare_financial_df(financial_data["income_stmt"], YEARS)
        
        if income_df.empty:
            st.warning("No hay datos de estado de resultados disponibles para este ticker.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                _plot_revenue_evolution(ticker, income_df)
                _plot_eps_evolution(ticker, income_df)
            with col2:
                _plot_margins_evolution(ticker, income_df)
                _plot_shares_outstanding(ticker, income_df)
            _render_financial_table_expander("📋 Ver tabla Estado de Resultados", income_df)
    
    elif selected_section == "EFE":
        st.markdown("## Estado de Flujo de Efectivo")
        financial_data = _load_financial_statements(ticker)
        cashflow_df = _prepare_financial_df(financial_data["cashflow"], YEARS)
        
        if cashflow_df.empty:
            st.warning("No hay datos de flujo de efectivo disponibles para este ticker.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                _plot_cashflow_vs_capex(ticker, cashflow_df)
                _plot_debt_repayment(ticker, cashflow_df)
            with col2:
                _plot_debt_issuance(ticker, cashflow_df)
                _plot_share_buybacks(ticker, cashflow_df)
            _render_financial_table_expander("📋 Ver tabla Flujo de Efectivo", cashflow_df)
    
    elif selected_section == "Valoración por múltiplos":
        st.markdown("## Valoración por múltiplos")
        financial_data = _load_financial_statements(ticker)
        balance_df = _prepare_financial_df(financial_data["balance_sheet"], YEARS)
        income_df = _prepare_financial_df(financial_data["income_stmt"], YEARS)
        cashflow_df = _prepare_financial_df(financial_data["cashflow"], YEARS)
        
        # Get ticker info for market cap and PE ratio (with rate limit protection)
        info = _load_ticker_info(ticker)
        
        if balance_df.empty and income_df.empty and cashflow_df.empty:
            st.warning("No hay datos financieros suficientes para la valoración por múltiplos.")
        else:
            # Create tabs for each chart
            sub_tabs = st.tabs(["💰 Evolución de la Deuda", "📊 Evolución del PER", "📈 Evolución EV/EBITDA", "📊 Uso del FC", "📊 Valoración Gurufocus"])
            with sub_tabs[0]:
                if not balance_df.empty and not cashflow_df.empty:
                    _plot_debt_fcf_evolution(ticker, balance_df, cashflow_df)
                else:
                    st.warning("No hay datos suficientes de balance y flujo de efectivo para este análisis.")
            with sub_tabs[1]:
                if not income_df.empty:
                    _plot_per_evolution(ticker, income_df, info)
                else:
                    st.warning("No hay datos suficientes de estado de resultados para este análisis.")
            with sub_tabs[2]:
                if not income_df.empty and not balance_df.empty:
                    _plot_ev_ebitda_evolution(ticker, income_df, balance_df, info)
                else:
                    st.warning("No hay datos suficientes para este análisis.")
            with sub_tabs[3]:
                if not cashflow_df.empty:
                    _plot_fc_usage(ticker, cashflow_df)
                else:
                    st.warning("No hay datos suficientes de flujo de efectivo para este análisis.")
            with sub_tabs[4]:
                _render_gurufocus_valuation_charts(ticker)
    
    elif selected_section == "Pizarra de Valoración":
        if not admin:
            st.warning("Esta sección es solo para administradores.")
            return
        st.markdown("## Pizarra de Valoración")
        
        # Get the company website to fetch logo
        website = (profile.get("website") or raw.get("website") or "") if isinstance(profile, dict) else ""
        logos = logo_candidates(website) if website else []
        logo_url = next((u for u in logos if isinstance(u, str) and u.startswith(("http://", "https://"))), "")
        
        if not logo_url:
            st.warning("No se pudo obtener el logo de la empresa. La funcionalidad de la pizarra requiere un logo válido.")
        else:
            _render_interactive_valuation_board(ticker, logo_url)
    
    elif selected_section == "Análisis Razonado":
        st.markdown("## Análisis Razonado")
        financial_data = _load_financial_statements(ticker)
        balance_df = _prepare_financial_df(financial_data["balance_sheet"], YEARS)
        income_df = _prepare_financial_df(financial_data["income_stmt"], YEARS)
        cashflow_df = _prepare_financial_df(financial_data["cashflow"], YEARS)
        
        if balance_df.empty and income_df.empty:
            st.warning("No hay datos financieros suficientes para el análisis razonado.")
        else:
            ratios = _calculate_financial_ratios(balance_df, income_df, cashflow_df, ticker)
            
            if ratios.empty:
                st.info("No se pudieron calcular ratios financieros con los datos disponibles.")
            else:
                # Display ratios in a two-column layout: table on left, chart on right
                ratio_cols = list(ratios.columns)
                
                # Check if we have any ratios to display
                if not ratio_cols:
                    st.info("No se pudieron calcular ratios financieros con los datos disponibles.")
                else:
                    # Transpose ratios DataFrame for better table display
                    # Rows will be metrics, columns will be years
                    ratios_transposed = ratios.T
                    
                    # Initialize selected metric in session state if not exists
                    session_key = f"selected_ratio_{ticker}"
                    if session_key not in st.session_state or st.session_state[session_key] not in ratio_cols:
                        st.session_state[session_key] = ratio_cols[0]
                    
                    # Create two columns: left for table, right for chart
                    col_table, col_chart = st.columns([1, 1])
                    
                    with col_table:
                        st.markdown("### Métricas Financieras")
                        
                        # Display the table with clickable rows
                        # Create a formatted DataFrame for display
                        display_df = ratios_transposed.copy()
                        
                        # Format values to 2 decimal places
                        try:
                            # Use map() for pandas >= 2.1, applymap() for older versions
                            display_df = display_df.map(lambda x: f"{x:.2f}" if pd.notna(x) else "N/D")
                        except AttributeError:
                            # Fallback to applymap for older pandas versions
                            display_df = display_df.applymap(lambda x: f"{x:.2f}" if pd.notna(x) else "N/D")
                        
                        # Display the dataframe
                        st.dataframe(
                            display_df,
                            use_container_width=True,
                            height=400
                        )
                        
                        # Add dropdown (selectbox) for metric selection
                        st.markdown("**Seleccione una métrica para visualizar:**")
                        
                        # Calculate default index for selectbox
                        default_index = ratio_cols.index(st.session_state[session_key])
                        
                        selected_metric = st.selectbox(
                            "Métrica",
                            ratio_cols,
                            index=default_index,
                            key=f"ratio_selector_{ticker}",
                            label_visibility="collapsed"
                        )
                        
                        # Update session state
                        st.session_state[session_key] = selected_metric
                    
                    with col_chart:
                        st.markdown("### Gráfico de Evolución")
                        
                        # Plot the selected ratio
                        selected_ratio_name = st.session_state[session_key]
                        selected_ratio_data = ratios[selected_ratio_name]
                        _plot_ratio_evolution(ticker, selected_ratio_name, selected_ratio_data)
