# src/pages/etf_comparator.py
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from src.auth import is_admin
from src.services.cache_store import cache_get, cache_set
from src.services.usage_limits import consume_search, remaining_searches

# =========================================================
# Constantes
# =========================================================
DIVIDENDS_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 días
DAILY_LIMIT = 3

# Color scheme constants
COLOR_PRIMARY = "#ff6d01"     # Orange - Primary chart elements
COLOR_TERTIARY = "#01c2ef"    # Cyan - Tertiary chart elements
COLOR_BACKGROUND = "#141f41"  # Dark blue - Chart background
COLOR_TEXT = "#ffffff"        # White - All text

# Spanish month names for date formatting
SPANISH_MONTHS = {
    1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"
}


# =========================================================
# Helpers
# =========================================================
def _format_date_spanish(date_index: pd.DatetimeIndex) -> list[str]:
    """Format dates in Spanish (MMM YYYY format)."""
    return [f"{SPANISH_MONTHS[d.month]} {d.year}" for d in date_index]
def _get_user_email() -> str:
    for key in ["auth_email", "user_email", "email", "username", "user", "logged_email"]:
        v = st.session_state.get(key)
        if isinstance(v, str) and "@" in v:
            return v.strip().lower()
    return ""


def _fmt_kpi(x: Any, suffix: str = "", decimals: int = 2) -> str:
    if not isinstance(x, (int, float)) or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "N/D"
    return f"{x:.{decimals}f}{suffix}"


