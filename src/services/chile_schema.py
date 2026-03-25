# src/services/chile_schema.py
"""
Esquema contable para Buscador CL.

Este módulo define dos niveles de cuentas:

1) ESQUEMA DE ENTRADA (CSV amplio final)
   Corresponde al formato oficial de EEFF_Chile_<TICKER>.csv con secciones:
   - METADATA
   - BALANCE
   - EERR
   - EFE

2) ESQUEMA OPERATIVO INTERNO
   Corresponde a las cuentas "cortas" que ya usan chile_metrics.py y chile_charts.py.

La estrategia correcta es:
- validar/aceptar el CSV amplio como entrada
- traducirlo internamente al esquema operativo corto
- mantener métricas y gráficos sin romperse
"""

from __future__ import annotations


# =============================================================================
# ESQUEMA OPERATIVO INTERNO (el que usan métricas y gráficos)
# =============================================================================

METADATA_ACCOUNTS_CL: list[str] = [
    "acciones_promedio",
    "acciones_en_circulacion",
]

BALANCE_ACCOUNTS_CL: list[str] = [
    "efectivo_y_equivalentes",
    "inversiones_corto_plazo",
    "deudores_comerciales",
    "inventarios",
    "otros_activos_corrientes",
    "activos_corrientes",
    "propiedades_planta_y_equipo",
    "propiedades_de_inversion",
    "activos_biologicos",
    "intangibles",
    "goodwill",
    "otros_activos_no_corrientes",
    "activos_no_corrientes",
    "activos_totales",
    "cuentas_por_pagar",
    "deuda_financiera_corto_plazo",
    "pasivos_arrendamiento_corriente",
    "otros_pasivos_corrientes",
    "pasivos_corrientes",
    "deuda_financiera_largo_plazo",
    "pasivos_arrendamiento_no_corriente",
    "impuestos_diferidos",
    "otros_pasivos_no_corrientes",
    "pasivos_no_corrientes",
    "pasivos_totales",
    "ganancias_acumuladas",
    "participaciones_no_controladoras",
    "patrimonio_total",
]

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


# =============================================================================
# ESQUEMA DE ENTRADA (CSV amplio final)
# =============================================================================

CSV_METADATA_ACCOUNTS_CL: list[str] = [
    "ticker",
    "nombre_empresa",
    "profile_type",
    "sector",
    "moneda_reporte",
    "unidad_reporte",
    "formato_eerr",
]

