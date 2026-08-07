# src/pages/buscador_cl.py
"""
Página principal del Buscador CL.

Usa la nueva arquitectura de módulos Chile para cargar datos, normalizar EEFF,
calcular métricas y renderizar gráficos según el tipo de empresa chilena.

Importa funciones de analysis.py solo para componentes visuales genéricos
(formateo, tablas, gráficos de precio) que no tienen lógica financiera chilena.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st

from src.auth import is_admin

# --- Componentes visuales genéricos de analysis.py (solo UI, sin lógica financiera chilena) ---
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
    _render_financial_table_expander,
    _calculate_financial_ratios,
    _render_52w_gauge,
    _render_gurufocus_valuation_charts,
    _render_interactive_valuation_board,
    YEARS,
)

# --- Capa de datos Chile ---
from src.services.chile_data import (
    get_cl_company_name,
    get_cl_tickers_list,
    get_cl_yf_ticker,
    is_cl_ticker,
    load_cl_dividends,
    load_chile_financials_bundle,
    get_metrics_cl,
    get_chart_data_cl,
)

# --- Perfil de empresa chilena ---
from src.services.chile_profiles import (
    get_company_profile_cl,
    get_profile_type_cl,
    get_reporting_metadata_cl,
)

# --- Gráficos Chile ---
from src.services.chile_charts import get_charts_for_profile_cl

from src.services.finance_data import get_price_data, get_52w_range, get_price_history
from src.services.logos import logo_candidates

# Etiquetas amigables para cada tipo de perfil
_PROFILE_LABELS: dict[str, str] = {
    "normal": "🏭 Empresa Normal",
    "utility": "⚡ Utility / Regulada",
    "reit_concesion": "🏢 REIT / Concesión",
    "financiera": "🏦 Financiera / AFP",
}


# =========================================================
# Helpers
# =========================================================

def _load_cl_price_daily(yf_ticker: str, years: int = YEARS) -> pd.DataFrame:
    """Fetch daily price history from YF for the CL ticker (e.g. ANDINA-B.SN)."""
    return get_price_history(yf_ticker, period=f"{years}y", interval="1d", auto_adjust=False)


# =========================================================
# Página principal — Buscador CL
# =========================================================

def page_buscador_cl() -> None:
    """Entry point for the Chilean Stocks Buscador page."""
    admin = is_admin()

    # --- CSS ---
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
        .profile-badge {
            display: inline-block;
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 0.8rem;
            font-weight: 600;
            background: rgba(1,194,239,0.15);
            color: #01c2ef;
            border: 1px solid rgba(1,194,239,0.4);
            margin-top: 4px;
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

    # --- Cargar perfil y datos normalizados ---
    profile = get_company_profile_cl(cl_ticker)
    profile_type = profile.get("profile_type", "normal")
    meta = get_reporting_metadata_cl(cl_ticker)
    moneda = meta.get("moneda_reporte", "CLP")

    company_name = get_cl_company_name(cl_ticker)
    yf_ticker = get_cl_yf_ticker(cl_ticker)

    # Precio desde YF (con .SN)
    price_data = get_price_data(yf_ticker) or {}
    last_price = price_data.get("last_price")
    currency = price_data.get("currency") or moneda

    # Bundle normalizado para métricas y gráficos Chile.
    # Los datos crudos (balance_raw, income_raw, cashflow_raw) son equivalentes
    # a lo que retornaba load_cl_financial_statements(), evitando una carga doble.
    try:
        bundle = load_chile_financials_bundle(cl_ticker)
        balance_norm = bundle["balance_norm"]
        income_norm = bundle["income_norm"]
        cashflow_norm = bundle["cashflow_norm"]
        derived = bundle["derived"]
        # financial_data mantiene la misma interfaz que usaba load_cl_financial_statements()
        financial_data = {
            "balance_sheet": bundle["balance_raw"],
            "income_stmt": bundle["income_raw"],
            "cashflow": bundle["cashflow_raw"],
        }
    except Exception:
        bundle = None
        balance_norm = pd.DataFrame()
        income_norm = pd.DataFrame()
        cashflow_norm = pd.DataFrame()
        derived = {}
        financial_data = {"balance_sheet": pd.DataFrame(), "income_stmt": pd.DataFrame(), "cashflow": pd.DataFrame()}

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
            # Mostrar badge de perfil
            profile_label = _PROFILE_LABELS.get(profile_type, profile_type)
            sector = meta.get("sector", "")
            sector_txt = f" · {sector}" if sector else ""
            st.markdown(
                f'<span class="profile-badge">{profile_label}{sector_txt}</span>',
                unsafe_allow_html=True,
            )

    # --- KPIs desde datos normalizados ---
    with right:
        st.markdown("### KPIs clave")
        st.markdown('<div class="kpis-container">', unsafe_allow_html=True)

        try:
            kpi_cols = st.columns(4, gap="large")
            market_data_for_kpi = {"last_price": last_price, "currency": currency}

            from src.services.chile_metrics import compute_metrics_cl
            kpi_metrics = compute_metrics_cl(
                balance_norm, income_norm, cashflow_norm, derived,
                profile_type, market_data_for_kpi
            ) if bundle is not None else {}

            # KPI 1: Utilidad Neta (o EBITDA para utilities)
            with kpi_cols[0]:
                if profile_type in ("utility", "reit_concesion") and "ebitda_ultimo" in kpi_metrics:
                    _kpi_card("EBITDA", _fmt_large_number(kpi_metrics["ebitda_ultimo"]))
                elif "ganancia_neta_ultima" in kpi_metrics:
                    _kpi_card("Utilidad Neta", _fmt_large_number(kpi_metrics["ganancia_neta_ultima"]))
                else:
                    _kpi_card("Utilidad Neta", "N/D")

            # KPI 2: Patrimonio (o ROE para financieras)
            with kpi_cols[1]:
                if profile_type == "financiera" and "roe_ultimo" in kpi_metrics:
                    roe_val = kpi_metrics["roe_ultimo"]
                    _kpi_card("ROE", f"{roe_val * 100:.1f}%" if roe_val else "N/D")
                elif "patrimonio_ultimo" in kpi_metrics:
                    _kpi_card("Patrimonio", _fmt_large_number(kpi_metrics["patrimonio_ultimo"]))
                else:
                    _kpi_card("Patrimonio", "N/D")

            # KPI 3: Ingresos
            with kpi_cols[2]:
                if "ingresos_ultimo" in kpi_metrics:
                    _kpi_card("Ingresos", _fmt_large_number(kpi_metrics["ingresos_ultimo"]))
                else:
                    _kpi_card("Ingresos", "N/D")

            # KPI 4: FCL (o Deuda Neta / EBITDA para utilities)
            with kpi_cols[3]:
                if profile_type == "utility" and "deuda_neta_ebitda_ultimo" in kpi_metrics:
                    dn_eb = kpi_metrics["deuda_neta_ebitda_ultimo"]
                    _kpi_card("DN/EBITDA", f"{dn_eb:.2f}x" if dn_eb else "N/D")
                elif "flujo_libre_de_caja_ultimo" in kpi_metrics:
                    _kpi_card("FCL", _fmt_large_number(kpi_metrics["flujo_libre_de_caja_ultimo"]))
                else:
                    _kpi_card("FCL", "N/D")

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
        if balance_norm.empty:
            st.warning("No hay datos de balance disponibles para este ticker.")
        else:
            col1, col2 = st.columns(2)
            balance_df = _prepare_financial_df(balance_norm, YEARS)
            with col1:
                _plot_assets_evolution(cl_ticker, balance_df)
                _plot_debt_evolution(cl_ticker, balance_df)
            with col2:
                _plot_liabilities_evolution(cl_ticker, balance_df)
                _plot_equity_evolution(cl_ticker, balance_df)
            _render_financial_table_expander("📋 Ver tabla Balance", balance_norm)

    elif selected_section == "EERR":
        st.markdown("## Estado de Resultados")
        if income_norm.empty:
            st.warning("No hay datos de estado de resultados disponibles para este ticker.")
        else:
            col1, col2 = st.columns(2)
            income_df = _prepare_financial_df(income_norm, YEARS)
            with col1:
                _plot_revenue_evolution(cl_ticker, income_df)
                _plot_eps_evolution(cl_ticker, income_df)
            with col2:
                _plot_margins_evolution(cl_ticker, income_df)
                _plot_shares_outstanding(cl_ticker, income_df)
            _render_financial_table_expander("📋 Ver tabla Estado de Resultados", income_norm)

    elif selected_section == "EFE":
        st.markdown("## Estado de Flujo de Efectivo")
        if cashflow_norm.empty:
            st.warning("No hay datos de flujo de efectivo disponibles para este ticker.")
        else:
            col1, col2 = st.columns(2)
            cashflow_df = _prepare_financial_df(cashflow_norm, YEARS)
            with col1:
                _plot_cashflow_vs_capex(cl_ticker, cashflow_df)
                _plot_debt_repayment(cl_ticker, cashflow_df)
            with col2:
                _plot_debt_issuance(cl_ticker, cashflow_df)
                _plot_share_buybacks(cl_ticker, cashflow_df)
            _render_financial_table_expander("📋 Ver tabla Flujo de Efectivo", cashflow_norm)

    elif selected_section == "Valoración por múltiplos":
        _render_cl_valoracion(
            cl_ticker, yf_ticker,
            balance_norm, income_norm, cashflow_norm, derived,
            profile_type, moneda,
        )

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
        _render_cl_analisis_razonado(cl_ticker, financial_data, balance_norm, income_norm, cashflow_norm, derived, profile_type)




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


def _render_cl_valoracion(
    cl_ticker: str,
    yf_ticker: str,
    balance_norm: pd.DataFrame,
    income_norm: pd.DataFrame,
    cashflow_norm: pd.DataFrame,
    derived: dict,
    profile_type: str,
    moneda: str,
) -> None:
    """
    Renderiza la sección de Valoración por múltiplos para empresas chilenas.

    Para perfiles que lo admiten (normal, utility), incluye PER y EV/EBITDA.
    Para REIT y financieras, omite ratios que no aplican y muestra métricas Chile.
    """
    st.markdown("## Valoración por múltiplos")

    # Tabs que aplican a todos
    tab_labels = ["💰 Métricas CL", "💰 Evolución de la Deuda", "📊 Uso del FC", "📊 Valoración Gurufocus"]
    # Agregar PER y EV/EBITDA solo para perfiles donde tiene sentido
    if profile_type in ("normal",):
        tab_labels.insert(1, "📊 Evolución del PER")
        tab_labels.insert(2, "📈 Evolución EV/EBITDA")
    elif profile_type == "utility":
        tab_labels.insert(1, "📈 Evolución EV/EBITDA")

    sub_tabs = st.tabs(tab_labels)
    tab_idx = 0

    # Tab: Métricas CL
    with sub_tabs[tab_idx]:
        st.markdown(f"### Métricas Chile — {_PROFILE_LABELS.get(profile_type, profile_type)}")
        if balance_norm.empty and income_norm.empty:
            st.warning("No hay datos normalizados disponibles para métricas Chile.")
        else:
            try:
                from src.services.chile_metrics import compute_metrics_cl
                metrics = compute_metrics_cl(
                    balance_norm, income_norm, cashflow_norm, derived, profile_type
                )
                # Mostrar métricas escalares en tabla
                scalar_metrics = {
                    k: v for k, v in metrics.items()
                    if not isinstance(v, pd.Series) and v is not None
                }
                if scalar_metrics:
                    df_m = pd.DataFrame.from_dict(scalar_metrics, orient="index", columns=["Valor"])
                    df_m.index.name = "Métrica"
                    try:
                        df_m["Valor"] = df_m["Valor"].apply(
                            lambda x: f"{x:.4f}" if isinstance(x, float) else str(x)
                        )
                    except Exception:
                        pass
                    st.dataframe(df_m, use_container_width=True)
                else:
                    st.info("No se calcularon métricas con los datos disponibles.")

                # Gráficos Chile
                charts = get_charts_for_profile_cl(cl_ticker, metrics, profile_type, moneda)
                if charts:
                    import plotly.graph_objects as go
                    chart_names = list(charts.keys())
                    col1, col2 = st.columns(2)
                    for i, name in enumerate(chart_names):
                        fig = charts[name]
                        if fig is not None:
                            with (col1 if i % 2 == 0 else col2):
                                st.plotly_chart(fig, use_container_width=True)
            except Exception as e:
                st.warning(f"Error al calcular métricas Chile: {e}")
    tab_idx += 1

    # Tab: PER (solo normal)
    if profile_type == "normal":
        with sub_tabs[tab_idx]:
            income_df = _prepare_financial_df(income_norm, YEARS)
            if not income_df.empty:
                info = _load_ticker_info(yf_ticker)
                _plot_per_evolution(yf_ticker, income_df, info)
            else:
                st.warning("No hay datos suficientes de EERR para este análisis.")
        tab_idx += 1

    # Tab: EV/EBITDA (normal y utility)
    if profile_type in ("normal", "utility"):
        with sub_tabs[tab_idx]:
            income_df = _prepare_financial_df(income_norm, YEARS)
            balance_df = _prepare_financial_df(balance_norm, YEARS)
            if not income_df.empty and not balance_df.empty:
                info = _load_ticker_info(yf_ticker)
                _plot_ev_ebitda_evolution(yf_ticker, income_df, balance_df, info)
            else:
                st.warning("No hay datos suficientes para este análisis.")
        tab_idx += 1

    # Tab: Evolución de la Deuda
    with sub_tabs[tab_idx]:
        balance_df = _prepare_financial_df(balance_norm, YEARS)
        cashflow_df = _prepare_financial_df(cashflow_norm, YEARS)
        if not balance_df.empty and not cashflow_df.empty:
            _plot_debt_fcf_evolution(cl_ticker, balance_df, cashflow_df)
        else:
            st.warning("No hay datos suficientes de balance y flujo de efectivo para este análisis.")
    tab_idx += 1

    # Tab: Uso del FC
    with sub_tabs[tab_idx]:
        cashflow_df = _prepare_financial_df(cashflow_norm, YEARS)
        if not cashflow_df.empty:
            _plot_fc_usage(cl_ticker, cashflow_df)
        else:
            st.warning("No hay datos suficientes de flujo de efectivo para este análisis.")
    tab_idx += 1

    # Tab: Valoración Gurufocus
    with sub_tabs[tab_idx]:
        _render_gurufocus_valuation_charts(cl_ticker)


def _render_cl_analisis_razonado(
    cl_ticker: str,
    financial_data: Dict[str, Any],
    balance_norm: pd.DataFrame,
    income_norm: pd.DataFrame,
    cashflow_norm: pd.DataFrame,
    derived: dict,
    profile_type: str,
) -> None:
    """
    Renderiza la sección de Análisis Razonado para empresas chilenas.

    Muestra métricas Chile normalizadas y ratios calculados con la lógica
    del perfil de empresa.
    """
    st.markdown("## Análisis Razonado")

    # Intentar métricas Chile primero
    if not balance_norm.empty or not income_norm.empty:
        try:
            from src.services.chile_metrics import compute_metrics_cl
            metrics = compute_metrics_cl(
                balance_norm, income_norm, cashflow_norm, derived, profile_type
            )
            series_metrics = {
                k: v for k, v in metrics.items()
                if isinstance(v, pd.Series) and not v.empty
            }

            if series_metrics:
                st.markdown(f"### Métricas por perfil: {_PROFILE_LABELS.get(profile_type, profile_type)}")
                metric_names = list(series_metrics.keys())

                # Tabla de métricas series
                rows = {}
                for name, s in series_metrics.items():
                    s_clean = pd.to_numeric(s, errors="coerce")
                    rows[name] = s_clean
                df_series = pd.DataFrame(rows)
                df_series.index.name = "Año"

                try:
                    df_display = df_series.T.map(lambda x: f"{x:.4f}" if pd.notna(x) else "N/D")
                except AttributeError:
                    df_display = df_series.T.applymap(lambda x: f"{x:.4f}" if pd.notna(x) else "N/D")

                col_table, col_chart = st.columns([1, 1])
                with col_table:
                    st.dataframe(df_display, use_container_width=True, height=400)
                    st.markdown("**Seleccione una métrica para visualizar:**")
                    session_key = f"cl_metric_{cl_ticker}"
                    if session_key not in st.session_state or st.session_state[session_key] not in metric_names:
                        st.session_state[session_key] = metric_names[0]
                    default_index = metric_names.index(st.session_state[session_key])
                    selected_metric = st.selectbox(
                        "Métrica CL",
                        metric_names,
                        index=default_index,
                        key=f"cl_metric_selector_{cl_ticker}",
                        label_visibility="collapsed",
                    )
                    st.session_state[session_key] = selected_metric

                with col_chart:
                    st.markdown("### Gráfico de Evolución")
                    selected_series = series_metrics[selected_metric]
                    _plot_ratio_evolution(cl_ticker, selected_metric, selected_series)

                return
        except Exception:
            pass

    # Fallback: usar ratios del análisis EEUU si los normalizados no están disponibles
    balance_df = _prepare_financial_df(financial_data["balance_sheet"], YEARS)
    income_df = _prepare_financial_df(financial_data["income_stmt"], YEARS)
    cashflow_df = _prepare_financial_df(financial_data["cashflow"], YEARS)

    if balance_df.empty and income_df.empty:
        st.warning("No hay datos financieros suficientes para el análisis razonado.")
        return

    ratios = _calculate_financial_ratios(balance_df, income_df, cashflow_df, cl_ticker)

    if ratios.empty:
        st.info("No se pudieron calcular ratios financieros con los datos disponibles.")
        return

    ratio_cols = list(ratios.columns)
    if not ratio_cols:
        st.info("No se pudieron calcular ratios financieros con los datos disponibles.")
        return

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
