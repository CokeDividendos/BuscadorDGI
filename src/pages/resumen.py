# src/pages/resumen.py
from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from src.auth import is_admin
from src.db import get_user_gpt_api_key
from src.services.finance_data import (
    get_key_stats,
    get_price_data,
    get_profile_data,
    get_dividend_kpis,
)
from src.services.logos import logo_candidates
from src.services.usage_limits import consume_search, remaining_searches

# =========================================================
# Constantes
# =========================================================
YEARS = 5

# Color scheme constants
COLOR_PRIMARY = "#ff6d01"     # Orange - Primary chart elements
COLOR_SECONDARY = "#ff00ff"   # Magenta - Secondary chart elements
COLOR_TERTIARY = "#01c2ef"    # Cyan - Tertiary chart elements
COLOR_BACKGROUND = "#141f41"  # Dark blue - Chart background
COLOR_TEXT = "#ffffff"        # White - All text


# =========================================================
# Helpers UI / formato
# =========================================================
def _get_user_email() -> str:
    for key in ["auth_email", "user_email", "email", "username", "user", "logged_email"]:
        v = st.session_state.get(key)
        if isinstance(v, str) and "@" in v:
            return v.strip().lower()
    return ""


def _fmt_price(x: Any, currency: str) -> str:
    if not isinstance(x, (int, float)) or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "N/D"
    s = f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} {currency}".strip()


def _fmt_delta(net: Any, pct: Any) -> Tuple[Optional[str], Optional[float]]:
    if isinstance(net, (int, float)) and isinstance(pct, (int, float)):
        return f"{net:+.2f} ({pct:+.2f}%)", float(pct)
    return None, None


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


def _divk_get(divk: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if not isinstance(divk, dict):
            continue
        v = divk.get(k)
        if v is not None:
            return v
    return None


def _generate_gpt_summary(ticker: str, api_key: str) -> str:
    """Generate a financial summary using GPT API."""
    if not api_key:
        return "⚠️ No se ha configurado una API KEY de GPT. Por favor, ingrese su API KEY en el sidebar."
    
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        
        prompt = f"Haz un resumen financiero de la empresa según el ticker ingresado {ticker}, señalando a qué se dedica, cómo gana dinero y aspectos en los que destaca, el que debe ser escueto y resumido."
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Eres un analista financiero experto que proporciona resúmenes concisos y precisos sobre empresas."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=300,
            temperature=0.7
        )
        
        return response.choices[0].message.content.strip()
    except ImportError:
        return "⚠️ La librería openai no está instalada. Por favor, instálela para usar esta funcionalidad."
    except Exception as e:
        return f"⚠️ Error al generar el resumen: {str(e)}"


def _plot_price_variation_5y(ticker: str) -> None:
    """Plot 5-year price variation chart."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="5y", interval="1d")
        
        if hist.empty:
            st.warning("No hay datos de precio disponibles para los últimos 5 años.")
            return
        
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=hist.index,
                y=hist['Close'],
                mode='lines',
                name='Precio',
                line=dict(color=COLOR_PRIMARY, width=2),
            )
        )
        
        fig.update_layout(
            title=f"Variación del precio — {ticker} (5 años)",
            xaxis_title="Fecha",
            yaxis_title="Precio ($)",
            height=400,
            margin=dict(l=20, r=20, t=40, b=30),
            paper_bgcolor=COLOR_BACKGROUND,
            plot_bgcolor=COLOR_BACKGROUND,
            font=dict(color=COLOR_TEXT),
            showlegend=False,
        )
        fig.update_yaxes(showgrid=False, zeroline=False)
        fig.update_xaxes(showgrid=False, zeroline=False)
        
        st.plotly_chart(fig, use_container_width=True, key=f"price_5y_{ticker}")
    except Exception as e:
        st.error(f"Error al generar el gráfico de precio: {str(e)}")


def _plot_drawdown(ticker: str) -> None:
    """Plot drawdown chart."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="5y", interval="1d")
        
        if hist.empty:
            st.warning("No hay datos disponibles para calcular el drawdown.")
            return
        
        # Calculate drawdown
        close = hist['Close']
        running_max = close.cummax()
        drawdown = ((close - running_max) / running_max) * 100
        
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=drawdown.index,
                y=drawdown,
                mode='lines',
                name='Drawdown',
                line=dict(color=COLOR_SECONDARY, width=2),
                fill='tozeroy',
                fillcolor='rgba(255, 0, 255, 0.3)',
            )
        )
        
        fig.update_layout(
            title=f"Drawdown — {ticker} (5 años)",
            xaxis_title="Fecha",
            yaxis_title="Drawdown (%)",
            height=400,
            margin=dict(l=20, r=20, t=40, b=30),
            paper_bgcolor=COLOR_BACKGROUND,
            plot_bgcolor=COLOR_BACKGROUND,
            font=dict(color=COLOR_TEXT),
            showlegend=False,
        )
        fig.update_yaxes(showgrid=False, zeroline=False)
        fig.update_xaxes(showgrid=False, zeroline=False)
        
        st.plotly_chart(fig, use_container_width=True, key=f"drawdown_{ticker}")
    except Exception as e:
        st.error(f"Error al generar el gráfico de drawdown: {str(e)}")


