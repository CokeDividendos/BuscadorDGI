# src/services/chile_normalizer.py
"""
Normalización de estados financieros chilenos.

Toma DataFrames crudos con nombres variados (en inglés o español) y
los mapea a cuentas canónicas en español definidas en chile_schema.py.

El mapeo se configura desde data/chile_account_map.csv, permitiendo:
- Coincidencia exact / contains / regex
- Prioridades (menor número = mayor prioridad)
- Reglas generales ('all') y específicas por profile_type
- Derivación de cuentas faltantes (e.g., EBITDA desde EBIT + D&A)
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
    INCOME_ACCOUNTS_CL,
    METADATA_ACCOUNTS_CL,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent
_ACCOUNT_MAP_PATH = _REPO_ROOT / "data" / "chile_account_map.csv"

# ---------------------------------------------------------------------------
# Carga del mapa de cuentas
# ---------------------------------------------------------------------------


def load_account_map_cl() -> pd.DataFrame:
    """
    Carga data/chile_account_map.csv.

    Columnas: statement_type, profile_type, canonical_account,
              match_type, source_pattern, priority.
    Retorna DataFrame vacío si el archivo no existe.
    """
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
        # Normalizar a minúsculas para comparaciones
        df["source_pattern"] = df["source_pattern"].str.strip().str.lower()
        df["match_type"] = df["match_type"].str.strip().str.lower()
        df["profile_type"] = df["profile_type"].str.strip().str.lower()
        df["statement_type"] = df["statement_type"].str.strip().str.lower()
        df["canonical_account"] = df["canonical_account"].str.strip().str.lower()
        # Ordenar por prioridad
        df = df.sort_values("priority").reset_index(drop=True)
        return df
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
    """
    Mapea un nombre de cuenta crudo a su nombre canónico en español.

    Busca primero reglas específicas del perfil y luego reglas generales ('all').
    Dentro de cada grupo, respeta el orden de prioridad del CSV.

    Args:
        raw_name: Nombre de la cuenta tal como aparece en el CSV fuente.
        statement_type: 'balance', 'income' o 'cashflow'.
        profile_type: Tipo de perfil ('normal', 'utility', etc.).
        account_map: DataFrame del mapa (se carga automáticamente si es None).

    Returns:
        Nombre canónico en español, o None si no hay coincidencia.
    """
    if account_map is None:
        account_map = load_account_map_cl()

    if account_map.empty:
        return None

    raw_lower = raw_name.strip().lower()
    stmt_lower = statement_type.strip().lower()
    ptype_lower = profile_type.strip().lower()

    # Filtrar por statement_type
    subset = account_map[account_map["statement_type"] == stmt_lower]

    # Evaluar primero reglas específicas del perfil, luego las generales
    for pt_filter in [ptype_lower, "all"]:
        candidates = subset[subset["profile_type"] == pt_filter]

        for _, row in candidates.iterrows():
            pattern = row["source_pattern"]
            match_type = row["match_type"]

            try:
                if match_type == "exact":
                    if raw_lower == pattern:
                        return row["canonical_account"]
                elif match_type == "contains":
                    if pattern in raw_lower:
                        return row["canonical_account"]
                elif match_type == "regex":
                    if re.search(pattern, raw_lower):
                        return row["canonical_account"]
            except Exception:
                continue

    return None


# ---------------------------------------------------------------------------
# Normalización por estado financiero
# ---------------------------------------------------------------------------


def standardize_year_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Estandariza las columnas de años de un DataFrame financiero.

    Convierte columnas a string, elimina columnas sin nombre o con prefijo
    'Unnamed', y ordena de mayor a menor año (más reciente primero).

    Args:
        df: DataFrame con cuentas como índice y años como columnas.

    Returns:
        DataFrame con columnas de año ordenadas.
    """
    if df.empty:
        return df

    df = df.copy()
    # Limpiar columnas
    df.columns = [str(c).strip() for c in df.columns]
    df = df[[c for c in df.columns if c and not c.startswith("Unnamed")]]

    # Intentar ordenar columnas que parecen años (4 dígitos)
    year_cols = [c for c in df.columns if re.match(r"^\d{4}$", c)]
    other_cols = [c for c in df.columns if c not in year_cols]

    if year_cols:
        year_cols_sorted = sorted(year_cols, reverse=True)  # más reciente primero
        df = df[year_cols_sorted + other_cols]

    return df