def _kpi_card(label: str, value: str) -> None:
    st.markdown(
        f"""
        <div class="kpi-card">
          <div class="kpi-label">{label}</div>
          <div class="kpi-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# =========================================================
# Data fetching functions
# =========================================================
@st.cache_data(ttl=DIVIDENDS_CACHE_TTL_SECONDS, show_spinner=False)
def _load_dividend_data(ticker: str, months: int) -> pd.Series:
    """Load dividend data for a ticker."""
    try:
        t = yf.Ticker(ticker)
        dividends = t.dividends
        if dividends is None or not isinstance(dividends, pd.Series):
            return pd.Series(dtype=float)
        return dividends.dropna().astype(float)
    except Exception:
        return pd.Series(dtype=float)


def _filter_last_months(dividends: pd.Series, months: int) -> pd.Series:
    """Filter dividends to show only the last N months of data."""
    if dividends.empty:
        return pd.Series(dtype=float)
    
    # Get the last date
    end_date = dividends.index.max()
    
    # Calculate start date (N months back)
    start_date = end_date - pd.DateOffset(months=months)
    
    # Filter data
    filtered = dividends[dividends.index >= start_date]
    
    return filtered.dropna()


def _cagr_from_filtered(dividends: pd.Series) -> Optional[float]:
    """
    Calculate CAGR from dividend series using ONLY complete calendar years.
    This ensures accurate CAGR calculation regardless of the month range selected.
    """
    if dividends.empty or len(dividends) < 12:
        return None
    
    # Get only data from complete calendar years
    # Exclude current year if it's not complete
    current_year = datetime.now().year
    
    # Filter to only include complete years
    complete_years_data = dividends[dividends.index.year < current_year]
    
    if complete_years_data.empty:
        # If no complete years, we can't calculate CAGR reliably
        return None
    
    # Aggregate to annual totals
    annual = complete_years_data.resample("YE").sum().dropna()
    
    if annual.empty or len(annual) < 2:
        return None
    
    first_val = float(annual.iloc[0])
    last_val = float(annual.iloc[-1])
    
    if first_val <= 0 or last_val <= 0:
        return None
    
    n_years = len(annual) - 1
    if n_years <= 0:
        return None
    
    cagr = (pow(last_val / first_val, 1.0 / n_years) - 1) * 100
    return cagr


# =========================================================
# Chart functions
# =========================================================
def _plot_single_etf_dividends(ticker: str, dividends: pd.Series, months: int, chart_key: str) -> Optional[float]:
    """
    Plot dividend evolution as bar chart for a single ETF.
    Returns the CAGR value.
    """
    filtered = _filter_last_months(dividends, months)
    
    if filtered.empty:
        st.warning(f"No hay dividendos suficientes para {ticker} en el periodo seleccionado.")
        return None
    
    # Calculate CAGR
    cagr = _cagr_from_filtered(filtered)
    
    # Format dates for x-axis in Spanish (e.g., "Ene 2024")
    x_labels = _format_date_spanish(filtered.index)
    
    # Create bar chart
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=x_labels,
        y=filtered.values,
        name="Dividendo mensual",
        marker_color=COLOR_PRIMARY,
        text=[f"${v:.2f}" for v in filtered.values],
        textposition="outside"
    ))
    
    fig.update_layout(
        title=f"Evolución del dividendo - {ticker}",
        xaxis_title="Mes",
        yaxis_title="Dividendo mensual ($)",
        height=400,
        paper_bgcolor=COLOR_BACKGROUND,
        plot_bgcolor=COLOR_BACKGROUND,
        font=dict(color=COLOR_TEXT, size=12),
        title_font=dict(size=16, color=COLOR_TEXT),
        xaxis=dict(
            gridcolor="rgba(255,255,255,0.1)",
            showgrid=True,
            color=COLOR_TEXT,
            tickangle=-45
        ),
        yaxis=dict(
            gridcolor="rgba(255,255,255,0.1)",
            showgrid=True,
            color=COLOR_TEXT
        ),
        showlegend=False,
        margin=dict(l=60, r=40, t=60, b=80)
    )
    
    st.plotly_chart(fig, use_container_width=True, key=chart_key)
    
    return cagr


def _plot_comparison_chart(ticker1: str, ticker2: str, dividends1: pd.Series, dividends2: pd.Series, months: int) -> None:
    """
    Plot comparison line chart showing dividends of both ETFs.
    Uses actual datetime values for proper alignment.
    """
    filtered1 = _filter_last_months(dividends1, months)
    filtered2 = _filter_last_months(dividends2, months)
    
    if filtered1.empty and filtered2.empty:
        st.warning("No hay datos suficientes para comparar ambos ETFs.")
        return
    
    # Create line chart using DATETIME values (not formatted strings)
    fig = go.Figure()
    
    if not filtered1.empty:
        fig.add_trace(go.Scatter(
            x=filtered1.index,  # Use datetime index directly
            y=filtered1.values,
            mode='lines+markers',
            name=ticker1,
            line=dict(color=COLOR_PRIMARY, width=3),
            marker=dict(size=8, color=COLOR_PRIMARY)
        ))
    
    if not filtered2.empty:
        fig.add_trace(go.Scatter(
            x=filtered2.index,  # Use datetime index directly
            y=filtered2.values,
            mode='lines+markers',
            name=ticker2,
            line=dict(color=COLOR_TERTIARY, width=3),
            marker=dict(size=8, color=COLOR_TERTIARY)
        ))
    
    fig.update_layout(
        title=f"Comparación de dividendos: {ticker1} vs {ticker2}",
        xaxis_title="Fecha",
        yaxis_title="Dividendo mensual ($)",
        height=500,
        paper_bgcolor=COLOR_BACKGROUND,
        plot_bgcolor=COLOR_BACKGROUND,
        font=dict(color=COLOR_TEXT, size=12),
        title_font=dict(size=18, color=COLOR_TEXT),
        xaxis=dict(
            gridcolor="rgba(255,255,255,0.1)",
            showgrid=True,
            color=COLOR_TEXT,
            tickangle=-45,
            type='date'  # Ensure datetime type
        ),
        yaxis=dict(
            gridcolor="rgba(255,255,255,0.1)",
            showgrid=True,
            color=COLOR_TEXT
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=COLOR_TEXT)
        ),
        margin=dict(l=60, r=40, t=80, b=80)
    )
    
    st.plotly_chart(fig, use_container_width=True, key=f"comparison_{ticker1}_{ticker2}")


# =========================================================
# Main page function
# =========================================================
def page_etf_comparator() -> None:
    """Display the ETF Comparator page."""
    
    # Get user info for search limits
    user_email = _get_user_email()
    admin = is_admin()
    
    # CSS
    st.markdown(
        """
        <style>
        .search-middle > div[data-testid="stTextInput"] { max-width: 640px; margin: 0 auto; }
        div[data-testid="stTextInput"] input { border: none !important; box-shadow:none !important; }

        /* KPI cards individuales: sin sombra, solo fondo y padding */
        .kpi-card {
          background: transparent;
          border-radius: 10px;
          padding: 12px;
          display: block;
          margin-bottom: 8px;
        }
        .kpi-label { font-size: 0.78rem; color: #ffffff; margin-bottom:6px; }
        .kpi-value { font-size: 1.4rem; font-weight:700; color: #01c2ef; }

        /* Quitar sombras a contenedores de gráficos */
        div[data-testid="stPlotlyChart"] {
            box-shadow: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    
    st.markdown("## Comparador ETF")
    st.markdown("Compara la evolución de los dividendos de dos ETFs.")
    st.divider()
    
    # Period selector
    st.markdown("### Seleccionar periodo de análisis")
    period_options = {
        "12 meses": 12,
        "24 meses": 24,
        "36 meses": 36,
        "48 meses": 48,
        "60 meses": 60
    }
    
    selected_period_label = st.selectbox(
        "Periodo:",
        options=list(period_options.keys()),
        index=3,  # Default to 48 months (4 years)
        label_visibility="collapsed"
    )
    selected_months = period_options[selected_period_label]
    
    st.divider()
    
    # Two columns for ETF comparison
    col1, col2 = st.columns(2, gap="large")
    
    # Initialize session state for tickers
    if "etf1_input" not in st.session_state:
        st.session_state["etf1_input"] = ""
    if "etf2_input" not in st.session_state:
        st.session_state["etf2_input"] = ""
    if "etf1" not in st.session_state:
        st.session_state["etf1"] = ""
    if "etf2" not in st.session_state:
        st.session_state["etf2"] = ""
    
    # Store loaded dividend data to avoid redundant API calls
    dividends1 = None
    dividends2 = None
    
    # ETF 1
    with col1:
        st.markdown("### ETF 1")
        
        def _submit_etf1():
            val = (st.session_state.get("etf1_input") or "").strip().upper()
            if val:
                st.session_state["etf1"] = val
        
        st.text_input(
            "Ticker ETF 1 (ej: VTI, SPY, QQQ)",
            key="etf1_input",
            placeholder="Ingresa ticker y presiona Enter",
            on_change=_submit_etf1,
            label_visibility="collapsed"
        )
        
        etf1 = st.session_state.get("etf1", "").strip().upper()
        if etf1:
            with st.spinner(f"Cargando datos de {etf1}..."):
                dividends1 = _load_dividend_data(etf1, selected_months)
                cagr1 = _plot_single_etf_dividends(etf1, dividends1, selected_months, f"etf1_chart_{selected_months}")
                
                # Display CAGR card
                if cagr1 is not None:
                    _kpi_card(f"CAGR del dividendo ({selected_period_label})", _fmt_kpi(cagr1, suffix="%"))
                else:
                    _kpi_card(f"CAGR del dividendo ({selected_period_label})", "N/D")
        else:
            st.info("Ingresa un ticker para ETF 1")
    
    # ETF 2
    with col2:
        st.markdown("### ETF 2")
        
        def _submit_etf2():
            val = (st.session_state.get("etf2_input") or "").strip().upper()
            if val:
                st.session_state["etf2"] = val
        
        st.text_input(
            "Ticker ETF 2 (ej: VTI, SPY, QQQ)",
            key="etf2_input",
            placeholder="Ingresa ticker y presiona Enter",
            on_change=_submit_etf2,
            label_visibility="collapsed"
        )
        
        etf2 = st.session_state.get("etf2", "").strip().upper()
        if etf2:
            with st.spinner(f"Cargando datos de {etf2}..."):
                dividends2 = _load_dividend_data(etf2, selected_months)
                cagr2 = _plot_single_etf_dividends(etf2, dividends2, selected_months, f"etf2_chart_{selected_months}")
                
                # Display CAGR card
                if cagr2 is not None:
                    _kpi_card(f"CAGR del dividendo ({selected_period_label})", _fmt_kpi(cagr2, suffix="%"))
                else:
                    _kpi_card(f"CAGR del dividendo ({selected_period_label})", "N/D")
        else:
            st.info("Ingresa un ticker para ETF 2")
    
    # Comparison chart - reuse loaded data
    st.divider()
    st.markdown("### Comparación de ambos ETFs")
    
    etf1 = st.session_state.get("etf1", "").strip().upper()
    etf2 = st.session_state.get("etf2", "").strip().upper()
    
    if etf1 and etf2:
        # Track last compared ETFs to only consume counter on NEW comparisons
        last_comparison = st.session_state.get("last_etf_comparison", None)
        current_comparison = f"{etf1}_{etf2}"
        is_new_comparison = (current_comparison != last_comparison)
        
        # Consume search limit - ONLY on new comparison (both ETFs entered)
        if (not admin) and user_email and is_new_comparison:
            ok, rem_after = consume_search(user_email, DAILY_LIMIT, cost=1)
            if not ok:
                st.error("🚫 Búsquedas diarias alcanzadas. Vuelve mañana.")
                return
            # Update last comparison after successful consumption
            st.session_state["last_etf_comparison"] = current_comparison
        elif is_new_comparison:
            # For admin or other cases, just track the comparison without consuming
            st.session_state["last_etf_comparison"] = current_comparison
        
        with st.spinner("Generando gráfico de comparación..."):
            # Reuse already loaded data if available, otherwise load it
            if dividends1 is None:
                dividends1 = _load_dividend_data(etf1, selected_months)
            if dividends2 is None:
                dividends2 = _load_dividend_data(etf2, selected_months)
            _plot_comparison_chart(etf1, etf2, dividends1, dividends2, selected_months)
    elif etf1 or etf2:
        st.info("Ingresa ambos tickers para ver la comparación.")
    else:
        st.info("Ingresa dos tickers para comparar sus dividendos.")