def page_resumen() -> None:
    """Display the Resumen (Summary) page."""
    DAILY_LIMIT = 3
    user_email = _get_user_email()
    admin = is_admin()

    # Initialize ticker_main state at the start
    if "ticker_main" not in st.session_state:
        st.session_state["ticker_main"] = ""

    # CSS — sin sombras en KPIs, tarjetas individuales ni gráficos
    st.markdown(
        """
        <style>
        .search-middle > div[data-testid="stTextInput"] { max-width: 640px; margin: 0 auto; }
        div[data-testid="stTextInput"] input { border: none !important; box-shadow:none !important; }

        /* Contenedor de KPIs: sin sombra ni fondo */
        .kpis-container {
            background: transparent;
            border-radius: 0;
            padding: 0;
            box-shadow: none;
            margin-bottom: 16px;
        }

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

        /* pequeño ajuste para los metrics bajo los charts */
        .stMetric { background: transparent; }

        /* Quitar sombras a contenedores de gráficos */
        div[data-testid="stPlotlyChart"] {
            box-shadow: none !important;
        }

        div[data-testid="stForm"] { max-width: 520px !important; margin: 0 auto !important; border-radius: 10px; }
        
        /* Logo with white circle background */
        .logo-circle {
            width: 90px;
            height: 90px;
            border-radius: 50%;
            background-color: #ffffff;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 8px;
        }
        .logo-circle img {
            width: 100%;
            height: 100%;
            object-fit: contain;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Buscador (Enter activa)
    c_left, c_mid, c_right = st.columns([1, 2, 1])
    with c_mid:
        st.markdown('<div class="search-middle">', unsafe_allow_html=True)
        
        def _submit_search():
            val = (st.session_state.get("ticker_main") or "").strip().upper()
            if val:
                st.session_state["ticker"] = val

        st.text_input(
            "Ticker (ej: AAPL, MSFT, KO)",
            key="ticker_main",
            label_visibility="visible",
            placeholder="Buscar ticker y presiona Enter (ej: AAPL, MSFT, KO)",
            on_change=_submit_search,
        )
        st.markdown("</div>", unsafe_allow_html=True)

    if "ticker" not in st.session_state:
        st.info("Escribe un ticker y presiona Enter para cargar datos.")
        return

    ticker = (st.session_state.get("ticker") or "").strip().upper()
    if not ticker:
        st.error("Ticker vacío.")
        return

    # Track last searched ticker to only consume counter on NEW ticker searches
    last_ticker = st.session_state.get("last_searched_ticker", None)
    is_new_ticker = (ticker != last_ticker)
    
    # Consumo límite - ONLY on new ticker entry
    if (not admin) and user_email and is_new_ticker:
        ok, rem_after = consume_search(user_email, DAILY_LIMIT, cost=1)
        if not ok:
            st.error("🚫 Búsquedas diarias alcanzadas. Vuelve mañana.")
            return
        # Update last searched ticker after successful consumption
        st.session_state["last_searched_ticker"] = ticker
    elif is_new_ticker:
        # For admin or other cases, just track the ticker without consuming
        st.session_state["last_searched_ticker"] = ticker
    
    # Carga datos
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

    # Header: logo left
    left, right = st.columns([1.15, 0.85], gap="large")
    with left:
        c_logo, c_text = st.columns([0.12, 0.88], gap="small", vertical_alignment="center")
        with c_logo:
            if logo_url:
                st.markdown(f'<div class="logo-circle"><img src="{logo_url}" /></div>', unsafe_allow_html=True)
        with c_text:
            st.markdown(f"### {ticker} — {company_name}")
            st.markdown(f"## {_fmt_price(last_price, currency)}")
            if delta_txt:
                color = "#01c2ef" if (pct_val is not None and pct_val >= 0) else "#ff00ff"
                st.markdown(f"<div style='margin-top:-6px; color:{color}; font-weight:600'>{delta_txt}</div>", unsafe_allow_html=True)

    # ---------- KPIs (reordenados: 4 arriba + 4 abajo) ----------
    with right:
        st.markdown("### KPIs clave")
        
        # Contenedor único con sombra para todos los KPIs
        st.markdown('<div class="kpis-container">', unsafe_allow_html=True)
        
        try:
            # Fila superior: 4 KPIs generales
            top_cols = st.columns(4, gap="large")
            with top_cols[0]:
                _kpi_card("Beta", _fmt_kpi(stats.get("beta")))
            with top_cols[1]:
                pe = stats.get("pe_ttm")
                pe_txt = (_fmt_kpi(pe) + "x") if isinstance(pe, (int, float)) else "N/D"
                _kpi_card("PER (TTM)", pe_txt)
            with top_cols[2]:
                _kpi_card("EPS (TTM)", _fmt_kpi(stats.get("eps_ttm")))
            with top_cols[3]:
                _kpi_card("Target 1Y", _fmt_kpi(stats.get("target_1y")))

            # Fila inferior: 4 KPIs relacionados con dividendos (incluye PayOut)
            bottom_cols = st.columns(4, gap="large")

            div_yield = _divk_get(divk, "div_yield", "dividend_yield", "dividendYield", "dividend_yield_pct")
            fwd_div_yield = _divk_get(divk, "fwd_div_yield", "forward_div_yield", "forward_dividend_yield")
            annual_div = _divk_get(divk, "annual_dividend", "annual_div", "annualDividend")
            payout = _divk_get(divk, "payout_ratio", "payout", "payoutRatio")

            with bottom_cols[0]:
                val = "N/D"
                if isinstance(div_yield, (int, float)):
                    val = _fmt_kpi(div_yield, suffix="%", decimals=2)
                elif div_yield:
                    val = _fmt_kpi(div_yield)
                _kpi_card("Dividend Yield", val)

            with bottom_cols[1]:
                val = "N/D"
                if isinstance(fwd_div_yield, (int, float)):
                    val = _fmt_kpi(fwd_div_yield, suffix="%", decimals=2)
                elif fwd_div_yield:
                    val = _fmt_kpi(fwd_div_yield)
                _kpi_card("Fwd Div Yield", val)

            with bottom_cols[2]:
                val = "N/D"
                if isinstance(annual_div, (int, float)):
                    val = _fmt_kpi(annual_div, decimals=2)
                elif annual_div:
                    val = _fmt_kpi(annual_div)
                _kpi_card("Div. anual ($)", val)

            with bottom_cols[3]:
                val = "N/D"
                if isinstance(payout, (int, float)):
                    val = _fmt_kpi(payout, suffix="%", decimals=0)
                elif payout:
                    val = _fmt_kpi(payout)
                _kpi_card("PayOut Ratio", val)
        finally:
            # Cerrar contenedor de KPIs (siempre se ejecuta)
            st.markdown('</div>', unsafe_allow_html=True)

    st.divider()

    # GPT Summary Section
    st.markdown("## Resumen Financiero")
    
    api_key = get_user_gpt_api_key(user_email)
    if api_key:
        with st.spinner("Generando resumen con GPT..."):
            summary = _generate_gpt_summary(ticker, api_key)
            st.markdown(summary)
    else:
        st.info("⚠️ Para ver el resumen generado por GPT, configure su API KEY en el sidebar.")

    st.divider()

    # Charts Section
    st.markdown("## Análisis de Precio")
    col1, col2 = st.columns(2)
    
    with col1:
        _plot_price_variation_5y(ticker)
    
    with col2:
        _plot_drawdown(ticker)
