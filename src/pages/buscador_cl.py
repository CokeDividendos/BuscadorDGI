# src/pages/buscador_cl.py
from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st
import yfinance as yf

from src.auth import is_admin
from src.pages.analysis import (
    _fmt_large_number,
    _fmt_kpi,
    _kpi_card,
    _load_ticker_info,
    _plot_assets_evolution,
    _plot_cashflow_vs_capex,
    _plot_debt_evolution,
    _plot_debt_fcf_evolution,
    _plot_debt_issuance,
    _plot_debt_repayment,
    _plot_dividend_evolution,
    _plot_dividend_safety,
    _plot_drawdown,
    _plot_eps_evolution,
    _plot_equity_evolution,
    _plot_ev_ebitda_evolution,
    _plot_fc_usage,
    _plot_geraldine_weiss,
    _plot_liabilities_evolution,
    _plot_margins_evolution,
    _plot_per_evolution,
    _plot_price_variation_5y,
    _plot_ratio_evolution,
    _plot_revenue_evolution,
    _plot_share_buybacks,
    _plot_shares_outstanding,
    _prepare_financial_df,
    _calculate_financial_ratios,
    _render_52w_gauge,
    _render_gurufocus_valuation_charts,
    _render_interactive_valuation_board,
    YEARS,
)
from src.services.chile_data import (
    get_cl_company_name,
    get_cl_tickers_list,
    get_cl_yf_ticker,
    is_cl_ticker,
    load_cl_dividends,
    load_cl_financial_statements,
)
from src.services.finance_data import get_price_data, get_52w_range
from src.services.logos import logo_candidates


# =========================================================
# Helpers
# =========================================================

def _load_cl_price_daily(yf_ticker: str, years: int = YEARS) -> pd.DataFrame:
    """Fetch daily price history from YF for the CL ticker (e.g. ANDINA-B.SN)."""
    try:
        t = yf.Ticker(yf_ticker)
        hist = t.history(period=f"{years}y", interval="1d", auto_adjust=False)
        if isinstance(hist, pd.DataFrame) and not hist.empty:
            if "Close" not in hist.columns:
                close_cols = [c for c in hist.columns if str(c).lower() == "close"]
                if close_cols:
                    hist["Close"] = hist[close_cols[0]]
            return hist[["Close"]].dropna()
    except Exception:
        pass
    return pd.DataFrame(columns=["Close"])


# =========================================================
# Página principal — Buscador CL
# =========================================================

