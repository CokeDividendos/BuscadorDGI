# src/services/chile_charts.py
"""
Gráficos específicos para empresas chilenas.

Cada función genera un gráfico Plotly orientado a Chile, usando
cuentas canónicas en español y lógica financiera apropiada por perfil.

Los gráficos se seleccionan según el profile_type:
- normal: ingresos, márgenes, EPS, deuda neta, EV/EBITDA, FCF, dividendos
- utility: EBITDA, deuda neta/EBITDA, capex vs. flujo, cobertura
- reit_concesion: ingresos, EBITDA, payout flujo, propiedades, deuda/activos
- financiera: ROE, valor libro, P/B, dividendos, payout
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd
import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# Constantes de estilo
# ---------------------------------------------------------------------------

# Umbrales de referencia para Deuda Neta / EBITDA
_DEUDA_EBITDA_ALTO = 3.5   # nivel de alerta rojo
_DEUDA_EBITDA_MEDIO = 2.0  # nivel de alerta amarillo

_COLOR_PRIMARIO = "#01c2ef"
_COLOR_SECUNDARIO = "#f0a500"
_COLOR_POSITIVO = "#00c49a"
_COLOR_NEGATIVO = "#e05c5c"
_COLOR_NEUTRO = "#8888aa"
_BG_COLOR = "#141f41"
_GRID_COLOR = "rgba(255,255,255,0.08)"
_FONT_COLOR = "#ffffff"

_LAYOUT_BASE = dict(
    paper_bgcolor=_BG_COLOR,
    plot_bgcolor=_BG_COLOR,
    font=dict(color=_FONT_COLOR, size=12),
    margin=dict(l=40, r=20, t=50, b=40),
    xaxis=dict(gridcolor=_GRID_COLOR, showgrid=True),
    yaxis=dict(gridcolor=_GRID_COLOR, showgrid=True),
)


def _base_layout(title: str, **kwargs) -> dict:
    """Retorna layout base con título personalizado."""
    layout = dict(_LAYOUT_BASE)
    layout["title"] = dict(text=title, font=dict(color=_FONT_COLOR, size=14))
    layout.update(kwargs)
    return layout


def _series_to_xy(series: pd.Series) -> tuple[list, list]:
    """Convierte una Serie temporal a listas de x (años) e y (valores)."""
    if series is None or series.empty:
        return [], []
    s = series.sort_index(ascending=True)  # cronológico para gráficos
    return list(s.index.astype(str)), list(s.values)


def _format_label(value: float, moneda: str = "CLP", unidad: int = 1) -> str:
    """Formatea un valor para mostrar en tooltips."""
    try:
        v = float(value) * unidad
        if abs(v) >= 1e9:
            return f"{moneda} {v/1e9:.2f}B"
        elif abs(v) >= 1e6:
            return f"{moneda} {v/1e6:.1f}M"
        elif abs(v) >= 1e3:
            return f"{moneda} {v/1e3:.1f}K"
        return f"{moneda} {v:.0f}"
    except Exception:
        return str(value)


# ---------------------------------------------------------------------------
# Gráficos comunes (usados en múltiples perfiles)
# ---------------------------------------------------------------------------


def plot_ingresos_cl(
    ticker: str,
    ingresos_series: pd.Series,
    moneda: str = "CLP",
) -> Optional[go.Figure]:
    """
    Gráfico de barras de ingresos históricos.

    Args:
        ticker: Código de la empresa.
        ingresos_series: Serie con años como índice e ingresos como valores.
        moneda: Moneda de reporte.

    Returns:
        Figura Plotly o None si no hay datos.
    """
    x, y = _series_to_xy(ingresos_series)
    if not x:
        return None

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=x, y=y,
        name="Ingresos",
        marker_color=_COLOR_PRIMARIO,
        hovertemplate="%{x}: %{y:,.0f}<extra></extra>",
    ))
    fig.update_layout(_base_layout(f"{ticker} — Ingresos ({moneda})"))
    return fig


def plot_margenes_cl(
    ticker: str,
    margen_bruto: Optional[pd.Series] = None,
    margen_operacional: Optional[pd.Series] = None,
    margen_neto: Optional[pd.Series] = None,
    margen_ebitda: Optional[pd.Series] = None,
) -> Optional[go.Figure]:
    """
    Gráfico de líneas con evolución de márgenes.

    Args:
        ticker: Código de la empresa.
        margen_bruto, margen_operacional, margen_neto, margen_ebitda:
            Series de márgenes (valores entre 0 y 1).

    Returns:
        Figura Plotly o None si no hay ningún margen disponible.
    """
    traces = []
    series_map = {
        "Margen Bruto": (margen_bruto, _COLOR_PRIMARIO),
        "Margen Operacional": (margen_operacional, _COLOR_SECUNDARIO),
        "Margen Neto": (margen_neto, _COLOR_POSITIVO),
        "Margen EBITDA": (margen_ebitda, _COLOR_NEUTRO),
    }

    for name, (series, color) in series_map.items():
        if series is not None and not series.empty:
            x, y = _series_to_xy(series)
            y_pct = [v * 100 if v is not None and not pd.isna(v) else None for v in y]
            traces.append(go.Scatter(
                x=x, y=y_pct, name=name,
                line=dict(color=color, width=2),
                mode="lines+markers",
                hovertemplate="%{x}: %{y:.1f}%<extra></extra>",
            ))

    if not traces:
        return None

    fig = go.Figure(data=traces)
    fig.update_layout(_base_layout(
        f"{ticker} — Márgenes (%)",
        yaxis=dict(ticksuffix="%", gridcolor=_GRID_COLOR),
    ))
    return fig


def plot_eps_cl(
    ticker: str,
    eps_series: pd.Series,
    moneda: str = "CLP",
) -> Optional[go.Figure]:
    """
    Gráfico de barras de EPS histórico.

    Args:
        ticker: Código de la empresa.
        eps_series: Serie de EPS por año.
        moneda: Moneda.

    Returns:
        Figura Plotly o None si no hay datos.
    """
    x, y = _series_to_xy(eps_series)
    if not x:
        return None

    colors = [_COLOR_POSITIVO if v >= 0 else _COLOR_NEGATIVO for v in y]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=x, y=y, name="EPS",
        marker_color=colors,
        hovertemplate="%{x}: %{y:.2f}<extra></extra>",
    ))
    fig.update_layout(_base_layout(f"{ticker} — EPS ({moneda})"))
    return fig


def plot_deuda_cl(
    ticker: str,
    deuda_cp: Optional[pd.Series] = None,
    deuda_lp: Optional[pd.Series] = None,
    efectivo: Optional[pd.Series] = None,
    moneda: str = "CLP",
) -> Optional[go.Figure]:
    """
    Gráfico de deuda financiera por tramos vs. efectivo.

    Args:
        ticker: Código de la empresa.
        deuda_cp, deuda_lp: Deuda corto y largo plazo.
        efectivo: Efectivo y equivalentes.
        moneda: Moneda.

    Returns:
        Figura Plotly o None si no hay datos.
    """
    traces = []

    if deuda_cp is not None and not deuda_cp.empty:
        x, y = _series_to_xy(deuda_cp.abs())
        traces.append(go.Bar(x=x, y=y, name="Deuda CP",
                             marker_color=_COLOR_NEGATIVO,
                             hovertemplate="%{x}: %{y:,.0f}<extra></extra>"))

    if deuda_lp is not None and not deuda_lp.empty:
        x, y = _series_to_xy(deuda_lp.abs())
        traces.append(go.Bar(x=x, y=y, name="Deuda LP",
                             marker_color="#c44",
                             hovertemplate="%{x}: %{y:,.0f}<extra></extra>"))

    if efectivo is not None and not efectivo.empty:
        x, y = _series_to_xy(efectivo)
        traces.append(go.Bar(x=x, y=y, name="Efectivo",
                             marker_color=_COLOR_POSITIVO,
                             hovertemplate="%{x}: %{y:,.0f}<extra></extra>"))

    if not traces:
        return None

    fig = go.Figure(data=traces)
    fig.update_layout(_base_layout(
        f"{ticker} — Estructura de Deuda ({moneda})",
        barmode="group",
    ))
    return fig


def plot_deuda_neta_ebitda_cl(
    ticker: str,
    deuda_neta_ebitda_series: pd.Series,
) -> Optional[go.Figure]:
    """
    Gráfico de línea: Deuda Neta / EBITDA histórico.

    Args:
        ticker: Código de la empresa.
        deuda_neta_ebitda_series: Serie del ratio.

    Returns:
        Figura Plotly o None si no hay datos.
    """
    x, y = _series_to_xy(deuda_neta_ebitda_series)
    if not x:
        return None

    colors = [_COLOR_NEGATIVO if v > _DEUDA_EBITDA_ALTO else _COLOR_SECUNDARIO if v > _DEUDA_EBITDA_MEDIO else _COLOR_POSITIVO for v in y]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=x, y=y, name="Deuda Neta / EBITDA",
        marker_color=colors,
        hovertemplate="%{x}: %{y:.2f}x<extra></extra>",
    ))
    # Línea de referencia
    fig.add_hline(y=_DEUDA_EBITDA_ALTO, line_dash="dot", line_color=_COLOR_NEGATIVO,
                  annotation_text=f"{_DEUDA_EBITDA_ALTO}x", annotation_font_color=_COLOR_NEGATIVO)
    fig.update_layout(_base_layout(f"{ticker} — Deuda Neta / EBITDA"))
    return fig


def plot_flujo_operacional_vs_capex_cl(
    ticker: str,
    flujo_op: Optional[pd.Series] = None,
    capex: Optional[pd.Series] = None,
    fcf: Optional[pd.Series] = None,
    moneda: str = "CLP",
) -> Optional[go.Figure]:
    """
    Gráfico de flujo operacional vs. CAPEX vs. FCL.

    Args:
        ticker: Código de la empresa.
        flujo_op, capex, fcf: Series de flujo.
        moneda: Moneda.

    Returns:
        Figura Plotly o None si no hay datos.
    """
    traces = []

    if flujo_op is not None and not flujo_op.empty:
        x, y = _series_to_xy(flujo_op)
        traces.append(go.Bar(x=x, y=y, name="Flujo Operacional",
                             marker_color=_COLOR_PRIMARIO,
                             hovertemplate="%{x}: %{y:,.0f}<extra></extra>"))

    if capex is not None and not capex.empty:
        x, y = _series_to_xy(capex.abs())
        traces.append(go.Bar(x=x, y=y, name="CAPEX",
                             marker_color=_COLOR_NEGATIVO,
                             hovertemplate="%{x}: %{y:,.0f}<extra></extra>"))

    if fcf is not None and not fcf.empty:
        x, y = _series_to_xy(fcf)
        traces.append(go.Scatter(x=x, y=y, name="FCL",
                                 line=dict(color=_COLOR_POSITIVO, width=2),
                                 mode="lines+markers",
                                 hovertemplate="%{x}: %{y:,.0f}<extra></extra>"))

    if not traces:
        return None

    fig = go.Figure(data=traces)
    fig.update_layout(_base_layout(
        f"{ticker} — Flujo Operacional vs CAPEX ({moneda})",
        barmode="group",
    ))
    return fig


def plot_dividendos_seguridad_cl(
    ticker: str,
    dividendos: Optional[pd.Series] = None,
    ganancia_neta: Optional[pd.Series] = None,
    fcf: Optional[pd.Series] = None,
    moneda: str = "CLP",
) -> Optional[go.Figure]:
    """
    Gráfico de seguridad de dividendos: dividendos vs. utilidad neta y FCL.

    Args:
        ticker: Código de la empresa.
        dividendos, ganancia_neta, fcf: Series de valores.
        moneda: Moneda.

    Returns:
        Figura Plotly o None si no hay datos de dividendos.
    """
    if dividendos is None or dividendos.empty:
        return None

    traces = []
    x, y = _series_to_xy(dividendos.abs())
    traces.append(go.Bar(x=x, y=y, name="Dividendos Pagados",
                         marker_color=_COLOR_SECUNDARIO,
                         hovertemplate="%{x}: %{y:,.0f}<extra></extra>"))

    if ganancia_neta is not None and not ganancia_neta.empty:
        x2, y2 = _series_to_xy(ganancia_neta)
        traces.append(go.Scatter(x=x2, y=y2, name="Ganancia Neta",
                                 line=dict(color=_COLOR_PRIMARIO, width=2),
                                 mode="lines+markers",
                                 hovertemplate="%{x}: %{y:,.0f}<extra></extra>"))

    if fcf is not None and not fcf.empty:
        x3, y3 = _series_to_xy(fcf)
        traces.append(go.Scatter(x=x3, y=y3, name="FCL",
                                 line=dict(color=_COLOR_POSITIVO, width=2, dash="dot"),
                                 mode="lines+markers",
                                 hovertemplate="%{x}: %{y:,.0f}<extra></extra>"))

    fig = go.Figure(data=traces)
    fig.update_layout(_base_layout(
        f"{ticker} — Seguridad del Dividendo ({moneda})",
        barmode="overlay",
    ))
    return fig


def plot_valor_libro_cl(
    ticker: str,
    valor_libro_series: pd.Series,
    moneda: str = "CLP",
) -> Optional[go.Figure]:
    """
    Gráfico de evolución del valor libro por acción.

    Args:
        ticker: Código de la empresa.
        valor_libro_series: Serie de valor libro por acción.
        moneda: Moneda.

    Returns:
        Figura Plotly o None si no hay datos.
    """
    x, y = _series_to_xy(valor_libro_series)
    if not x:
        return None

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=y, name="Valor Libro / Acción",
        fill="tozeroy",
        fillcolor=f"rgba(1, 194, 239, 0.15)",
        line=dict(color=_COLOR_PRIMARIO, width=2),
        mode="lines+markers",
        hovertemplate="%{x}: %{y:,.2f}<extra></extra>",
    ))
    fig.update_layout(_base_layout(f"{ticker} — Valor Libro por Acción ({moneda})"))
    return fig


def plot_pb_cl(
    ticker: str,
    pb_actual: float,
) -> Optional[go.Figure]:
    """
    Indicador gauge del P/B actual.

    Args:
        ticker: Código de la empresa.
        pb_actual: Ratio Precio / Valor Libro actual.

    Returns:
        Figura Plotly o None si pb_actual no es válido.
    """
    if pb_actual is None or pd.isna(pb_actual):
        return None

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=pb_actual,
        title={"text": f"{ticker} — P/B Actual", "font": {"color": _FONT_COLOR}},
        gauge={
            "axis": {"range": [0, 5], "tickcolor": _FONT_COLOR},
            "bar": {"color": _COLOR_PRIMARIO},
            "steps": [
                {"range": [0, 1], "color": _COLOR_POSITIVO},
                {"range": [1, 2], "color": _COLOR_SECUNDARIO},
                {"range": [2, 5], "color": _COLOR_NEGATIVO},
            ],
            "threshold": {
                "line": {"color": _FONT_COLOR, "width": 2},
                "thickness": 0.75,
                "value": pb_actual,
            },
        },
        number={"font": {"color": _FONT_COLOR}, "suffix": "x"},
    ))
    fig.update_layout(
        paper_bgcolor=_BG_COLOR,
        font=dict(color=_FONT_COLOR),
        margin=dict(l=20, r=20, t=50, b=20),
    )
    return fig


def plot_roe_cl(
    ticker: str,
    roe_series: pd.Series,
) -> Optional[go.Figure]:
    """
    Gráfico de evolución del ROE.

    Args:
        ticker: Código de la empresa.
        roe_series: Serie de ROE (valores entre 0 y 1).

    Returns:
        Figura Plotly o None si no hay datos.
    """
    x, y = _series_to_xy(roe_series)
    if not x:
        return None

    y_pct = [v * 100 if v is not None and not pd.isna(v) else None for v in y]
    colors = [_COLOR_POSITIVO if v is not None and v >= 0 else _COLOR_NEGATIVO for v in y_pct]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=x, y=y_pct, name="ROE",
        marker_color=colors,
        hovertemplate="%{x}: %{y:.1f}%<extra></extra>",
    ))
    fig.update_layout(_base_layout(
        f"{ticker} — ROE (%)",
        yaxis=dict(ticksuffix="%", gridcolor=_GRID_COLOR),
    ))
    return fig


def plot_metricas_reit_cl(
    ticker: str,
    propiedades_sobre_activos: Optional[pd.Series] = None,
    deuda_sobre_activos: Optional[pd.Series] = None,
    payout_flujo: Optional[pd.Series] = None,
) -> Optional[go.Figure]:
    """
    Gráfico de métricas específicas para REIT/concesión.

    Muestra propiedades de inversión sobre activos, deuda sobre activos
    y payout sobre flujo como series de líneas normalizadas (%).

    Args:
        ticker: Código de la empresa.
        propiedades_sobre_activos, deuda_sobre_activos, payout_flujo: Series.

    Returns:
        Figura Plotly o None si no hay ninguna serie.
    """
    traces = []
    series_map = {
        "Prop. Inversión / Activos": (propiedades_sobre_activos, _COLOR_PRIMARIO),
        "Deuda / Activos": (deuda_sobre_activos, _COLOR_NEGATIVO),
        "Payout / Flujo Op.": (payout_flujo, _COLOR_SECUNDARIO),
    }

    for name, (series, color) in series_map.items():
        if series is not None and not series.empty:
            x, y = _series_to_xy(series)
            y_pct = [v * 100 if v is not None and not pd.isna(v) else None for v in y]
            traces.append(go.Scatter(
                x=x, y=y_pct, name=name,
                line=dict(color=color, width=2),
                mode="lines+markers",
                hovertemplate="%{x}: %{y:.1f}%<extra></extra>",
            ))

    if not traces:
        return None

    fig = go.Figure(data=traces)
    fig.update_layout(_base_layout(
        f"{ticker} — Métricas REIT/Concesión (%)",
        yaxis=dict(ticksuffix="%", gridcolor=_GRID_COLOR),
    ))
    return fig


def plot_ebitda_cl(
    ticker: str,
    ebitda_series: pd.Series,
    margen_ebitda: Optional[pd.Series] = None,
    moneda: str = "CLP",
) -> Optional[go.Figure]:
    """
    Gráfico combinado de EBITDA absoluto y margen EBITDA (eje secundario).

    Args:
        ticker: Código de la empresa.
        ebitda_series: Serie de EBITDA.
        margen_ebitda: Serie de margen EBITDA (0-1).
        moneda: Moneda.

    Returns:
        Figura Plotly o None si no hay datos.
    """
    x, y = _series_to_xy(ebitda_series)
    if not x:
        return None

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=x, y=y, name=f"EBITDA ({moneda})",
        marker_color=_COLOR_PRIMARIO,
        hovertemplate="%{x}: %{y:,.0f}<extra></extra>",
        yaxis="y1",
    ))

    if margen_ebitda is not None and not margen_ebitda.empty:
        x2, y2 = _series_to_xy(margen_ebitda)
        y2_pct = [v * 100 if v is not None and not pd.isna(v) else None for v in y2]
        fig.add_trace(go.Scatter(
            x=x2, y=y2_pct, name="Margen EBITDA (%)",
            line=dict(color=_COLOR_SECUNDARIO, width=2),
            mode="lines+markers",
            hovertemplate="%{x}: %{y:.1f}%<extra></extra>",
            yaxis="y2",
        ))

    layout = _base_layout(f"{ticker} — EBITDA")
    layout["yaxis2"] = dict(
        overlaying="y",
        side="right",
        ticksuffix="%",
        gridcolor=_GRID_COLOR,
        showgrid=False,
    )
    fig.update_layout(layout)
    return fig


# ---------------------------------------------------------------------------
# Selector de gráficos por perfil
# ---------------------------------------------------------------------------


def get_charts_for_profile_cl(
    ticker: str,
    metrics: dict,
    profile_type: str,
    moneda: str = "CLP",
) -> dict[str, Any]:
    """
    Genera el conjunto de gráficos apropiado para cada profile_type.

    Args:
        ticker: Código de la empresa.
        metrics: Dict de métricas calculado por chile_metrics.
        profile_type: Tipo de perfil de la empresa.
        moneda: Moneda de reporte.

    Returns:
        Dict donde la clave es el nombre del gráfico y el valor es la figura Plotly.
        Las figuras None son excluidas automáticamente.
    """
    charts: dict[str, Any] = {}

    # --- Gráficos comunes a todos los perfiles ---
    if "ingresos_series" in metrics:
        fig = plot_ingresos_cl(ticker, metrics["ingresos_series"], moneda)
        if fig:
            charts["ingresos"] = fig

    if "flujo_operacional_series" in metrics or "capex_series" in metrics or "flujo_libre_de_caja_series" in metrics:
        fig = plot_flujo_operacional_vs_capex_cl(
            ticker,
            flujo_op=metrics.get("flujo_operacional_series"),
            capex=metrics.get("capex_series"),
            fcf=metrics.get("flujo_libre_de_caja_series"),
            moneda=moneda,
        )
        if fig:
            charts["flujo_operacional_vs_capex"] = fig

    if "dividendos_pagados_series" in metrics:
        fig = plot_dividendos_seguridad_cl(
            ticker,
            dividendos=metrics.get("dividendos_pagados_series"),
            ganancia_neta=metrics.get("ganancia_neta_series"),
            fcf=metrics.get("flujo_libre_de_caja_series"),
            moneda=moneda,
        )
        if fig:
            charts["dividendos_seguridad"] = fig

    # --- Gráficos por perfil ---
    if profile_type == "normal":
        if any(k in metrics for k in ["margen_bruto_series", "margen_operacional_series", "margen_neto_series"]):
            fig = plot_margenes_cl(
                ticker,
                margen_bruto=metrics.get("margen_bruto_series"),
                margen_operacional=metrics.get("margen_operacional_series"),
                margen_neto=metrics.get("margen_neto_series"),
            )
            if fig:
                charts["margenes"] = fig

        if "eps_series" in metrics:
            fig = plot_eps_cl(ticker, metrics["eps_series"], moneda)
            if fig:
                charts["eps"] = fig

        if any(k in metrics for k in ["deuda_financiera_corto_plazo", "deuda_financiera_largo_plazo"]):
            fig = plot_deuda_cl(
                ticker,
                deuda_cp=metrics.get("deuda_cp_series"),
                deuda_lp=metrics.get("deuda_lp_series"),
                efectivo=metrics.get("efectivo_series"),
                moneda=moneda,
            )
            if fig:
                charts["deuda"] = fig

        if "deuda_neta_ebitda_series" in metrics:
            fig = plot_deuda_neta_ebitda_cl(ticker, metrics["deuda_neta_ebitda_series"])
            if fig:
                charts["deuda_neta_ebitda"] = fig

    elif profile_type == "utility":
        if "ebitda_series" in metrics:
            fig = plot_ebitda_cl(
                ticker,
                metrics["ebitda_series"],
                margen_ebitda=metrics.get("margen_ebitda_series"),
                moneda=moneda,
            )
            if fig:
                charts["ebitda"] = fig

        if "deuda_neta_ebitda_series" in metrics:
            fig = plot_deuda_neta_ebitda_cl(ticker, metrics["deuda_neta_ebitda_series"])
            if fig:
                charts["deuda_neta_ebitda"] = fig

    elif profile_type == "reit_concesion":
        if any(k in metrics for k in [
            "propiedades_inversion_sobre_activos_series",
            "deuda_sobre_activos_series",
            "payout_flujo_series",
        ]):
            fig = plot_metricas_reit_cl(
                ticker,
                propiedades_sobre_activos=metrics.get("propiedades_inversion_sobre_activos_series"),
                deuda_sobre_activos=metrics.get("deuda_sobre_activos_series"),
                payout_flujo=metrics.get("payout_flujo_series"),
            )
            if fig:
                charts["metricas_reit"] = fig

        if "ebitda_series" in metrics:
            fig = plot_ebitda_cl(ticker, metrics["ebitda_series"], moneda=moneda)
            if fig:
                charts["ebitda"] = fig

    elif profile_type == "financiera":
        if "roe_series" in metrics:
            fig = plot_roe_cl(ticker, metrics["roe_series"])
            if fig:
                charts["roe"] = fig

        if "valor_libro_por_accion_series" in metrics:
            fig = plot_valor_libro_cl(ticker, metrics["valor_libro_por_accion_series"], moneda)
            if fig:
                charts["valor_libro"] = fig

        if "pb" in metrics:
            fig = plot_pb_cl(ticker, metrics["pb"])
            if fig:
                charts["pb"] = fig

    return charts
