# src/services/chile_profiles.py
"""
Gestión de perfiles de empresas chilenas.

Cada empresa chilena tiene un perfil que determina:
- Tipo de empresa (normal, utility, reit_concesion, financiera)
- Moneda y unidad de reporte
- Sector
- Método de valoración preferido

Esto permite que chile_metrics y chile_charts apliquen la lógica
correcta según la naturaleza de cada empresa.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent
_PROFILES_PATH = _REPO_ROOT / "data" / "chile_company_profiles.csv"

# Tipos de perfil válidos
PROFILE_TYPES = {"normal", "utility", "reit_concesion", "financiera"}

# Perfil por defecto cuando no se encuentra el ticker
_DEFAULT_PROFILE: dict = {
    "ticker": "",
    "nombre_empresa": "",
    "profile_type": "normal",
    "moneda_reporte": "CLP",
    "unidad_reporte": 1,
    "sector": "",
    "valuation_method": "per_ev_ebitda",
}

# ---------------------------------------------------------------------------
# Carga de datos
# ---------------------------------------------------------------------------


def load_chile_company_profiles() -> pd.DataFrame:
    """
    Carga el archivo data/chile_company_profiles.csv.

    Returns:
        DataFrame con columnas: ticker, nombre_empresa, profile_type,
        moneda_reporte, unidad_reporte, sector, valuation_method.
        Retorna DataFrame vacío si el archivo no existe.
    """
    if not _PROFILES_PATH.exists():
        return pd.DataFrame(
            columns=[
                "ticker",
                "nombre_empresa",
                "profile_type",
                "moneda_reporte",
                "unidad_reporte",
                "sector",
                "valuation_method",
            ]
        )
    try:
        df = pd.read_csv(_PROFILES_PATH, sep=",", dtype=str).fillna("")
        df["ticker"] = df["ticker"].str.strip().str.upper()
        # Asegurar que unidad_reporte sea numérico
        unit_numeric = pd.to_numeric(df["unidad_reporte"], errors="coerce").fillna(1)
        df["unidad_reporte"] = unit_numeric.clip(lower=1).round().astype(int)
        return df
    except Exception:
        return pd.DataFrame(
            columns=[
                "ticker",
                "nombre_empresa",
                "profile_type",
                "moneda_reporte",
                "unidad_reporte",
                "sector",
                "valuation_method",
            ]
        )


# ---------------------------------------------------------------------------
# Consultas por ticker
# ---------------------------------------------------------------------------


def get_company_profile_cl(ticker: str) -> dict:
    """
    Retorna el perfil completo de una empresa chilena.

    Args:
        ticker: Código de la empresa (e.g. 'ANDINA-B').

    Returns:
        dict con: ticker, nombre_empresa, profile_type, moneda_reporte,
        unidad_reporte, sector, valuation_method.
        Si el ticker no existe, retorna perfil por defecto (tipo 'normal').
    """
    df = load_chile_company_profiles()
    if df.empty:
        profile = dict(_DEFAULT_PROFILE)
        profile["ticker"] = ticker.upper()
        return profile

    row = df[df["ticker"] == ticker.upper()]
    if row.empty:
        profile = dict(_DEFAULT_PROFILE)
        profile["ticker"] = ticker.upper()
        return profile

    return row.iloc[0].to_dict()


def get_profile_type_cl(ticker: str) -> str:
    """
    Retorna el tipo de perfil de una empresa chilena.

    Args:
        ticker: Código de la empresa (e.g. 'COLBUN').

    Returns:
        Uno de: 'normal', 'utility', 'reit_concesion', 'financiera'.
        Retorna 'normal' si el ticker no existe en el mapa de perfiles.
    """
    profile = get_company_profile_cl(ticker)
    ptype = profile.get("profile_type", "normal")
    if ptype not in PROFILE_TYPES:
        return "normal"
    return ptype


def get_reporting_metadata_cl(ticker: str) -> dict:
    """
    Retorna los metadatos de reporte de una empresa chilena.

    Args:
        ticker: Código de la empresa.

    Returns:
        dict con: moneda_reporte, unidad_reporte, sector, valuation_method.
        Valores por defecto: CLP, 1, '', 'per_ev_ebitda'.
    """
    profile = get_company_profile_cl(ticker)
    return {
        "moneda_reporte": profile.get("moneda_reporte", "CLP"),
        "unidad_reporte": int(profile.get("unidad_reporte", 1)),
        "sector": profile.get("sector", ""),
        "valuation_method": profile.get("valuation_method", "per_ev_ebitda"),
    }