def page_buscador_cl() -> None:
    """Entry point for the Chilean Stocks Buscador page."""
    admin = is_admin()

    # --- CSS (reuses same styles as page_analysis) ---
    st.markdown(
        """
        <style>
        .kpis-container {
            background: transparent;
            border-radius: 0;
            padding: 0;
            box-shadow: none;
            margin-bottom: 16px;
        }
        .kpi-card {
          background: transparent;
          border-radius: 10px;
          padding: 12px;
          display: block;
          margin-bottom: 8px;
        }
        .kpi-label { font-size: 0.78rem; color: #ffffff; margin-bottom:6px; }
        .kpi-value { font-size: 1.4rem; font-weight:700; color: #01c2ef; }
        .stMetric { background: transparent; }
        div[data-testid="stPlotlyChart"] { box-shadow: none !important; }
        .logo-circle {
            width: 85px;
            height: 85px;
            border-radius: 12px;
            background-color: #ffffff;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 10px;
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

    # --- Selector de ticker ---
    available_tickers = get_cl_tickers_list()

    if not available_tickers:
        st.warning("No hay tickers chilenos disponibles en el mapa.")
        return

    # Restore previous selection or default to ANDINA-B
    default_ticker = "ANDINA-B" if "ANDINA-B" in available_tickers else available_tickers[0]
    prev_selection = st.session_state.get("cl_ticker", default_ticker)
    default_idx = available_tickers.index(prev_selection) if prev_selection in available_tickers else 0

    c_left, c_mid, c_right = st.columns([1, 2, 1])
    with c_mid:
        selected = st.selectbox(
            "Seleccione un ticker chileno:",
            available_tickers,
            index=default_idx,
            key="cl_ticker_selector",
        )
        st.session_state["cl_ticker"] = selected

    cl_ticker = st.session_state.get("cl_ticker", "")
    if not cl_ticker:
        st.info("Seleccione un ticker chileno para comenzar.")
        return

    # --- Validar ---
    if not is_cl_ticker(cl_ticker):
        st.error(f"Ticker '{cl_ticker}' no encontrado en el mapa de empresas chilenas.")
        return

    # --- Datos base ---
    company_name = get_cl_company_name(cl_ticker)
    yf_ticker = get_cl_yf_ticker(cl_ticker)

    # Precio desde YF (con .SN)
    price_data = get_price_data(yf_ticker) or {}
    last_price = price_data.get("last_price")
    currency = price_data.get("currency") or "CLP"

    # Estados financieros desde CSVs
    financial_data = load_cl_financial_statements(cl_ticker)

    # Intento de obtener logo via YF info
    logo_url = ""
    try:
        info = _load_ticker_info(yf_ticker)
        website = info.get("website") or ""
        if website:
            logos = logo_candidates(website)
            logo_url = next(
                (u for u in logos if isinstance(u, str) and u.startswith(("http://", "https://"))),
                "",
            )
    except Exception:
        logo_url = ""

    # --- Encabezado ---
    left, right = st.columns([1.15, 0.85], gap="large")
    with left:
        c_logo, c_text = st.columns([0.12, 0.88], gap="small", vertical_alignment="center")
        with c_logo:
            if logo_url:
                st.markdown(
                    f'<div class="logo-circle"><img src="{logo_url}" /></div>',
                    unsafe_allow_html=True,
                )
        with c_text:
            st.markdown(f"### {cl_ticker} — {company_name}")
            if last_price:
                st.markdown(f"## {last_price:,.2f} {currency}")
            else:
                st.markdown("## Precio no disponible")

    # KPIs calculados desde CSVs + precio YF
    with right:
        st.markdown("### KPIs clave")
        st.markdown('<div class="kpis-container">', unsafe_allow_html=True)

        income_df_raw = financial_data.get("income_stmt", pd.DataFrame())
        balance_df_raw = financial_data.get("balance_sheet", pd.DataFrame())

        try:
            kpi_cols = st.columns(4, gap="large")

            # EPS = Net Income (último año) — shares not available → show Net Income
            eps_val = None
            if not income_df_raw.empty:
                for col in income_df_raw.index:
                    if "net income" in str(col).lower():
                        ni_row = pd.to_numeric(income_df_raw.loc[col], errors="coerce").dropna()
                        if not ni_row.empty:
                            eps_val = ni_row.iloc[-1]
                        break

            # PER = Price / EPS (only meaningful if EPS per share available)
            with kpi_cols[0]:
                _kpi_card("Utilidad Neta", _fmt_large_number(eps_val) if eps_val is not None else "N/D")

            # Total Equity
            eq_val = None
            if not balance_df_raw.empty:
                for col in balance_df_raw.index:
                    if "total equity" in str(col).lower():
                        eq_row = pd.to_numeric(balance_df_raw.loc[col], errors="coerce").dropna()
                        if not eq_row.empty:
                            eq_val = eq_row.iloc[-1]
                        break

            with kpi_cols[1]:
                _kpi_card("Patrimonio", _fmt_large_number(eq_val) if eq_val is not None else "N/D")

            # Total Revenue
            rev_val = None
            if not income_df_raw.empty:
                for col in income_df_raw.index:
                    if "total revenue" in str(col).lower():
                        rev_row = pd.to_numeric(income_df_raw.loc[col], errors="coerce").dropna()
                        if not rev_row.empty:
                            rev_val = rev_row.iloc[-1]
                        break

            with kpi_cols[2]:
                _kpi_card("Ingresos", _fmt_large_number(rev_val) if rev_val is not None else "N/D")

            # Free Cash Flow
            fcf_val = None
            cashflow_df_raw = financial_data.get("cashflow", pd.DataFrame())
            if not cashflow_df_raw.empty:
                for col in cashflow_df_raw.index:
                    if "free cash flow" in str(col).lower():
                        fcf_row = pd.to_numeric(cashflow_df_raw.loc[col], errors="coerce").dropna()
                        if not fcf_row.empty:
                            fcf_val = fcf_row.iloc[-1]
                        break

            with kpi_cols[3]:
                _kpi_card("FCF", _fmt_large_number(fcf_val) if fcf_val is not None else "N/D")

        except Exception:
            pass

        st.markdown("</div>", unsafe_allow_html=True)

    st.divider()

    # --- Routing por sección ---
    selected_section = st.session_state.get("analysis_section", "Resumen")

    if selected_section == "Resumen":
        _render_cl_resumen(yf_ticker)

    elif selected_section == "Dividendos":
        _render_cl_dividends(cl_ticker, yf_ticker, financial_data)

    elif selected_section == "Balance":
        st.markdown("## Balance")
        balance_df = _prepare_financial_df(financial_data["balance_sheet"], YEARS)
        if balance_df.empty:
            st.warning("No hay datos de balance disponibles para este ticker.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                _plot_assets_evolution(cl_ticker, balance_df)
                _plot_debt_evolution(cl_ticker, balance_df)
            with col2:
                _plot_liabilities_evolution(cl_ticker, balance_df)
                _plot_equity_evolution(cl_ticker, balance_df)

    elif selected_section == "EERR":
        st.markdown("## Estado de Resultados")
        income_df = _prepare_financial_df(financial_data["income_stmt"], YEARS)
        if income_df.empty:
            st.warning("No hay datos de estado de resultados disponibles para este ticker.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                _plot_revenue_evolution(cl_ticker, income_df)
                _plot_eps_evolution(cl_ticker, income_df)
            with col2:
                _plot_margins_evolution(cl_ticker, income_df)
                _plot_shares_outstanding(cl_ticker, income_df)

    elif selected_section == "EFE":
        st.markdown("## Estado de Flujo de Efectivo")
        cashflow_df = _prepare_financial_df(financial_data["cashflow"], YEARS)
        if cashflow_df.empty:
            st.warning("No hay datos de flujo de efectivo disponibles para este ticker.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                _plot_cashflow_vs_capex(cl_ticker, cashflow_df)
                _plot_debt_repayment(cl_ticker, cashflow_df)
            with col2:
                _plot_debt_issuance(cl_ticker, cashflow_df)
                _plot_share_buybacks(cl_ticker, cashflow_df)

    elif selected_section == "Valoración por múltiplos":
        st.markdown("## Valoración por múltiplos")
        balance_df = _prepare_financial_df(financial_data["balance_sheet"], YEARS)
        income_df = _prepare_financial_df(financial_data["income_stmt"], YEARS)
        cashflow_df = _prepare_financial_df(financial_data["cashflow"], YEARS)
        info = _load_ticker_info(yf_ticker)

        if balance_df.empty and income_df.empty and cashflow_df.empty:
            st.warning("No hay datos financieros suficientes para la valoración por múltiplos.")
        else:
            sub_tabs = st.tabs([
                "💰 Evolución de la Deuda",
                "📊 Evolución del PER",
                "📈 Evolución EV/EBITDA",
                "📊 Uso del FC",
                "📊 Valoración Gurufocus",
            ])
            with sub_tabs[0]:
                if not balance_df.empty and not cashflow_df.empty:
                    _plot_debt_fcf_evolution(cl_ticker, balance_df, cashflow_df)
                else:
                    st.warning("No hay datos suficientes de balance y flujo de efectivo para este análisis.")
            with sub_tabs[1]:
                if not income_df.empty:
                    _plot_per_evolution(yf_ticker, income_df, info)
                else:
                    st.warning("No hay datos suficientes de estado de resultados para este análisis.")
            with sub_tabs[2]:
                if not income_df.empty and not balance_df.empty:
                    _plot_ev_ebitda_evolution(yf_ticker, income_df, balance_df, info)
                else:
                    st.warning("No hay datos suficientes para este análisis.")
            with sub_tabs[3]:
                if not cashflow_df.empty:
                    _plot_fc_usage(cl_ticker, cashflow_df)
                else:
                    st.warning("No hay datos suficientes de flujo de efectivo para este análisis.")
            with sub_tabs[4]:
                _render_gurufocus_valuation_charts(cl_ticker)

    elif selected_section == "Pizarra de Valoración":
        if not admin:
            st.warning("Esta sección es solo para administradores.")
            return
        st.markdown("## Pizarra de Valoración")
        if not logo_url:
            st.warning(
                "No se pudo obtener el logo de la empresa. "
                "La funcionalidad de la pizarra requiere un logo válido."
            )
        else:
            _render_interactive_valuation_board(cl_ticker, logo_url)

    elif selected_section == "Análisis Razonado":
        st.markdown("## Análisis Razonado")
        balance_df = _prepare_financial_df(financial_data["balance_sheet"], YEARS)
        income_df = _prepare_financial_df(financial_data["income_stmt"], YEARS)
        cashflow_df = _prepare_financial_df(financial_data["cashflow"], YEARS)

        if balance_df.empty and income_df.empty:
            st.warning("No hay datos financieros suficientes para el análisis razonado.")
        else:
            ratios = _calculate_financial_ratios(balance_df, income_df, cashflow_df, cl_ticker)

            if ratios.empty:
                st.info("No se pudieron calcular ratios financieros con los datos disponibles.")
            else:
                ratio_cols = list(ratios.columns)
                if not ratio_cols:
                    st.info("No se pudieron calcular ratios financieros con los datos disponibles.")
                else:
                    ratios_transposed = ratios.T
                    session_key = f"selected_ratio_{cl_ticker}"
                    if session_key not in st.session_state or st.session_state[session_key] not in ratio_cols:
                        st.session_state[session_key] = ratio_cols[0]

                    col_table, col_chart = st.columns([1, 1])
                    with col_table:
                        st.markdown("### Métricas Financieras")
                        display_df = ratios_transposed.copy()
                        try:
                            display_df = display_df.map(
                                lambda x: f"{x:.2f}" if pd.notna(x) else "N/D"
                            )
                        except AttributeError:
                            display_df = display_df.applymap(
                                lambda x: f"{x:.2f}" if pd.notna(x) else "N/D"
                            )
                        st.dataframe(display_df, use_container_width=True, height=400)
                        st.markdown("**Seleccione una métrica para visualizar:**")
                        default_index = ratio_cols.index(st.session_state[session_key])
                        selected_metric = st.selectbox(
                            "Métrica",
                            ratio_cols,
                            index=default_index,
                            key=f"ratio_selector_{cl_ticker}",
                            label_visibility="collapsed",
                        )
                        st.session_state[session_key] = selected_metric

                    with col_chart:
                        st.markdown("### Gráfico de Evolución")
                        selected_ratio_name = st.session_state[session_key]
                        selected_ratio_data = ratios[selected_ratio_name]
                        _plot_ratio_evolution(cl_ticker, selected_ratio_name, selected_ratio_data)


def _render_cl_resumen(yf_ticker: str) -> None:
    """Render Resumen section for CL ticker: price variation, drawdown and 52w range."""
    st.markdown("## Análisis de Precio")
    col1, col2 = st.columns(2)
    with col1:
        _plot_price_variation_5y(yf_ticker)
    with col2:
        _plot_drawdown(yf_ticker)

    st.markdown("### Rango 52 Semanas")
    range_data = get_52w_range(yf_ticker)
    _render_52w_gauge(
        yf_ticker,
        range_data.get("current_price"),
        range_data.get("low_52w"),
        range_data.get("high_52w"),
    )


def _render_cl_dividends(cl_ticker: str, yf_ticker: str, financial_data: Dict[str, Any]) -> None:
    """Render Dividendos section for CL ticker: evolution, safety and Geraldine Weiss."""
    st.markdown("## Valoración por dividendo")

    price_daily = _load_cl_price_daily(yf_ticker, YEARS)
    dividends = load_cl_dividends(cl_ticker)
    cashflow_raw = financial_data.get("cashflow", pd.DataFrame())

    sub_tabs = st.tabs([
        "📈 Evolución del dividendo",
        "🛡️ Seguridad del dividendo",
        "📌 Geraldine Weiss",
    ])
    with sub_tabs[0]:
        _plot_dividend_evolution(cl_ticker, price_daily, dividends, years=None)
    with sub_tabs[1]:
        # _plot_dividend_safety expects raw cashflow (accounts as index, year cols)
        # which is exactly what load_cl_financial_statements returns
        _plot_dividend_safety(cl_ticker, cashflow_raw, years=None)
    with sub_tabs[2]:
        _plot_geraldine_weiss(cl_ticker, price_daily, dividends)