CSV_BALANCE_ACCOUNTS_CL: list[str] = [
    "efectivo_y_equivalentes",
    "activos_financieros_a_valor_razonable_corrientes",
    "otros_activos_financieros_corrientes",
    "otros_activos_no_financieros_corrientes",
    "deudores_comerciales_y_otras_cuentas_por_cobrar_corrientes",
    "cuentas_por_cobrar_a_entidades_relacionadas_corrientes",
    "inventarios",
    "activos_por_impuestos_corrientes",
    "pagos_anticipados_corrientes",
    "activos_biologicos_corrientes",
    "otros_activos_corrientes",
    "total_activos_corrientes",
    "encaje",
    "otros_activos_financieros_no_corrientes",
    "deudores_comerciales_y_otras_cuentas_por_cobrar_no_corrientes",
    "cuentas_por_cobrar_a_entidades_relacionadas_no_corrientes",
    "inversiones_contabilizadas_usando_metodo_de_participacion",
    "activos_intangibles",
    "plusvalia",
    "propiedades_planta_y_equipo",
    "propiedades_de_inversion",
    "activos_por_derecho_de_uso",
    "activos_biologicos_no_corrientes",
    "activos_por_impuestos_diferidos",
    "pagos_anticipados_no_corrientes",
    "otros_activos_no_corrientes",
    "total_activos_no_corrientes",
    "total_activos",
    "prestamos_y_obligaciones_financieras_corrientes",
    "otros_pasivos_financieros_corrientes",
    "pasivos_por_arrendamiento_corrientes",
    "acreedores_comerciales_y_otras_cuentas_por_pagar_corrientes",
    "cuentas_por_pagar_a_entidades_relacionadas_corrientes",
    "provisiones_corrientes",
    "pasivos_por_impuestos_corrientes",
    "pasivos_acumulados_o_devengados_corrientes",
    "provisiones_corrientes_por_beneficios_a_los_empleados",
    "otros_pasivos_no_financieros_corrientes",
    "total_pasivos_corrientes",
    "prestamos_y_obligaciones_financieras_no_corrientes",
    "otros_pasivos_financieros_no_corrientes",
    "pasivos_por_arrendamiento_no_corrientes",
    "acreedores_comerciales_y_otras_cuentas_por_pagar_no_corrientes",
    "cuentas_por_pagar_a_entidades_relacionadas_no_corrientes",
    "otras_provisiones_no_corrientes",
    "pasivos_por_impuestos_diferidos",
    "obligaciones_por_beneficios_post_empleo",
    "provisiones_no_corrientes_por_beneficios_a_los_empleados",
    "otros_pasivos_no_financieros_no_corrientes",
    "total_pasivos_no_corrientes",
    "total_pasivos",
    "capital_emitido",
    "acciones_propias_en_cartera",
    "otras_reservas",
    "resultados_retenidos_o_ganancias_acumuladas",
    "patrimonio_atribuible_a_los_propietarios_de_la_controladora",
    "participaciones_no_controladoras",
    "total_patrimonio",
    "acciones_emitidas",
]

CSV_INCOME_ACCOUNTS_CL: list[str] = [
    "ingresos_ordinarios",
    "ingresos_por_comisiones",
    "rentabilidad_del_encaje",
    "prima_seguro_invalidez_y_sobrevivencia",
    "costo_de_ventas",
    "materias_primas_y_consumibles_utilizados",
    "ganancia_bruta",
    "otros_ingresos_operacionales",
    "costos_de_distribucion",
    "gastos_de_administracion",
    "gastos_de_personal",
    "depreciacion_y_amortizacion",
    "perdidas_por_deterioro_reversiones_neto",
    "otros_gastos_varios_de_operacion",
    "otros_gastos_por_funcion_o_naturaleza",
    "resultado_operacional",
    "costos_financieros",
    "ingresos_financieros",
    "ganancia_perdida_procedente_de_inversiones",
    "participacion_en_ganancias_perdidas_de_asociadas_y_negocios_conjuntos",
    "diferencias_de_cambio",
    "resultados_por_unidades_de_reajuste",
    "otras_ganancias_perdidas",
    "otros_ingresos_no_operacionales",
    "otros_gastos_no_operacionales",
    "resultado_antes_de_impuestos",
    "gasto_ingreso_por_impuestos_a_las_ganancias",
    "ganancia_neta_de_actividades_continuadas",
    "ganancia_perdida_de_actividades_descontinuadas",
    "ganancia_neta",
    "ganancia_atribuible_a_los_propietarios_de_la_controladora",
    "ganancia_atribuible_a_participaciones_no_controladoras",
    "ganancia_neta_controladora",
    "ganancia_por_accion_basica_total",
    "ganancia_por_accion_diluida_total",
    "acciones_promedio_ponderado_basico",
    "acciones_promedio_ponderado_diluido",
    "ebit",
    "ebitda",
]

