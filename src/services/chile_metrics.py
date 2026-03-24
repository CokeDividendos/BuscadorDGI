# src/services/chile_metrics.py
"""
Cálculo de métricas financieras para empresas chilenas.

Las métricas se calculan según el profile_type de la empresa:
- normal: PER, EV/EBITDA, márgenes, ROE, ROIC, deuda neta, FCF
- utility: EBITDA, cobertura, capex vs. FCF, deuda neta/EBITDA
- reit_concesion: FFO aproximado, payout flujo, yield histórico
- financiera: ROE, P/B, payout utilidad, valor libro por acción

Todas las funciones manejan datos faltantes y divisiones por cero de
forma elegante, retornando None o diccionarios parciales cuando
la información no es suficiente.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------


def _safe_div(numerator: Any, denominator: Any) -> Optional[float]:
    """División segura que retorna None en caso de error o div/0."""
    try:
        num = float(numerator)
        den = float(denominator)
        if den == 0 or np.isnan(den) or np.isnan(num):
            return None
        return num / den
    except (TypeError, ValueError):
        return None


def _get_latest(series: Optional[pd.Series]) -> Optional[float]:
    """Retorna el valor más reciente (primer elemento) de una serie temporal."""
    if series is None:
        return None
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return None
    return float(s.iloc[0])


def _get_series_values(series: Optional[pd.Series]) -> pd.Series:
    """Retorna serie numérica limpia o vacía."""
    if series is None:
        return pd.Series(dtype=float)
    return pd.to_numeric(series, errors="coerce").dropna()


def _row(df: pd.DataFrame, account: str) -> Optional[pd.Series]:
    """Retorna fila del DataFrame o None si la cuenta no existe."""
    if df is None or df.empty or account not in df.index:
        return None
    return df.loc[account]


# ---------------------------------------------------------------------------
# Métricas comunes (aplicables a todos los perfiles)
# ---------------------------------------------------------------------------


def compute_common_metrics_cl(
    balance_df: pd.DataFrame,
    income_df: pd.DataFrame,
    cashflow_df: pd.DataFrame,
    derived: dict,
    market_data: Optional[dict] = None,
) -> dict:
    """
    Calcula métricas financieras comunes para cualquier tipo de empresa chilena.

    Args:
        balance_df: Balance normalizado (cuentas canónicas como índice).
        income_df: EERR normalizado.
        cashflow_df: EFE normalizado.
        derived: Dict con cuentas derivadas (de derive_missing_accounts_cl).
        market_data: Dict con datos de mercado (precio, shares, market_cap, etc.).

    Returns:
        Dict con métricas calculadas. Las métricas no disponibles se omiten.
    """
    md = market_data or {}
    metrics: dict = {}

    # Ingresos
    ingresos = _row(income_df, "ingresos")
    if ingresos is not None:
        metrics["ingresos_series"] = _get_series_values(ingresos)
        metrics["ingresos_ultimo"] = _get_latest(ingresos)

    # Ganancia neta
    ganancia = _row(income_df, "ganancia_neta")
    if ganancia is None:
        ganancia = _row(income_df, "ganancia_neta_controladora")
    if ganancia is not None:
        metrics["ganancia_neta_series"] = _get_series_values(ganancia)
        metrics["ganancia_neta_ultima"] = _get_latest(ganancia)

    # EBITDA
    ebitda_row = _row(income_df, "ebitda")
    if ebitda_row is None and "ebitda" in derived:
        ebitda_row = derived["ebitda"]
    if ebitda_row is not None:
        metrics["ebitda_series"] = _get_series_values(ebitda_row)
        metrics["ebitda_ultimo"] = _get_latest(ebitda_row)

    # EBIT
    ebit_row = _row(income_df, "ebit")
    if ebit_row is None and "ebit" in derived:
        ebit_row = derived["ebit"]
    if ebit_row is not None:
        metrics["ebit_series"] = _get_series_values(ebit_row)
        metrics["ebit_ultimo"] = _get_latest(ebit_row)

    # Patrimonio total
    patrimonio = _row(balance_df, "patrimonio_total")
    if patrimonio is not None:
        metrics["patrimonio_series"] = _get_series_values(patrimonio)
        metrics["patrimonio_ultimo"] = _get_latest(patrimonio)

    # Activos totales
    activos = _row(balance_df, "activos_totales")
    if activos is not None:
        metrics["activos_totales_series"] = _get_series_values(activos)
        metrics["activos_totales_ultimo"] = _get_latest(activos)

    # Deuda financiera total
    deuda_cp = _row(balance_df, "deuda_financiera_corto_plazo")
    deuda_lp = _row(balance_df, "deuda_financiera_largo_plazo")
    deuda_total_row = derived.get("deuda_financiera_total")

    if deuda_total_row is not None:
        metrics["deuda_financiera_total_series"] = _get_series_values(deuda_total_row)
        metrics["deuda_financiera_total_ultima"] = _get_latest(deuda_total_row)

    # Efectivo
    efectivo = _row(balance_df, "efectivo_y_equivalentes")
    if efectivo is not None:
        metrics["efectivo_series"] = _get_series_values(efectivo)
        metrics["efectivo_ultimo"] = _get_latest(efectivo)

    # Deuda neta = deuda_total - efectivo
    if deuda_total_row is not None and efectivo is not None:
        try:
            deuda_neta = _get_series_values(deuda_total_row) - _get_series_values(efectivo)
            metrics["deuda_neta_series"] = deuda_neta
            metrics["deuda_neta_ultima"] = float(deuda_neta.iloc[0]) if not deuda_neta.empty else None
        except Exception:
            pass

    # Flujo operacional
    flujo_op = _row(cashflow_df, "flujo_operacional")
    if flujo_op is not None:
        metrics["flujo_operacional_series"] = _get_series_values(flujo_op)
        metrics["flujo_operacional_ultimo"] = _get_latest(flujo_op)

    # CAPEX
    capex = _row(cashflow_df, "capex")
    if capex is not None:
        metrics["capex_series"] = _get_series_values(capex)
        metrics["capex_ultimo"] = _get_latest(capex)

    # Flujo libre de caja
    fcf_row = _row(cashflow_df, "flujo_libre_de_caja")
    if fcf_row is None and "flujo_libre_de_caja" in derived:
        fcf_row = derived["flujo_libre_de_caja"]
    if fcf_row is not None:
        metrics["flujo_libre_de_caja_series"] = _get_series_values(fcf_row)
        metrics["flujo_libre_de_caja_ultimo"] = _get_latest(fcf_row)

    # Dividendos pagados
    dividendos = _row(cashflow_df, "dividendos_pagados")
    if dividendos is not None:
        metrics["dividendos_pagados_series"] = _get_series_values(dividendos).abs()
        _div_latest = _get_latest(dividendos)
        metrics["dividendos_pagados_ultimo"] = abs(_div_latest) if _div_latest is not None else None

    return metrics


# ---------------------------------------------------------------------------
# Métricas por perfil
# ---------------------------------------------------------------------------


def compute_normal_metrics_cl(
    balance_df: pd.DataFrame,
    income_df: pd.DataFrame,
    cashflow_df: pd.DataFrame,
    derived: dict,
    market_data: Optional[dict] = None,
) -> dict:
    """
    Calcula métricas para empresas de perfil 'normal' (consumo masivo, retail, etc.).

    Incluye: márgenes, ROE, ROA, ROIC, PER, EV/EBITDA, deuda neta,
    deuda neta/EBITDA, payout, liquidez corriente.

    Args:
        balance_df, income_df, cashflow_df: DataFrames normalizados.
        derived: Cuentas derivadas.
        market_data: Dict con precio, market_cap, shares_outstanding, etc.

    Returns:
        Dict con todas las métricas calculadas.
    """
    md = market_data or {}
    metrics = compute_common_metrics_cl(balance_df, income_df, cashflow_df, derived, md)

    # --- Márgenes ---
    ingresos_s = metrics.get("ingresos_series", pd.Series(dtype=float))
    ganancia_s = metrics.get("ganancia_neta_series", pd.Series(dtype=float))

    ganancia_bruta = _row(income_df, "ganancia_bruta")
    resultado_op = _row(income_df, "resultado_operacional")
    if resultado_op is None:
        resultado_op = _row(income_df, "ebit")

    if not ingresos_s.empty and ganancia_bruta is not None:
        try:
            gb_s = _get_series_values(ganancia_bruta)
            ing_aligned, gb_aligned = ingresos_s.align(gb_s, join="inner")
            metrics["margen_bruto_series"] = _safe_series_div(gb_aligned, ing_aligned)
            metrics["margen_bruto_ultimo"] = _get_latest(metrics["margen_bruto_series"])
        except Exception:
            pass

    if not ingresos_s.empty and resultado_op is not None:
        try:
            op_s = _get_series_values(resultado_op)
            ing_aligned, op_aligned = ingresos_s.align(op_s, join="inner")
            metrics["margen_operacional_series"] = _safe_series_div(op_aligned, ing_aligned)
            metrics["margen_operacional_ultimo"] = _get_latest(metrics["margen_operacional_series"])
        except Exception:
            pass

    if not ingresos_s.empty and not ganancia_s.empty:
        try:
            ing_aligned, gn_aligned = ingresos_s.align(ganancia_s, join="inner")
            metrics["margen_neto_series"] = _safe_series_div(gn_aligned, ing_aligned)
            metrics["margen_neto_ultimo"] = _get_latest(metrics["margen_neto_series"])
        except Exception:
            pass

    # --- ROE ---
    patrimonio_s = metrics.get("patrimonio_series", pd.Series(dtype=float))
    if not ganancia_s.empty and not patrimonio_s.empty:
        try:
            gn_aligned, pat_aligned = ganancia_s.align(patrimonio_s, join="inner")
            metrics["roe_series"] = _safe_series_div(gn_aligned, pat_aligned)
            metrics["roe_ultimo"] = _get_latest(metrics["roe_series"])
        except Exception:
            pass

    # --- ROA ---
    activos_s = metrics.get("activos_totales_series", pd.Series(dtype=float))
    if not ganancia_s.empty and not activos_s.empty:
        try:
            gn_aligned, act_aligned = ganancia_s.align(activos_s, join="inner")
            metrics["roa_series"] = _safe_series_div(gn_aligned, act_aligned)
            metrics["roa_ultimo"] = _get_latest(metrics["roa_series"])
        except Exception:
            pass

    # --- Deuda neta / EBITDA ---
    ebitda_s = metrics.get("ebitda_series", pd.Series(dtype=float))
    deuda_neta_s = metrics.get("deuda_neta_series", pd.Series(dtype=float))
    if not deuda_neta_s.empty and not ebitda_s.empty:
        try:
            dn_aligned, eb_aligned = deuda_neta_s.align(ebitda_s, join="inner")
            metrics["deuda_neta_ebitda_series"] = _safe_series_div(dn_aligned, eb_aligned)
            metrics["deuda_neta_ebitda_ultimo"] = _get_latest(metrics["deuda_neta_ebitda_series"])
        except Exception:
            pass

    # --- Liquidez corriente ---
    activos_corr = _row(balance_df, "activos_corrientes")
    pasivos_corr = _row(balance_df, "pasivos_corrientes")
    if activos_corr is not None and pasivos_corr is not None:
        try:
            ac_s = _get_series_values(activos_corr)
            pc_s = _get_series_values(pasivos_corr)
            ac_aligned, pc_aligned = ac_s.align(pc_s, join="inner")
            metrics["liquidez_corriente_series"] = _safe_series_div(ac_aligned, pc_aligned)
            metrics["liquidez_corriente_ultimo"] = _get_latest(metrics["liquidez_corriente_series"])
        except Exception:
            pass

    # --- Payout sobre utilidad ---
    dividendos_s = metrics.get("dividendos_pagados_series", pd.Series(dtype=float))
    if not dividendos_s.empty and not ganancia_s.empty:
        try:
            div_aligned, gn_aligned = dividendos_s.align(ganancia_s, join="inner")
            metrics["payout_utilidad_series"] = _safe_series_div(div_aligned, gn_aligned)
            metrics["payout_utilidad_ultimo"] = _get_latest(metrics["payout_utilidad_series"])
        except Exception:
            pass

    # --- Payout sobre FCL ---
    fcf_s = metrics.get("flujo_libre_de_caja_series", pd.Series(dtype=float))
    if not dividendos_s.empty and not fcf_s.empty:
        try:
            div_aligned, fcf_aligned = dividendos_s.align(fcf_s, join="inner")
            metrics["payout_fcl_series"] = _safe_series_div(div_aligned, fcf_aligned)
            metrics["payout_fcl_ultimo"] = _get_latest(metrics["payout_fcl_series"])
        except Exception:
            pass

    # --- EPS desde datos disponibles ---
    eps_metricas = compute_eps_series_cl(income_df, derived, md)
    metrics.update(eps_metricas)

    # --- PER ---
    per_metricas = compute_per_series_cl(income_df, derived, md)
    metrics.update(per_metricas)

    # --- EV/EBITDA ---
    ev_metricas = compute_ev_ebitda_series_cl(balance_df, income_df, derived, md)
    metrics.update(ev_metricas)

    return metrics


def compute_utility_metrics_cl(
    balance_df: pd.DataFrame,
    income_df: pd.DataFrame,
    cashflow_df: pd.DataFrame,
    derived: dict,
    market_data: Optional[dict] = None,
) -> dict:
    """
    Calcula métricas para empresas de perfil 'utility' (eléctricas, agua, etc.).

    Énfasis en EBITDA, cobertura de intereses, capex vs. flujo operacional,
    deuda neta/EBITDA y PPE como proporción de activos.
    El PER se incluye pero no es el múltiplo principal.

    Args:
        balance_df, income_df, cashflow_df: DataFrames normalizados.
        derived: Cuentas derivadas.
        market_data: Dict con datos de mercado.

    Returns:
        Dict con métricas calculadas.
    """
    md = market_data or {}
    metrics = compute_common_metrics_cl(balance_df, income_df, cashflow_df, derived, md)

    # --- Margen EBITDA ---
    ingresos_s = metrics.get("ingresos_series", pd.Series(dtype=float))
    ebitda_s = metrics.get("ebitda_series", pd.Series(dtype=float))
    if not ingresos_s.empty and not ebitda_s.empty:
        try:
            ing_aligned, eb_aligned = ingresos_s.align(ebitda_s, join="inner")
            metrics["margen_ebitda_series"] = _safe_series_div(eb_aligned, ing_aligned)
            metrics["margen_ebitda_ultimo"] = _get_latest(metrics["margen_ebitda_series"])
        except Exception:
            pass

    # --- Deuda neta / EBITDA ---
    deuda_neta_s = metrics.get("deuda_neta_series", pd.Series(dtype=float))
    if not deuda_neta_s.empty and not ebitda_s.empty:
        try:
            dn_aligned, eb_aligned = deuda_neta_s.align(ebitda_s, join="inner")
            metrics["deuda_neta_ebitda_series"] = _safe_series_div(dn_aligned, eb_aligned)
            metrics["deuda_neta_ebitda_ultimo"] = _get_latest(metrics["deuda_neta_ebitda_series"])
        except Exception:
            pass

    # --- Cobertura de intereses (EBIT / costos financieros) ---
    ebit_s = metrics.get("ebit_series", pd.Series(dtype=float))
    costos_fin = _row(income_df, "costos_financieros")
    if not ebit_s.empty and costos_fin is not None:
        try:
            cf_s = _get_series_values(costos_fin).abs()
            eb_aligned, cf_aligned = ebit_s.align(cf_s, join="inner")
            metrics["cobertura_intereses_series"] = _safe_series_div(eb_aligned, cf_aligned)
            metrics["cobertura_intereses_ultimo"] = _get_latest(metrics["cobertura_intereses_series"])
        except Exception:
            pass

    # --- Flujo operacional / CAPEX ---
    flujo_op_s = metrics.get("flujo_operacional_series", pd.Series(dtype=float))
    capex_s = metrics.get("capex_series", pd.Series(dtype=float))
    if not flujo_op_s.empty and not capex_s.empty:
        try:
            op_aligned, cap_aligned = flujo_op_s.align(capex_s.abs(), join="inner")
            metrics["flujo_op_sobre_capex_series"] = _safe_series_div(op_aligned, cap_aligned)
            metrics["flujo_op_sobre_capex_ultimo"] = _get_latest(metrics["flujo_op_sobre_capex_series"])
        except Exception:
            pass

    # --- PPE sobre activos totales ---
    ppe = _row(balance_df, "propiedades_planta_y_equipo")
    activos_s = metrics.get("activos_totales_series", pd.Series(dtype=float))
    if ppe is not None and not activos_s.empty:
        try:
            ppe_s = _get_series_values(ppe)
            ppe_aligned, act_aligned = ppe_s.align(activos_s, join="inner")
            metrics["ppe_sobre_activos_series"] = _safe_series_div(ppe_aligned, act_aligned)
            metrics["ppe_sobre_activos_ultimo"] = _get_latest(metrics["ppe_sobre_activos_series"])
        except Exception:
            pass

    # --- Payout sobre FCL ---
    dividendos_s = metrics.get("dividendos_pagados_series", pd.Series(dtype=float))
    fcf_s = metrics.get("flujo_libre_de_caja_series", pd.Series(dtype=float))
    if not dividendos_s.empty and not fcf_s.empty:
        try:
            div_aligned, fcf_aligned = dividendos_s.align(fcf_s, join="inner")
            metrics["payout_fcl_series"] = _safe_series_div(div_aligned, fcf_aligned)
            metrics["payout_fcl_ultimo"] = _get_latest(metrics["payout_fcl_series"])
        except Exception:
            pass

    # --- EV/EBITDA ---
    ev_metricas = compute_ev_ebitda_series_cl(balance_df, income_df, derived, md)
    metrics.update(ev_metricas)

    return metrics


def compute_reit_concesion_metrics_cl(
    balance_df: pd.DataFrame,
    income_df: pd.DataFrame,
    cashflow_df: pd.DataFrame,
    derived: dict,
    market_data: Optional[dict] = None,
) -> dict:
    """
    Calcula métricas para empresas de perfil 'reit_concesion' (REIT, zonas francas, etc.).

    Énfasis en flujo operacional, payout sobre flujo, propiedades de inversión,
    yield histórico y deuda sobre activos. No se usa PER como métrica principal.

    Args:
        balance_df, income_df, cashflow_df: DataFrames normalizados.
        derived: Cuentas derivadas.
        market_data: Dict con datos de mercado.

    Returns:
        Dict con métricas calculadas.
    """
    md = market_data or {}
    metrics = compute_common_metrics_cl(balance_df, income_df, cashflow_df, derived, md)

    # --- Margen operacional ---
    ingresos_s = metrics.get("ingresos_series", pd.Series(dtype=float))
    ebit_s = metrics.get("ebit_series", pd.Series(dtype=float))
    if not ingresos_s.empty and not ebit_s.empty:
        try:
            ing_aligned, eb_aligned = ingresos_s.align(ebit_s, join="inner")
            metrics["margen_operacional_series"] = _safe_series_div(eb_aligned, ing_aligned)
            metrics["margen_operacional_ultimo"] = _get_latest(metrics["margen_operacional_series"])
        except Exception:
            pass

    # --- Propiedades de inversión sobre activos ---
    prop_inv = _row(balance_df, "propiedades_de_inversion")
    activos_s = metrics.get("activos_totales_series", pd.Series(dtype=float))
    if prop_inv is not None and not activos_s.empty:
        try:
            pi_s = _get_series_values(prop_inv)
            pi_aligned, act_aligned = pi_s.align(activos_s, join="inner")
            metrics["propiedades_inversion_sobre_activos_series"] = _safe_series_div(pi_aligned, act_aligned)
            metrics["propiedades_inversion_sobre_activos_ultimo"] = _get_latest(
                metrics["propiedades_inversion_sobre_activos_series"]
            )
        except Exception:
            pass

    # --- Deuda sobre activos ---
    deuda_total_s = metrics.get("deuda_financiera_total_series", pd.Series(dtype=float))
    if not deuda_total_s.empty and not activos_s.empty:
        try:
            dt_aligned, act_aligned = deuda_total_s.align(activos_s, join="inner")
            metrics["deuda_sobre_activos_series"] = _safe_series_div(dt_aligned, act_aligned)
            metrics["deuda_sobre_activos_ultimo"] = _get_latest(metrics["deuda_sobre_activos_series"])
        except Exception:
            pass

    # --- Payout sobre flujo operacional ---
    dividendos_s = metrics.get("dividendos_pagados_series", pd.Series(dtype=float))
    flujo_op_s = metrics.get("flujo_operacional_series", pd.Series(dtype=float))
    if not dividendos_s.empty and not flujo_op_s.empty:
        try:
            div_aligned, op_aligned = dividendos_s.align(flujo_op_s, join="inner")
            metrics["payout_flujo_series"] = _safe_series_div(div_aligned, op_aligned)
            metrics["payout_flujo_ultimo"] = _get_latest(metrics["payout_flujo_series"])
        except Exception:
            pass

    # --- FFO aproximado (ganancia neta + D&A) ---
    ganancia_s = metrics.get("ganancia_neta_series", pd.Series(dtype=float))
    da_row = _row(income_df, "depreciacion_y_amortizacion")
    if not ganancia_s.empty and da_row is not None:
        try:
            da_s = _get_series_values(da_row).abs()
            gn_aligned, da_aligned = ganancia_s.align(da_s, join="inner")
            metrics["ffo_aprox_series"] = gn_aligned + da_aligned
            metrics["ffo_aprox_ultimo"] = _get_latest(metrics["ffo_aprox_series"])
        except Exception:
            pass

    # --- EV/EBITDA ---
    ev_metricas = compute_ev_ebitda_series_cl(balance_df, income_df, derived, md)
    metrics.update(ev_metricas)

    return metrics


def compute_financial_metrics_cl(
    balance_df: pd.DataFrame,
    income_df: pd.DataFrame,
    cashflow_df: pd.DataFrame,
    derived: dict,
    market_data: Optional[dict] = None,
) -> dict:
    """
    Calcula métricas para empresas de perfil 'financiera' (bancos, AFP, etc.).

    Énfasis en ROE, P/B, valor libro por acción, payout y dividend yield.
    No se aplican métricas industriales (deuda neta/EBITDA, capital de trabajo).

    Args:
        balance_df, income_df, cashflow_df: DataFrames normalizados.
        derived: Cuentas derivadas.
        market_data: Dict con datos de mercado.

    Returns:
        Dict con métricas calculadas.
    """
    md = market_data or {}
    metrics = compute_common_metrics_cl(balance_df, income_df, cashflow_df, derived, md)

    ganancia_s = metrics.get("ganancia_neta_series", pd.Series(dtype=float))
    patrimonio_s = metrics.get("patrimonio_series", pd.Series(dtype=float))

    # --- ROE ---
    if not ganancia_s.empty and not patrimonio_s.empty:
        try:
            gn_aligned, pat_aligned = ganancia_s.align(patrimonio_s, join="inner")
            metrics["roe_series"] = _safe_series_div(gn_aligned, pat_aligned)
            metrics["roe_ultimo"] = _get_latest(metrics["roe_series"])
        except Exception:
            pass

    # --- Payout sobre utilidad ---
    dividendos_s = metrics.get("dividendos_pagados_series", pd.Series(dtype=float))
    if not dividendos_s.empty and not ganancia_s.empty:
        try:
            div_aligned, gn_aligned = dividendos_s.align(ganancia_s, join="inner")
            metrics["payout_utilidad_series"] = _safe_series_div(div_aligned, gn_aligned)
            metrics["payout_utilidad_ultimo"] = _get_latest(metrics["payout_utilidad_series"])
        except Exception:
            pass

    # --- Valor libro por acción ---
    shares = md.get("shares_outstanding")
    if not patrimonio_s.empty and shares:
        try:
            vlpa = _get_series_values(patrimonio_s) / float(shares)
            metrics["valor_libro_por_accion_series"] = vlpa
            metrics["valor_libro_por_accion_ultimo"] = _get_latest(vlpa)
        except Exception:
            pass

    # --- P/B ---
    price = md.get("last_price")
    vlpa_ultimo = metrics.get("valor_libro_por_accion_ultimo")
    if price and vlpa_ultimo:
        pb = _safe_div(price, vlpa_ultimo)
        if pb is not None:
            metrics["pb"] = pb

    # --- Crecimiento de utilidad (YoY) ---
    if not ganancia_s.empty and len(ganancia_s) >= 2:
        try:
            crecimiento = ganancia_s.pct_change(periods=-1)  # compara vs año anterior
            metrics["crecimiento_utilidad_series"] = crecimiento.dropna()
        except Exception:
            pass

    return metrics


# ---------------------------------------------------------------------------
# Métricas especializadas
# ---------------------------------------------------------------------------


def compute_eps_series_cl(
    income_df: pd.DataFrame,
    derived: dict,
    market_data: Optional[dict] = None,
) -> dict:
    """
    Calcula EPS (Earnings Per Share) como serie histórica.

    Prioriza EPS reportado directamente; si no existe, lo calcula desde
    ganancia_neta_controladora / acciones_promedio.

    Args:
        income_df: Estado de resultados normalizado.
        derived: Cuentas derivadas.
        market_data: Dict con shares_outstanding como fallback.

    Returns:
        Dict con eps_series y eps_ultimo.
    """
    md = market_data or {}
    result: dict = {}

    # EPS reportado
    eps_row = _row(income_df, "eps_basico")
    if eps_row is not None:
        s = _get_series_values(eps_row)
        if not s.empty:
            result["eps_series"] = s
            result["eps_ultimo"] = _get_latest(s)
            return result

    # EPS calculado
    ganancia = _row(income_df, "ganancia_neta_controladora")
    if ganancia is None:
        ganancia = _row(income_df, "ganancia_neta")
    acciones = _row(income_df, "acciones_promedio")

    if ganancia is None:
        return result

    gn_s = _get_series_values(ganancia)

    if acciones is not None:
        acc_s = _get_series_values(acciones)
        if not acc_s.empty:
            gn_aligned, acc_aligned = gn_s.align(acc_s, join="inner")
            eps_s = _safe_series_div(gn_aligned, acc_aligned)
            if not eps_s.empty:
                result["eps_series"] = eps_s
                result["eps_ultimo"] = _get_latest(eps_s)
                return result

    # Fallback con shares de market_data
    shares = md.get("shares_outstanding")
    if shares and not gn_s.empty:
        try:
            eps_s = gn_s / float(shares)
            result["eps_series"] = eps_s
            result["eps_ultimo"] = _get_latest(eps_s)
        except Exception:
            pass

    return result


def compute_per_series_cl(
    income_df: pd.DataFrame,
    derived: dict,
    market_data: Optional[dict] = None,
) -> dict:
    """
    Calcula PER (Price / EPS) usando precio de mercado actual.

    Returns:
        Dict con per_actual (basado en precio actual y EPS último).
    """
    md = market_data or {}
    result: dict = {}

    eps_data = compute_eps_series_cl(income_df, derived, md)
    eps_ultimo = eps_data.get("eps_ultimo")
    price = md.get("last_price")

    if price and eps_ultimo and eps_ultimo > 0:
        per = _safe_div(float(price), eps_ultimo)
        if per is not None:
            result["per_actual"] = per

    return result


def compute_ev_series_cl(
    balance_df: pd.DataFrame,
    market_data: Optional[dict] = None,
) -> dict:
    """
    Calcula Enterprise Value (EV = market_cap + deuda_financiera_total - efectivo).

    Returns:
        Dict con ev_actual.
    """
    md = market_data or {}
    result: dict = {}

    market_cap = md.get("market_cap")
    if not market_cap:
        return result

    deuda_total = _get_latest(_row(balance_df, "deuda_financiera_largo_plazo"))
    deuda_cp = _get_latest(_row(balance_df, "deuda_financiera_corto_plazo"))
    efectivo = _get_latest(_row(balance_df, "efectivo_y_equivalentes"))

    deuda = (deuda_total or 0) + (deuda_cp or 0)
    cash = efectivo or 0

    try:
        ev = float(market_cap) + deuda - cash
        result["ev_actual"] = ev
    except Exception:
        pass

    return result


def compute_ev_ebitda_series_cl(
    balance_df: pd.DataFrame,
    income_df: pd.DataFrame,
    derived: dict,
    market_data: Optional[dict] = None,
) -> dict:
    """
    Calcula EV/EBITDA usando EV actual y EBITDA histórico.

    Returns:
        Dict con ev_ebitda_actual.
    """
    md = market_data or {}
    result: dict = {}

    ev_data = compute_ev_series_cl(balance_df, md)
    ev = ev_data.get("ev_actual")
    if ev is None:
        return result

    result["ev_actual"] = ev

    ebitda_row = _row(income_df, "ebitda")
    if ebitda_row is None and "ebitda" in derived:
        ebitda_row = derived["ebitda"]

    if ebitda_row is not None:
        ebitda_ultimo = _get_latest(ebitda_row)
        if ebitda_ultimo and ebitda_ultimo > 0:
            ev_ebitda = _safe_div(ev, ebitda_ultimo)
            if ev_ebitda is not None:
                result["ev_ebitda_actual"] = ev_ebitda

    return result


def compute_dividend_metrics_cl(
    cashflow_df: pd.DataFrame,
    income_df: pd.DataFrame,
    derived: dict,
    market_data: Optional[dict] = None,
) -> dict:
    """
    Calcula métricas de dividendos.

    Returns:
        Dict con dividendos_pagados_ultimo, payout_utilidad, payout_fcl.
    """
    md = market_data or {}
    result: dict = {}

    dividendos = _row(cashflow_df, "dividendos_pagados")
    if dividendos is not None:
        div_s = _get_series_values(dividendos).abs()
        result["dividendos_pagados_ultimo"] = _get_latest(div_s)

        ganancia = _row(income_df, "ganancia_neta")
        if ganancia is not None:
            gn_s = _get_series_values(ganancia)
            if not gn_s.empty and not div_s.empty:
                d_aligned, g_aligned = div_s.align(gn_s, join="inner")
                result["payout_utilidad_series"] = _safe_series_div(d_aligned, g_aligned)
                result["payout_utilidad_ultimo"] = _get_latest(result["payout_utilidad_series"])

    return result


def compute_profitability_metrics_cl(
    balance_df: pd.DataFrame,
    income_df: pd.DataFrame,
    derived: dict,
) -> dict:
    """
    Calcula métricas de rentabilidad (ROE, ROA, márgenes).

    Returns:
        Dict con métricas de rentabilidad.
    """
    result: dict = {}

    ganancia = _row(income_df, "ganancia_neta")
    if ganancia is None:
        return result

    gn_s = _get_series_values(ganancia)
    ingresos = _row(income_df, "ingresos")
    patrimonio = _row(balance_df, "patrimonio_total")
    activos = _row(balance_df, "activos_totales")

    if ingresos is not None and not gn_s.empty:
        ing_s = _get_series_values(ingresos)
        if not ing_s.empty:
            gn_aligned, ing_aligned = gn_s.align(ing_s, join="inner")
            result["margen_neto_series"] = _safe_series_div(gn_aligned, ing_aligned)
            result["margen_neto_ultimo"] = _get_latest(result["margen_neto_series"])

    if patrimonio is not None and not gn_s.empty:
        pat_s = _get_series_values(patrimonio)
        if not pat_s.empty:
            gn_aligned, pat_aligned = gn_s.align(pat_s, join="inner")
            result["roe_series"] = _safe_series_div(gn_aligned, pat_aligned)
            result["roe_ultimo"] = _get_latest(result["roe_series"])

    if activos is not None and not gn_s.empty:
        act_s = _get_series_values(activos)
        if not act_s.empty:
            gn_aligned, act_aligned = gn_s.align(act_s, join="inner")
            result["roa_series"] = _safe_series_div(gn_aligned, act_aligned)
            result["roa_ultimo"] = _get_latest(result["roa_series"])

    return result


def compute_leverage_metrics_cl(
    balance_df: pd.DataFrame,
    income_df: pd.DataFrame,
    derived: dict,
) -> dict:
    """
    Calcula métricas de endeudamiento.

    Returns:
        Dict con deuda_neta, deuda_neta_ebitda, deuda_sobre_activos.
    """
    result: dict = {}

    deuda_lp = _row(balance_df, "deuda_financiera_largo_plazo")
    deuda_cp = _row(balance_df, "deuda_financiera_corto_plazo")
    efectivo = _row(balance_df, "efectivo_y_equivalentes")
    activos = _row(balance_df, "activos_totales")

    # Deuda total
    if deuda_lp is not None or deuda_cp is not None:
        dt = pd.Series(dtype=float)
        if deuda_lp is not None:
            dt = _get_series_values(deuda_lp).abs()
        if deuda_cp is not None:
            cp = _get_series_values(deuda_cp).abs()
            dt = dt.add(cp, fill_value=0)
        result["deuda_financiera_total_series"] = dt
        result["deuda_financiera_total_ultima"] = _get_latest(dt)

        # Deuda neta
        if efectivo is not None:
            ef = _get_series_values(efectivo)
            dt_aligned, ef_aligned = dt.align(ef, join="inner")
            dn = dt_aligned - ef_aligned
            result["deuda_neta_series"] = dn
            result["deuda_neta_ultima"] = _get_latest(dn)

            # Deuda neta / EBITDA
            ebitda_row = _row(income_df, "ebitda")
            if ebitda_row is None and "ebitda" in derived:
                ebitda_row = derived["ebitda"]
            if ebitda_row is not None:
                eb_s = _get_series_values(ebitda_row)
                dn_aligned, eb_aligned = dn.align(eb_s, join="inner")
                result["deuda_neta_ebitda_series"] = _safe_series_div(dn_aligned, eb_aligned)
                result["deuda_neta_ebitda_ultimo"] = _get_latest(result["deuda_neta_ebitda_series"])

    # Deuda sobre activos
    if "deuda_financiera_total_series" in result and activos is not None:
        dt_s = result["deuda_financiera_total_series"]
        act_s = _get_series_values(activos)
        dt_aligned, act_aligned = dt_s.align(act_s, join="inner")
        result["deuda_sobre_activos_series"] = _safe_series_div(dt_aligned, act_aligned)
        result["deuda_sobre_activos_ultimo"] = _get_latest(result["deuda_sobre_activos_series"])

    return result


def compute_cashflow_metrics_cl(
    cashflow_df: pd.DataFrame,
    income_df: pd.DataFrame,
    derived: dict,
) -> dict:
    """
    Calcula métricas de flujo de caja.

    Returns:
        Dict con flujo_operacional, capex, FCL, payout_fcl.
    """
    result: dict = {}

    flujo_op = _row(cashflow_df, "flujo_operacional")
    capex = _row(cashflow_df, "capex")
    fcf_row = _row(cashflow_df, "flujo_libre_de_caja")
    if fcf_row is None and "flujo_libre_de_caja" in derived:
        fcf_row = derived["flujo_libre_de_caja"]

    if flujo_op is not None:
        op_s = _get_series_values(flujo_op)
        result["flujo_operacional_series"] = op_s
        result["flujo_operacional_ultimo"] = _get_latest(op_s)

    if capex is not None:
        cap_s = _get_series_values(capex)
        result["capex_series"] = cap_s
        result["capex_ultimo"] = _get_latest(cap_s)

    if fcf_row is not None:
        fcf_s = _get_series_values(fcf_row)
        result["flujo_libre_de_caja_series"] = fcf_s
        result["flujo_libre_de_caja_ultimo"] = _get_latest(fcf_s)

    return result


# ---------------------------------------------------------------------------
# Dispatcher principal
# ---------------------------------------------------------------------------


def compute_metrics_cl(
    balance_df: pd.DataFrame,
    income_df: pd.DataFrame,
    cashflow_df: pd.DataFrame,
    derived: dict,
    profile_type: str,
    market_data: Optional[dict] = None,
) -> dict:
    """
    Calcula las métricas adecuadas según el profile_type de la empresa.

    Args:
        balance_df, income_df, cashflow_df: DataFrames normalizados.
        derived: Cuentas derivadas del normalizer.
        profile_type: 'normal', 'utility', 'reit_concesion' o 'financiera'.
        market_data: Dict con datos de mercado.

    Returns:
        Dict con las métricas calculadas para el perfil indicado.
    """
    if profile_type == "utility":
        return compute_utility_metrics_cl(balance_df, income_df, cashflow_df, derived, market_data)
    elif profile_type == "reit_concesion":
        return compute_reit_concesion_metrics_cl(balance_df, income_df, cashflow_df, derived, market_data)
    elif profile_type == "financiera":
        return compute_financial_metrics_cl(balance_df, income_df, cashflow_df, derived, market_data)
    else:
        # 'normal' o cualquier perfil desconocido
        return compute_normal_metrics_cl(balance_df, income_df, cashflow_df, derived, market_data)


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------


def _safe_series_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """División segura de dos Series, retornando NaN donde no es posible dividir."""
    try:
        result = numerator / denominator
        result = result.replace([np.inf, -np.inf], np.nan)
        return result
    except Exception:
        return pd.Series(dtype=float)