def normalize_balance_cl(
    df_raw: pd.DataFrame,
    profile_type: str,
    account_map: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Normaliza el Balance General crudo a cuentas canónicas en español.

    Args:
        df_raw: DataFrame crudo con cuentas como índice y años como columnas.
        profile_type: Tipo de empresa ('normal', 'utility', 'reit_concesion', 'financiera').
        account_map: Mapa de cuentas (se carga si es None).

    Returns:
        DataFrame normalizado con cuentas canónicas como índice.
        Cuentas sin mapeo se descartan con trazabilidad interna.
    """
    return _normalize_statement(df_raw, "balance", profile_type, BALANCE_ACCOUNTS_CL, account_map)


def normalize_income_cl(
    df_raw: pd.DataFrame,
    profile_type: str,
    account_map: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Normaliza el Estado de Resultados crudo a cuentas canónicas en español.

    Args:
        df_raw: DataFrame crudo con cuentas como índice y años como columnas.
        profile_type: Tipo de empresa.
        account_map: Mapa de cuentas (se carga si es None).

    Returns:
        DataFrame normalizado con cuentas canónicas como índice.
    """
    return _normalize_statement(df_raw, "income", profile_type, INCOME_ACCOUNTS_CL, account_map)


def normalize_cashflow_cl(
    df_raw: pd.DataFrame,
    profile_type: str,
    account_map: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Normaliza el Estado de Flujo de Efectivo crudo a cuentas canónicas en español.

    Args:
        df_raw: DataFrame crudo con cuentas como índice y años como columnas.
        profile_type: Tipo de empresa.
        account_map: Mapa de cuentas (se carga si es None).

    Returns:
        DataFrame normalizado con cuentas canónicas como índice.
    """
    return _normalize_statement(df_raw, "cashflow", profile_type, CASHFLOW_ACCOUNTS_CL, account_map)


def _normalize_statement(
    df_raw: pd.DataFrame,
    statement_type: str,
    profile_type: str,
    canonical_accounts: list[str],
    account_map: Optional[pd.DataFrame],
) -> pd.DataFrame:
    """
    Implementación interna de normalización para cualquier tipo de estado financiero.

    Cuando varios nombres crudos mapean a la misma cuenta canónica,
    se usa la primera fila encontrada (respetando el orden de prioridad del CSV).
    """
    if df_raw is None or df_raw.empty:
        return pd.DataFrame()

    if account_map is None:
        account_map = load_account_map_cl()

    # Estandarizar columnas de años
    df_raw = standardize_year_columns(df_raw)
    if df_raw.empty:
        return pd.DataFrame()

    year_cols = list(df_raw.columns)

    # Mapear cada cuenta cruda a su nombre canónico
    # Construir mapa: canonical -> primera fila cruda que coincide
    mapped: dict[str, pd.Series] = {}
    unmapped: list[str] = []

    for raw_account in df_raw.index:
        canonical = map_raw_account_to_canonical(
            str(raw_account), statement_type, profile_type, account_map
        )
        if canonical and canonical not in mapped:
            mapped[canonical] = df_raw.loc[raw_account]
        elif canonical is None:
            unmapped.append(str(raw_account))

    if not mapped:
        return pd.DataFrame()

    # Construir DataFrame normalizado con solo las cuentas canónicas que existen
    rows = {}
    for account in canonical_accounts:
        if account in mapped:
            rows[account] = mapped[account]

    if not rows:
        return pd.DataFrame()

    result = pd.DataFrame(rows).T
    result.index.name = "cuenta"
    result.columns = year_cols[: len(result.columns)]
    result = result.apply(pd.to_numeric, errors="coerce")

    return result


# ---------------------------------------------------------------------------
# Normalización directa desde secciones del formato EEFF_Chile
# ---------------------------------------------------------------------------


def normalize_from_sections(
    sections: dict,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Normaliza los EEFF directamente desde las secciones del formato EEFF_Chile.

    Los DataFrames de entrada ya usan nombres de cuentas canónicos en español.
    Esta función solo:
    1. Reindexea cada sección a la lista completa de cuentas canónicas (NaN para faltantes).
    2. Garantiza conversión numérica y orden de columnas (años de mayor a menor).

    Args:
        sections: Dict con claves ``'BALANCE'``, ``'EERR'``, ``'EFE'`` (y opcionalmente
                  ``'METADATA'``), cada uno siendo un DataFrame con cuentas canónicas
                  como índice y años como columnas.

    Returns:
        Tupla ``(balance_norm, income_norm, cashflow_norm)``, DataFrames normalizados
        con cuentas canónicas como índice.  Cuentas ausentes en el CSV aparecen
        como filas de NaN.
    """
    balance_norm = _reindex_to_canonical(
        sections.get("BALANCE", pd.DataFrame()), BALANCE_ACCOUNTS_CL
    )
    income_norm = _reindex_to_canonical(
        sections.get("EERR", pd.DataFrame()), INCOME_ACCOUNTS_CL
    )
    cashflow_norm = _reindex_to_canonical(
        sections.get("EFE", pd.DataFrame()), CASHFLOW_ACCOUNTS_CL
    )
    return balance_norm, income_norm, cashflow_norm


def _reindex_to_canonical(df: Optional[pd.DataFrame], canonical_accounts: list[str]) -> pd.DataFrame:
    """
    Reindexea un DataFrame de sección a la lista completa de cuentas canónicas.

    Las cuentas presentes en canonical_accounts pero ausentes en el DataFrame
    aparecen como filas de NaN.  Se conservan solo las columnas de año (4 dígitos)
    ordenadas de mayor a menor.

    Args:
        df: DataFrame con cuentas como índice y años como columnas.
        canonical_accounts: Lista ordenada de cuentas canónicas destino.

    Returns:
        DataFrame reindexado con orden canónico.
    """
    if df is None or df.empty:
        return pd.DataFrame(index=canonical_accounts)

    df = df.copy()
    # Estandarizar columnas
    df.columns = [str(c).strip() for c in df.columns]
    df = df[[c for c in df.columns if c and not c.startswith("Unnamed:")]]

    # Conversión numérica explícita
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Ordenar columnas de año de mayor a menor
    year_cols = sorted(
        [c for c in df.columns if re.match(r"^\d{4}$", c)],
        reverse=True,
    )
    other_cols = [c for c in df.columns if c not in year_cols]
    df = df[year_cols + other_cols]

    # Reindexar a cuentas canónicas (introduce NaN para ausentes)
    result = df.reindex(canonical_accounts)
    result.index.name = "cuenta"
    return result


# ---------------------------------------------------------------------------
# Derivación de cuentas faltantes
# ---------------------------------------------------------------------------


def derive_missing_accounts_cl(
    balance_df: pd.DataFrame,
    income_df: pd.DataFrame,
    cashflow_df: pd.DataFrame,
    profile_type: str,
) -> dict:
    """
    Deriva cuentas canónicas faltantes cuando es razonable hacerlo.

    Reglas de derivación:
    - EBITDA = ebit + depreciacion_y_amortizacion (si EBITDA no existe)
    - EBIT = resultado_operacional (si EBIT no existe)
    - flujo_libre_de_caja = flujo_operacional + capex (capex suele ser negativo)
    - deuda_financiera_total = corto_plazo + largo_plazo

    Args:
        balance_df: Balance normalizado.
        income_df: EERR normalizado.
        cashflow_df: EFE normalizado.
        profile_type: Tipo de empresa.

    Returns:
        dict con cuentas derivadas como DataFrames de series temporales.
        Sólo incluye cuentas que fueron efectivamente derivadas.
    """
    derived: dict = {}

    # --- Derivar EBIT desde resultado_operacional ---
    if not income_df.empty:
        if "ebit" not in income_df.index and "resultado_operacional" in income_df.index:
            derived["ebit"] = income_df.loc["resultado_operacional"]

        # --- Derivar EBITDA desde EBIT + D&A ---
        ebit_source = income_df.loc["ebit"] if "ebit" in income_df.index else derived.get("ebit")
        da_source = income_df.loc["depreciacion_y_amortizacion"] if "depreciacion_y_amortizacion" in income_df.index else None

        if "ebitda" not in income_df.index and ebit_source is not None and da_source is not None:
            try:
                ebitda = pd.to_numeric(ebit_source, errors="coerce") + pd.to_numeric(da_source, errors="coerce").abs()
                derived["ebitda"] = ebitda
            except Exception:
                pass

    # --- Derivar flujo_libre_de_caja ---
    if not cashflow_df.empty:
        if "flujo_libre_de_caja" not in cashflow_df.index:
            op_source = cashflow_df.loc["flujo_operacional"] if "flujo_operacional" in cashflow_df.index else None
            capex_source = cashflow_df.loc["capex"] if "capex" in cashflow_df.index else None

            if op_source is not None and capex_source is not None:
                try:
                    op = pd.to_numeric(op_source, errors="coerce")
                    capex = pd.to_numeric(capex_source, errors="coerce")
                    # CAPEX es típicamente negativo en los datos; FCF = op + capex
                    fcf = op + capex
                    # Si el resultado es negativo pero el capex era positivo, ajustar
                    if (fcf < 0).all() and (capex > 0).all():
                        fcf = op - capex
                    derived["flujo_libre_de_caja"] = fcf
                except Exception:
                    pass

    # --- Derivar deuda_financiera_total (útil para métricas) ---
    if not balance_df.empty:
        cp_debt = balance_df.loc["deuda_financiera_corto_plazo"] if "deuda_financiera_corto_plazo" in balance_df.index else None
        lp_debt = balance_df.loc["deuda_financiera_largo_plazo"] if "deuda_financiera_largo_plazo" in balance_df.index else None

        if cp_debt is not None and lp_debt is not None:
            try:
                deuda_total = pd.to_numeric(cp_debt, errors="coerce").abs() + pd.to_numeric(lp_debt, errors="coerce").abs()
                derived["deuda_financiera_total"] = deuda_total
            except Exception:
                pass
        elif lp_debt is not None:
            derived["deuda_financiera_total"] = pd.to_numeric(lp_debt, errors="coerce").abs()
        elif cp_debt is not None:
            derived["deuda_financiera_total"] = pd.to_numeric(cp_debt, errors="coerce").abs()

    return derived
