# src/services/chile_normalizer.py
"""
Normalización de estados financieros chilenos.

Este módulo soporta dos mundos:

1) Formatos crudos / heredados
2) Formato final EEFF_Chile_<TICKER>.csv con esquema amplio en español

Para el formato final, la lógica correcta NO es reindexar directo al esquema
operativo, sino:
- leer el esquema amplio
- traducirlo a las cuentas operativas cortas
- derivar cuentas faltantes
- entregar DataFrames compatibles con chile_metrics.py y chile_charts.py
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from src.services.chile_schema import (
    BALANCE_ACCOUNTS_CL,
    CASHFLOW_ACCOUNTS_CL,
    CSV_BALANCE_ACCOUNTS_CL,
    CSV_CASHFLOW_ACCOUNTS_CL,
    CSV_INCOME_ACCOUNTS_CL,
    INCOME_ACCOUNTS_CL,
)

_REPO_ROOT = Path(__file__).parent.parent.parent
_ACCOUNT_MAP_PATH = _REPO_ROOT / "data" / "chile_account_map.csv"


# =============================================================================
# MAPA LEGACY OPCIONAL
# =============================================================================

def load_account_map_cl() -> pd.DataFrame:
    if not _ACCOUNT_MAP_PATH.exists():
        return pd.DataFrame(
            columns=[
                "statement_type",
                "profile_type",
                "canonical_account",
                "match_type",
                "source_pattern",
                "priority",
            ]
        )
    try:
        df = pd.read_csv(_ACCOUNT_MAP_PATH, sep=",", dtype=str).fillna("")
        df["priority"] = pd.to_numeric(df["priority"], errors="coerce").fillna(99).astype(int)
        df["source_pattern"] = df["source_pattern"].str.strip().str.lower()
        df["match_type"] = df["match_type"].str.strip().str.lower()
        df["profile_type"] = df["profile_type"].str.strip().str.lower()
        df["statement_type"] = df["statement_type"].str.strip().str.lower()
        df["canonical_account"] = df["canonical_account"].str.strip().str.lower()
        return df.sort_values("priority").reset_index(drop=True)
    except Exception:
        return pd.DataFrame(
            columns=[
                "statement_type",
                "profile_type",
                "canonical_account",
                "match_type",
                "source_pattern",
                "priority",
            ]
        )


def map_raw_account_to_canonical(
    raw_name: str,
    statement_type: str,
    profile_type: str,
    account_map: Optional[pd.DataFrame] = None,
) -> Optional[str]:
    if account_map is None:
        account_map = load_account_map_cl()

    if account_map.empty:
        return None

    raw_lower = str(raw_name).strip().lower()
    stmt_lower = str(statement_type).strip().lower()
    ptype_lower = str(profile_type).strip().lower()

    subset = account_map[account_map["statement_type"] == stmt_lower]

    for pt_filter in [ptype_lower, "all"]:
        candidates = subset[subset["profile_type"] == pt_filter]
        for _, row in candidates.iterrows():
            pattern = row["source_pattern"]
            match_type = row["match_type"]
            try:
                if match_type == "exact" and raw_lower == pattern:
                    return row["canonical_account"]
                if match_type == "contains" and pattern in raw_lower:
                    return row["canonical_account"]
                if match_type == "regex" and re.search(pattern, raw_lower):
                    return row["canonical_account"]
            except Exception:
                continue

    return None


# =============================================================================
# UTILIDADES
# =============================================================================

def standardize_year_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    df = df[[c for c in df.columns if c and not c.startswith("Unnamed")]]

    year_cols = [c for c in df.columns if re.match(r"^\d{4}$", str(c))]
    other_cols = [c for c in df.columns if c not in year_cols]
    year_cols = sorted(year_cols, reverse=True)

    return df[year_cols + other_cols]


def _clean_section_df(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()
    out.index = [str(i).strip() for i in out.index]
    out = standardize_year_columns(out)

    for col in out.columns:
        out[col] = (
            out[col]
            .astype(str)
            .str.replace(".", "", regex=False)  # quita miles tipo 1.234
            .str.replace(",", ".", regex=False)  # decimal coma -> punto
            .replace({"nan": np.nan, "None": np.nan, "": np.nan})
        )
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out[~out.index.duplicated(keep="first")]
    return out


def _sum_existing_rows(df: pd.DataFrame, accounts: list[str]) -> Optional[pd.Series]:
    if df is None or df.empty:
        return None
    rows = [acc for acc in accounts if acc in df.index]
    if not rows:
        return None
    numeric = df.loc[rows].apply(pd.to_numeric, errors="coerce")
    return numeric.sum(axis=0, min_count=1)


def _first_existing_row(df: pd.DataFrame, accounts: list[str]) -> Optional[pd.Series]:
    if df is None or df.empty:
        return None
    for acc in accounts:
        if acc in df.index:
            return pd.to_numeric(df.loc[acc], errors="coerce")
    return None


def _build_operating_df(source_df: pd.DataFrame, mapping: dict[str, list[str]], ordered_accounts: list[str]) -> pd.DataFrame:
    if source_df is None or source_df.empty:
        return pd.DataFrame(index=ordered_accounts)

    rows: dict[str, pd.Series] = {}
    all_cols = list(source_df.columns)

    for target, candidates in mapping.items():
        series = _sum_existing_rows(source_df, candidates)
        if series is None:
            series = _first_existing_row(source_df, candidates)
        if series is None:
            series = pd.Series(index=all_cols, dtype=float)
        rows[target] = series

    out = pd.DataFrame(rows).T
    out = out.reindex(ordered_accounts)
    out.index.name = "cuenta"
    out = standardize_year_columns(out)
    return out


# =============================================================================
# MAPEO DESDE CSV AMPLIO -> ESQUEMA OPERATIVO CORTO
# =============================================================================

BALANCE_WIDE_TO_SHORT: dict[str, list[str]] = {
    "efectivo_y_equivalentes": ["efectivo_y_equivalentes"],
    "inversiones_corto_plazo": [
        "activos_financieros_a_valor_razonable_corrientes",
        "otros_activos_financieros_corrientes",
    ],
    "deudores_comerciales": [
        "deudores_comerciales_y_otras_cuentas_por_cobrar_corrientes",
        "deudores_comerciales_y_otras_cuentas_por_cobrar_no_corrientes",
        "cuentas_por_cobrar_a_entidades_relacionadas_corrientes",
        "cuentas_por_cobrar_a_entidades_relacionadas_no_corrientes",
    ],
    "inventarios": ["inventarios"],
    "otros_activos_corrientes": [
        "otros_activos_no_financieros_corrientes",
        "activos_por_impuestos_corrientes",
        "pagos_anticipados_corrientes",
        "activos_biologicos_corrientes",
        "otros_activos_corrientes",
    ],
    "activos_corrientes": ["total_activos_corrientes"],
    "propiedades_planta_y_equipo": ["propiedades_planta_y_equipo"],
    "propiedades_de_inversion": ["propiedades_de_inversion"],
    "activos_biologicos": ["activos_biologicos_no_corrientes", "activos_biologicos_corrientes"],
    "intangibles": ["activos_intangibles"],
    "goodwill": ["plusvalia"],
    "otros_activos_no_corrientes": [
        "otros_activos_financieros_no_corrientes",
        "inversiones_contabilizadas_usando_metodo_de_participacion",
        "activos_por_derecho_de_uso",
        "activos_por_impuestos_diferidos",
        "pagos_anticipados_no_corrientes",
        "otros_activos_no_corrientes",
        "encaje",
    ],
    "activos_no_corrientes": ["total_activos_no_corrientes"],
    "activos_totales": ["total_activos"],
    "cuentas_por_pagar": [
        "acreedores_comerciales_y_otras_cuentas_por_pagar_corrientes",
        "acreedores_comerciales_y_otras_cuentas_por_pagar_no_corrientes",
        "cuentas_por_pagar_a_entidades_relacionadas_corrientes",
        "cuentas_por_pagar_a_entidades_relacionadas_no_corrientes",
    ],
    "deuda_financiera_corto_plazo": ["prestamos_y_obligaciones_financieras_corrientes"],
    "pasivos_arrendamiento_corriente": ["pasivos_por_arrendamiento_corrientes"],
    "otros_pasivos_corrientes": [
        "otros_pasivos_financieros_corrientes",
        "provisiones_corrientes",
        "pasivos_por_impuestos_corrientes",
        "pasivos_acumulados_o_devengados_corrientes",
        "provisiones_corrientes_por_beneficios_a_los_empleados",
        "otros_pasivos_no_financieros_corrientes",
    ],
    "pasivos_corrientes": ["total_pasivos_corrientes"],
    "deuda_financiera_largo_plazo": ["prestamos_y_obligaciones_financieras_no_corrientes"],
    "pasivos_arrendamiento_no_corriente": ["pasivos_por_arrendamiento_no_corrientes"],
    "impuestos_diferidos": ["pasivos_por_impuestos_diferidos"],
    "otros_pasivos_no_corrientes": [
        "otros_pasivos_financieros_no_corrientes",
        "otras_provisiones_no_corrientes",
        "obligaciones_por_beneficios_post_empleo",
        "provisiones_no_corrientes_por_beneficios_a_los_empleados",
        "otros_pasivos_no_financieros_no_corrientes",
    ],
    "pasivos_no_corrientes": ["total_pasivos_no_corrientes"],
    "pasivos_totales": ["total_pasivos"],
    "ganancias_acumuladas": ["resultados_retenidos_o_ganancias_acumuladas"],
    "participaciones_no_controladoras": ["participaciones_no_controladoras"],
    "patrimonio_total": ["total_patrimonio", "patrimonio_atribuible_a_los_propietarios_de_la_controladora"],
}

INCOME_WIDE_TO_SHORT: dict[str, list[str]] = {
    "ingresos": ["ingresos_ordinarios", "ingresos_por_comisiones"],
    "costo_de_ventas": ["costo_de_ventas", "materias_primas_y_consumibles_utilizados"],
    "ganancia_bruta": ["ganancia_bruta"],
    "gastos_de_administracion": ["gastos_de_administracion", "gastos_de_personal"],
    "gastos_de_distribucion": ["costos_de_distribucion"],
    "otros_ingresos_operacionales": [
        "otros_ingresos_operacionales",
        "rentabilidad_del_encaje",
        "prima_seguro_invalidez_y_sobrevivencia",
    ],
    "otros_gastos_operacionales": [
        "perdidas_por_deterioro_reversiones_neto",
        "otros_gastos_varios_de_operacion",
        "otros_gastos_por_funcion_o_naturaleza",
    ],
    "resultado_operacional": ["resultado_operacional"],
    "depreciacion_y_amortizacion": ["depreciacion_y_amortizacion"],
    "ebit": ["ebit", "resultado_operacional"],
    "ebitda": ["ebitda"],
    "ingresos_financieros": ["ingresos_financieros"],
    "costos_financieros": ["costos_financieros"],
    "resultado_por_tipo_de_cambio": ["diferencias_de_cambio", "resultados_por_unidades_de_reajuste"],
    "participacion_en_asociadas": ["participacion_en_ganancias_perdidas_de_asociadas_y_negocios_conjuntos"],
    "resultado_antes_de_impuestos": ["resultado_antes_de_impuestos"],
    "impuesto_a_las_ganancias": ["gasto_ingreso_por_impuestos_a_las_ganancias"],
    "ganancia_neta": [
        "ganancia_neta",
        "ganancia_neta_de_actividades_continuadas",
    ],
    "ganancia_neta_controladora": [
        "ganancia_neta_controladora",
        "ganancia_atribuible_a_los_propietarios_de_la_controladora",
    ],
    "eps_basico": ["ganancia_por_accion_basica_total"],
    "acciones_promedio": ["acciones_promedio_ponderado_basico"],
}

CASHFLOW_WIDE_TO_SHORT: dict[str, list[str]] = {
    "flujo_operacional": ["flujo_neto_actividades_de_operacion"],
    "intereses_recibidos": ["intereses_recibidos_clasificados_como_operacion"],
    "intereses_pagados": ["intereses_pagados_clasificados_como_operacion"],
    "impuestos_pagados": ["impuestos_a_las_ganancias_pagados"],
    "capex": ["capex"],  # si viene ya cargado
    "venta_de_activos": [
        "ventas_de_propiedades_planta_y_equipo",
        "ventas_de_activos_financieros",
        "ventas_de_cuotas_del_encaje",
    ],
    "adquisiciones": ["pagos_por_adquisicion_de_filiales_o_negocios"],
    "dividendos_pagados": ["dividendos_pagados"],
    "deuda_emitida": ["obtencion_de_prestamos"],
    "deuda_pagada": ["pago_de_prestamos"],
    "pagos_de_arrendamiento": ["pago_de_pasivos_por_arrendamiento"],
    "flujo_libre_de_caja": ["flujo_libre_de_caja"],  # si viene ya cargado
}


# =============================================================================
# NORMALIZACIÓN LEGACY (se mantiene)
# =============================================================================

def normalize_balance_cl(
    df_raw: pd.DataFrame,
    profile_type: str,
    account_map: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    return _normalize_statement(df_raw, "balance", profile_type, BALANCE_ACCOUNTS_CL, account_map)


def normalize_income_cl(
    df_raw: pd.DataFrame,
    profile_type: str,
    account_map: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    return _normalize_statement(df_raw, "income", profile_type, INCOME_ACCOUNTS_CL, account_map)


def normalize_cashflow_cl(
    df_raw: pd.DataFrame,
    profile_type: str,
    account_map: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    return _normalize_statement(df_raw, "cashflow", profile_type, CASHFLOW_ACCOUNTS_CL, account_map)


def _normalize_statement(
    df_raw: pd.DataFrame,
    statement_type: str,
    profile_type: str,
    canonical_accounts: list[str],
    account_map: Optional[pd.DataFrame],
) -> pd.DataFrame:
    if df_raw is None or df_raw.empty:
        return pd.DataFrame()

    if account_map is None:
        account_map = load_account_map_cl()

    df_raw = standardize_year_columns(df_raw)
    if df_raw.empty:
        return pd.DataFrame()

    mapped: dict[str, pd.Series] = {}

    for raw_account in df_raw.index:
        canonical = map_raw_account_to_canonical(
            str(raw_account), statement_type, profile_type, account_map
        )
        if canonical and canonical not in mapped:
            mapped[canonical] = pd.to_numeric(df_raw.loc[raw_account], errors="coerce")

    if not mapped:
        return pd.DataFrame(index=canonical_accounts)

    result = pd.DataFrame(mapped).T
    result.index.name = "cuenta"
    result = result.reindex(canonical_accounts)
    result = standardize_year_columns(result)
    return result


# =============================================================================
# NORMALIZACIÓN DESDE CSV AMPLIO FINAL
# =============================================================================

def normalize_from_sections(
    sections: dict,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Traduce el CSV amplio final al esquema operativo corto.

    Entrada:
        sections["BALANCE"], sections["EERR"], sections["EFE"]
    Salida:
        balance_norm, income_norm, cashflow_norm
    """
    balance_src = _clean_section_df(sections.get("BALANCE"))
    income_src = _clean_section_df(sections.get("EERR"))
    cashflow_src = _clean_section_df(sections.get("EFE"))

    balance_norm = _build_operating_df(balance_src, BALANCE_WIDE_TO_SHORT, BALANCE_ACCOUNTS_CL)
    income_norm = _build_operating_df(income_src, INCOME_WIDE_TO_SHORT, INCOME_ACCOUNTS_CL)
    cashflow_norm = _build_operating_df(cashflow_src, CASHFLOW_WIDE_TO_SHORT, CASHFLOW_ACCOUNTS_CL)

    # Derivación temprana de CAPEX desde el CSV amplio si no vino informado
    if "capex" in cashflow_norm.index:
        capex_row = pd.to_numeric(cashflow_norm.loc["capex"], errors="coerce")
        if capex_row.dropna().empty:
            derived_capex = _derive_capex_from_wide_cashflow(cashflow_src)
            if derived_capex is not None:
                cashflow_norm.loc["capex"] = derived_capex

    # Si acciones_promedio viene en EERR, mantenerlo también como metadata lógica interna
    return balance_norm, income_norm, cashflow_norm


