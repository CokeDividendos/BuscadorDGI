# src/services/chile_schema.py
"""
Esquema contable canónico para empresas chilenas.

Define las cuentas estándar en español para Balance General,
Estado de Resultados y Estado de Flujo de Efectivo.
También define las claves de metadatos aceptadas en la sección METADATA
del formato EEFF_Chile_<TICKER>.csv.
Estas cuentas son el eje central de toda la lógica de Buscador CL.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Cuentas de metadatos (sección METADATA del CSV único)
# ---------------------------------------------------------------------------

METADATA_ACCOUNTS_CL: list[str] = [
    "acciones_promedio",
    "acciones_en_circulacion",
]

# ---------------------------------------------------------------------------
# Cuentas canónicas del Balance General
# ---------------------------------------------------------------------------

BALANCE_ACCOUNTS_CL: list[str] = [
    # Activos corrientes
    "efectivo_y_equivalentes",
    "inversiones_corto_plazo",
    "deudores_comerciales",
    "inventarios",
    "otros_activos_corrientes",
    "activos_corrientes",
    # Activos no corrientes
    "propiedades_planta_y_equipo",
    "propiedades_de_inversion",
    "activos_biologicos",
    "intangibles",
    "goodwill",
    "otros_activos_no_corrientes",
    "activos_no_corrientes",
    # Total activos
    "activos_totales",
    # Pasivos corrientes
    "cuentas_por_pagar",
    "deuda_financiera_corto_plazo",
    "pasivos_arrendamiento_corriente",
    "otros_pasivos_corrientes",
    "pasivos_corrientes",
    # Pasivos no corrientes
    "deuda_financiera_largo_plazo",
    "pasivos_arrendamiento_no_corriente",
    "impuestos_diferidos",
    "otros_pasivos_no_corrientes",
    "pasivos_no_corrientes",
    # Total pasivos y patrimonio
    "pasivos_totales",
    "ganancias_acumuladas",
    "participaciones_no_controladoras",
    "patrimonio_total",
]

# ---------------------------------------------------------------------------
# Cuentas canónicas del Estado de Resultados
# ---------------------------------------------------------------------------

INCOME_ACCOUNTS_CL: list[str] = [
    "ingresos",
    "costo_de_ventas",
    "ganancia_bruta",
    "gastos_de_administracion",
    "gastos_de_distribucion",
    "otros_ingresos_operacionales",
    "otros_gastos_operacionales",
    "resultado_operacional",
    "depreciacion_y_amortizacion",
    "ebit",
    "ebitda",
    "ingresos_financieros",
    "costos_financieros",
    "resultado_por_tipo_de_cambio",
    "participacion_en_asociadas",
    "resultado_antes_de_impuestos",
    "impuesto_a_las_ganancias",
    "ganancia_neta",
    "ganancia_neta_controladora",
    "eps_basico",
    "acciones_promedio",
]

# ---------------------------------------------------------------------------
# Cuentas canónicas del Estado de Flujo de Efectivo
# ---------------------------------------------------------------------------

CASHFLOW_ACCOUNTS_CL: list[str] = [
    "flujo_operacional",
    "intereses_recibidos",
    "intereses_pagados",
    "impuestos_pagados",
    "capex",
    "venta_de_activos",
    "adquisiciones",
    "dividendos_pagados",
    "deuda_emitida",
    "deuda_pagada",
    "pagos_de_arrendamiento",
    "flujo_libre_de_caja",
]

# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


def get_metadata_accounts_cl() -> list[str]:
    """Retorna lista de claves de metadatos del CSV único chileno."""
    return list(METADATA_ACCOUNTS_CL)


def get_balance_accounts_cl() -> list[str]:
    """Retorna lista de cuentas canónicas del Balance General chileno."""
    return list(BALANCE_ACCOUNTS_CL)


def get_income_accounts_cl() -> list[str]:
    """Retorna lista de cuentas canónicas del Estado de Resultados chileno."""
    return list(INCOME_ACCOUNTS_CL)


def get_cashflow_accounts_cl() -> list[str]:
    """Retorna lista de cuentas canónicas del Estado de Flujo de Efectivo chileno."""
    return list(CASHFLOW_ACCOUNTS_CL)


def get_all_accounts_cl() -> dict[str, list[str]]:
    """
    Retorna un diccionario con todas las cuentas canónicas chilenas
    agrupadas por tipo de estado financiero.

    Returns:
        dict con claves 'metadata', 'balance', 'income', 'cashflow', cada una
        conteniendo la lista de cuentas canónicas correspondiente.
    """
    return {
        "metadata": get_metadata_accounts_cl(),
        "balance": get_balance_accounts_cl(),
        "income": get_income_accounts_cl(),
        "cashflow": get_cashflow_accounts_cl(),
    }