CSV_CASHFLOW_ACCOUNTS_CL: list[str] = [
    "ingresos_por_comisiones_cobrados",
    "pagos_a_proveedores",
    "remuneraciones_pagadas",
    "otros_cobros_de_operacion",
    "otros_pagos_de_operacion",
    "dividendos_recibidos_clasificados_como_operacion",
    "intereses_recibidos_clasificados_como_operacion",
    "intereses_pagados_clasificados_como_operacion",
    "impuestos_a_las_ganancias_pagados",
    "otras_entradas_de_operacion",
    "otras_salidas_de_operacion",
    "flujo_neto_actividades_de_operacion",
    "ventas_de_propiedades_planta_y_equipo",
    "ventas_de_cuotas_del_encaje",
    "ventas_de_activos_financieros",
    "compras_de_propiedades_planta_y_equipo",
    "compras_de_propiedades_de_inversion",
    "compras_de_activos_intangibles",
    "compras_de_cuotas_del_encaje",
    "compras_de_activos_financieros",
    "pagos_por_adquisicion_de_filiales_o_negocios",
    "otras_entradas_de_inversion",
    "otras_salidas_de_inversion",
    "flujo_neto_actividades_de_inversion",
    "obtencion_de_prestamos",
    "pago_de_prestamos",
    "pago_de_pasivos_por_arrendamiento",
    "dividendos_pagados",
    "otras_entradas_de_financiacion",
    "otras_salidas_de_financiacion",
    "flujo_neto_actividades_de_financiacion",
    "incremento_disminucion_neta_de_efectivo",
    "efectos_variacion_tipo_cambio_en_efectivo",
    "efectivo_inicial",
    "efectivo_final",
    "capex",
    "flujo_libre_de_caja",
]


def get_metadata_accounts_cl() -> list[str]:
    return list(METADATA_ACCOUNTS_CL)


def get_balance_accounts_cl() -> list[str]:
    return list(BALANCE_ACCOUNTS_CL)


def get_income_accounts_cl() -> list[str]:
    return list(INCOME_ACCOUNTS_CL)


def get_cashflow_accounts_cl() -> list[str]:
    return list(CASHFLOW_ACCOUNTS_CL)


def get_csv_metadata_accounts_cl() -> list[str]:
    return list(CSV_METADATA_ACCOUNTS_CL)


def get_csv_balance_accounts_cl() -> list[str]:
    return list(CSV_BALANCE_ACCOUNTS_CL)


def get_csv_income_accounts_cl() -> list[str]:
    return list(CSV_INCOME_ACCOUNTS_CL)


def get_csv_cashflow_accounts_cl() -> list[str]:
    return list(CSV_CASHFLOW_ACCOUNTS_CL)


def get_all_accounts_cl() -> dict:
    return {
        "metadata": get_metadata_accounts_cl(),
        "balance": get_balance_accounts_cl(),
        "income": get_income_accounts_cl(),
        "cashflow": get_cashflow_accounts_cl(),
    }


def get_all_csv_accounts_cl() -> dict:
    return {
        "metadata": get_csv_metadata_accounts_cl(),
        "balance": get_csv_balance_accounts_cl(),
        "income": get_csv_income_accounts_cl(),
        "cashflow": get_csv_cashflow_accounts_cl(),
    }


def validate_financial_template_cl(df_dict: dict) -> dict:
    """
    Validador tolerante del CSV amplio final.

    No bloquea el uso. Solo reporta:
    - cuentas presentes
    - cuentas esperadas faltantes
    - cuentas inesperadas
    """
    expected = get_all_csv_accounts_cl()
    section_map = {
        "METADATA": "metadata",
        "BALANCE": "balance",
        "EERR": "income",
        "EFE": "cashflow",
    }

    report: dict = {}

    for raw_section, logical_section in section_map.items():
        df = df_dict.get(raw_section)
        expected_accounts = set(expected[logical_section])

        if df is None or df.empty:
            report[raw_section] = {
                "presentes": [],
                "faltantes": sorted(expected_accounts),
                "inesperadas": [],
            }
            continue

        present = set(str(idx).strip() for idx in df.index)
        report[raw_section] = {
            "presentes": sorted(present),
            "faltantes": sorted(expected_accounts - present),
            "inesperadas": sorted(present - expected_accounts),
        }

    return report