def _derive_capex_from_wide_cashflow(cashflow_src: pd.DataFrame) -> Optional[pd.Series]:
    if cashflow_src is None or cashflow_src.empty:
        return None

    capex_components = [
        "compras_de_propiedades_planta_y_equipo",
        "compras_de_activos_intangibles",
        "compras_de_propiedades_de_inversion",
    ]

    series = _sum_existing_rows(cashflow_src, capex_components)
    if series is None:
        return None

    # Normalizamos CAPEX a negativo, porque derive_missing_accounts_cl usa FCF = op + capex
    return -series.abs()


# =============================================================================
# DERIVACIÓN DE CUENTAS FALTANTES
# =============================================================================

def derive_missing_accounts_cl(
    balance_df: pd.DataFrame,
    income_df: pd.DataFrame,
    cashflow_df: pd.DataFrame,
    profile_type: str,
) -> dict:
    derived: dict = {}

    # EBIT desde resultado_operacional
    if not income_df.empty and "resultado_operacional" in income_df.index:
        ebit_existing = pd.to_numeric(income_df.loc["ebit"], errors="coerce") if "ebit" in income_df.index else None
        if ebit_existing is None or ebit_existing.dropna().empty:
            derived["ebit"] = pd.to_numeric(income_df.loc["resultado_operacional"], errors="coerce")

    # EBITDA desde EBIT + D&A
    ebit_source = None
    if "ebit" in income_df.index:
        ebit_source = pd.to_numeric(income_df.loc["ebit"], errors="coerce")
        if ebit_source.dropna().empty and "ebit" in derived:
            ebit_source = pd.to_numeric(derived["ebit"], errors="coerce")
    elif "ebit" in derived:
        ebit_source = pd.to_numeric(derived["ebit"], errors="coerce")

    da_source = None
    if "depreciacion_y_amortizacion" in income_df.index:
        da_source = pd.to_numeric(income_df.loc["depreciacion_y_amortizacion"], errors="coerce")

    if ebit_source is not None and da_source is not None:
        ebitda_existing = pd.to_numeric(income_df.loc["ebitda"], errors="coerce") if "ebitda" in income_df.index else None
        if ebitda_existing is None or ebitda_existing.dropna().empty:
            derived["ebitda"] = ebit_source + da_source.abs()

    # Deuda financiera total
    cp_debt = pd.to_numeric(balance_df.loc["deuda_financiera_corto_plazo"], errors="coerce") if "deuda_financiera_corto_plazo" in balance_df.index else None
    lp_debt = pd.to_numeric(balance_df.loc["deuda_financiera_largo_plazo"], errors="coerce") if "deuda_financiera_largo_plazo" in balance_df.index else None

    if cp_debt is not None or lp_debt is not None:
        cp = cp_debt if cp_debt is not None else pd.Series(index=balance_df.columns, dtype=float)
        lp = lp_debt if lp_debt is not None else pd.Series(index=balance_df.columns, dtype=float)
        derived["deuda_financiera_total"] = cp.abs().fillna(0) + lp.abs().fillna(0)

    # Flujo libre de caja
    op_source = pd.to_numeric(cashflow_df.loc["flujo_operacional"], errors="coerce") if "flujo_operacional" in cashflow_df.index else None
    capex_source = pd.to_numeric(cashflow_df.loc["capex"], errors="coerce") if "capex" in cashflow_df.index else None

    if op_source is not None and capex_source is not None:
        fcf_existing = pd.to_numeric(cashflow_df.loc["flujo_libre_de_caja"], errors="coerce") if "flujo_libre_de_caja" in cashflow_df.index else None
        if fcf_existing is None or fcf_existing.dropna().empty:
            # Convención: capex negativo
            derived["flujo_libre_de_caja"] = op_source + capex_source

    return derived
