# src/pages/dividend_simulator.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from src.services.finance_data import get_price_data, get_dividend_kpis

# =========================================================
# Constants
# =========================================================
COLOR_PRIMARY = "#ff6d01"     # Orange
COLOR_SECONDARY = "#ff00ff"   # Magenta
COLOR_TERTIARY = "#01c2ef"    # Cyan
COLOR_BACKGROUND = "#141f41"  # Dark blue
COLOR_TEXT = "#ffffff"        # White


# =========================================================
# Helper Functions
# =========================================================
def _calculate_dividend_cagr(ticker: str) -> Optional[float]:
    """
    Calculate CAGR from dividend history using only complete calendar years.
    Returns None if insufficient data.
    """
    try:
        t = yf.Ticker(ticker)
        dividends = t.dividends
        
        if dividends is None or not isinstance(dividends, pd.Series) or dividends.empty:
            return None
        
        # Get only data from complete calendar years
        current_year = datetime.now().year
        complete_years_data = dividends[dividends.index.year < current_year]
        
        if complete_years_data.empty:
            return None
        
        # Aggregate to annual totals
        annual = complete_years_data.resample("YE").sum().dropna()
        
        if annual.empty or len(annual) < 2:
            return None
        
        first_val = float(annual.iloc[0])
        last_val = float(annual.iloc[-1])
        
        if first_val <= 0 or last_val <= 0:
            return None
        
        n_years = len(annual) - 1
        if n_years <= 0:
            return None
        
        cagr = (pow(last_val / first_val, 1.0 / n_years) - 1) * 100
        return cagr
        
    except Exception:
        return None


def _get_annual_dividend_from_ticker(ticker: str) -> Optional[float]:
    """
    Get annual dividend per share from ticker data.
    Returns trailing 12-month dividend sum.
    """
    try:
        div_kpis = get_dividend_kpis(ticker)
        return div_kpis.get("annual_div")
    except Exception:
        return None


def _calculate_kpis(df: pd.DataFrame, inversion_inicial: float, aportes_mensuales: float, 
                    inflacion_anual: float, anos_simulacion: int) -> dict:
    """
    Calculate all KPIs from simulation results.
    
    Args:
        df: DataFrame with simulation results
        inversion_inicial: Initial investment amount
        aportes_mensuales: Monthly contribution amount
        inflacion_anual: Annual inflation rate (as percentage)
        anos_simulacion: Number of years simulated
    
    Returns:
        dict with keys:
        - capital_total: Final portfolio value
        - aportes_totales: Total contributions
        - dividendos_totales: Total dividends collected
        - rentabilidad_total: Total return % (capital growth)
        - dividendo_mensual_final: Monthly dividend at end
        - costo_vida_final: Cost of living at end (inflation-adjusted)
        - ano_cobertura: Dict with "value" and "text" for coverage year
        - crecimiento_capital: Capital growth percentage
    """
    # Capital Total (último valor del portafolio)
    capital_total = df["Valor del Portafolio"].iloc[-1]
    
    # Aportes Totales
    aportes_totales = inversion_inicial + (aportes_mensuales * 12 * anos_simulacion)
    
    # Total Dividendos Cobrados (suma de todos los dividendos generados)
    dividendos_totales = df["Dividendos del Mes"].sum()
    
    # Rentabilidad Total % (same as capital growth %)
    # Note: In this simulation, dividends are automatically reinvested into shares,
    # so capital_total already includes the full value of all reinvested dividends.
    # Thus, this calculation represents true total return including dividend growth.
    rentabilidad_total = ((capital_total - aportes_totales) / aportes_totales) * 100 if aportes_totales > 0 else 0
    crecimiento_capital = rentabilidad_total  # Same value, different name for clarity
    
    # Dividendo Mensual Final
    dividendo_mensual_final = df["Dividendo Mensual Generado"].iloc[-1]
    
    # Costo de Vida Final (ajustado por inflación)
    costo_vida_final_mensual = df["Costo de Vida Ajustado"].iloc[-1]
    
    # Año de Cobertura - Calcular años y meses
    # Find first month where monthly dividend covers monthly cost of living
    anos_con_cobertura = df[df["% Cobertura"] >= 100]
    if not anos_con_cobertura.empty:
        # Get the first month when coverage is achieved
        first_coverage_row = anos_con_cobertura.iloc[0]
        ano_cobertura_num = first_coverage_row["Año"]
        mes_cobertura_num = first_coverage_row["Mes"]
        
        # Calculate total months
        total_meses = (ano_cobertura_num - 1) * 12 + mes_cobertura_num
        
        # Calculate años y meses
        anos = int(total_meses // 12)
        meses = int(total_meses % 12)
        
        # Formato del texto
        if anos == 0:
            if meses == 1:
                ano_cobertura_text = "1 mes"
            else:
                ano_cobertura_text = f"{meses} meses"
        elif anos == 1:
            if meses == 0:
                ano_cobertura_text = "1 año"
            elif meses == 1:
                ano_cobertura_text = "1 año y 1 mes"
            else:
                ano_cobertura_text = f"1 año y {meses} meses"
        else:
            if meses == 0:
                ano_cobertura_text = f"{anos} años"
            elif meses == 1:
                ano_cobertura_text = f"{anos} años y 1 mes"
            else:
                ano_cobertura_text = f"{anos} años y {meses} meses"
        
        ano_cobertura = {
            "value": ano_cobertura_num,
            "text": ano_cobertura_text
        }
    else:
        ano_cobertura = {
            "value": None,
            "text": f"No alcanzado en {anos_simulacion} años"
        }
    
    return {
        "capital_total": capital_total,
        "aportes_totales": aportes_totales,
        "dividendos_totales": dividendos_totales,
        "rentabilidad_total": rentabilidad_total,
        "dividendo_mensual_final": dividendo_mensual_final,
        "costo_vida_final": costo_vida_final_mensual,
        "ano_cobertura": ano_cobertura,
        "crecimiento_capital": crecimiento_capital,
    }


def _simulate_dividends(
    inversion_inicial: float,
    aportes_mensuales: float,
    costo_vida_mensual: float,
    inflacion_anual: float,
    rentabilidad_precio_anual: float,
    cagr_dividendo: float,
    tipo_distribucion: str,
    anos_simulacion: int,
    precio_actual: float,
    dividendo_anual: float,
) -> pd.DataFrame:
    """
    Simulate dividend portfolio growth with monthly granularity.
    
    Returns DataFrame with monthly simulation results.
    """
    # Initialize results list
    results = []
    
    # Convert percentages to decimals
    inflacion_decimal = inflacion_anual / 100
    rentabilidad_decimal = rentabilidad_precio_anual / 100
    cagr_decimal = cagr_dividendo / 100
    
    # Determine dividend frequency
    dividendos_por_ano = 4 if tipo_distribucion == "Trimestral" else 12
    
    # Initial values
    precio_proyectado = precio_actual
    dpa_proyectado = dividendo_anual
    acciones_inicial = inversion_inicial / precio_actual
    acciones_aportes_acum = 0.0
    dividendos_reinvertidos_acum = 0.0
    
    # Monthly simulation
    for ano in range(1, anos_simulacion + 1):
        for mes in range(1, 13):
            mes_absoluto = (ano - 1) * 12 + mes
            
            # Update price and DPA annually (at the start of each year)
            if mes == 1 and ano > 1:
                precio_proyectado *= (1 + rentabilidad_decimal)
                dpa_proyectado *= (1 + cagr_decimal)
            
            # Investment accumulation
            inversion_acumulada = inversion_inicial + (aportes_mensuales * mes_absoluto)
            
            # Shares purchased with monthly contributions
            if mes_absoluto == 1:
                acciones_mes_aportes = 0.0  # First month, only initial investment
            else:
                acciones_mes_aportes = aportes_mensuales / precio_proyectado
                acciones_aportes_acum += acciones_mes_aportes
            
            # Calculate if dividend is paid this month
            dividendos_mes = 0.0
            acciones_mes_reinversion = 0.0
            
            # Determine if this month pays dividends based on distribution type
            if tipo_distribucion == "Trimestral":
                # Quarterly: months 3, 6, 9, 12
                paga_dividendo = (mes % 3 == 0)
            else:
                # Monthly: every month
                paga_dividendo = True
            
            if paga_dividendo:
                dividendo_pago = dpa_proyectado / dividendos_por_ano
                acciones_totales = acciones_inicial + acciones_aportes_acum + dividendos_reinvertidos_acum
                dividendos_mes = acciones_totales * dividendo_pago
                
                # Reinvest dividends
                acciones_mes_reinversion = dividendos_mes / precio_proyectado
                dividendos_reinvertidos_acum += acciones_mes_reinversion
            
            # Total shares
            acciones_totales = acciones_inicial + acciones_aportes_acum + dividendos_reinvertidos_acum
            
            # Portfolio value
            valor_portafolio = acciones_totales * precio_proyectado
            
            # Monthly dividend yield (annualized)
            dividendo_mensual_generado = (acciones_totales * dpa_proyectado) / 12
            
            # Adjusted cost of living for inflation
            costo_vida_ajustado = costo_vida_mensual * ((1 + inflacion_decimal) ** (ano - 1))
            
            # Coverage percentage
            cobertura_pct = (dividendo_mensual_generado / costo_vida_ajustado * 100) if costo_vida_ajustado > 0 else 0
            
            # Append results
            results.append({
                "Año": ano,
                "Mes": mes,
                "Mes Absoluto": mes_absoluto,
                "Precio Proyectado": precio_proyectado,
                "DPA Proyectado": dpa_proyectado,
                "Inversión Acumulada": inversion_acumulada,
                "Q. Acciones (Inversión Inicial)": acciones_inicial,
                "Q. Acciones (Aportes)": acciones_aportes_acum,
                "Q. Acciones (Reinversión Dividendos)": dividendos_reinvertidos_acum,
                "Q. Acciones Totales": acciones_totales,
                "Dividendos del Mes": dividendos_mes,
                "Valor del Portafolio": valor_portafolio,
                "Dividendo Mensual Generado": dividendo_mensual_generado,
                "Costo de Vida Ajustado": costo_vida_ajustado,
                "% Cobertura": cobertura_pct,
            })
    
    return pd.DataFrame(results)


# =========================================================
# Main Page Function
# =========================================================
def page_dividend_simulator():
    """Main page for dividend portfolio simulator."""
    st.title("📊 Simulador de Dividendos")
    st.markdown("Proyecta el crecimiento de tu portafolio con reinversión de dividendos y aportes periódicos.")
    
    # Check if there's a ticker loaded in session state
    ticker_in_session = st.session_state.get("ticker", "").strip().upper()
    
    # Try to get automatic values from ticker
    auto_precio = None
    auto_dividendo = None
    auto_cagr = None
    
    if ticker_in_session:
        st.info(f"📌 Ticker cargado: **{ticker_in_session}** - Los valores predeterminados se obtienen automáticamente.")
        
        # Get current price
        try:
            price_data = get_price_data(ticker_in_session)
            auto_precio = price_data.get("last_price")
        except Exception:
            pass
        
        # Get annual dividend
        auto_dividendo = _get_annual_dividend_from_ticker(ticker_in_session)
        
        # Calculate CAGR
        auto_cagr = _calculate_dividend_cagr(ticker_in_session)
    
    # Input form
    st.markdown("### 📝 Parámetros de Simulación")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        inversion_inicial = st.number_input(
            "Inversión Inicial ($)",
            min_value=100.0,
            value=10000.0,
            step=100.0,
            format="%.2f",
            help="Capital inicial para invertir"
        )
        
        aportes_mensuales = st.number_input(
            "Aportes Mensuales ($)",
            min_value=0.0,
            value=200.0,
            step=50.0,
            format="%.2f",
            help="Cantidad a invertir mensualmente"
        )
        
        costo_vida_mensual = st.number_input(
            "Costo de Vida Mensual ($)",
            min_value=0.0,
            value=100.0,
            step=50.0,
            format="%.2f",
            help="Gastos mensuales a cubrir con dividendos"
        )
    
    with col2:
        inflacion_anual = st.number_input(
            "Inflación Anual (%)",
            min_value=0.0,
            max_value=20.0,
            value=2.0,
            step=0.1,
            format="%.2f",
            help="Tasa de inflación anual esperada"
        )
        
        rentabilidad_precio = st.number_input(
            "Rentabilidad Promedio Anual del Precio (%)",
            min_value=-10.0,
            max_value=30.0,
            value=1.0,
            step=0.5,
            format="%.2f",
            help="Crecimiento anual esperado del precio de la acción"
        )
        
        # CAGR with automatic value if available
        default_cagr = auto_cagr if auto_cagr is not None else 7.76
        cagr_dividendo = st.number_input(
            "CAGR del Dividendo (%)" + (f" - Calculado: {auto_cagr:.2f}%" if auto_cagr is not None else ""),
            min_value=0.0,
            max_value=30.0,
            value=default_cagr,
            step=0.1,
            format="%.2f",
            help="Tasa de crecimiento anual del dividendo" + (" (calculado automáticamente desde el historial)" if auto_cagr is not None else "")
        )
    
    with col3:
        tipo_distribucion = st.selectbox(
            "Tipo de Distribución de Dividendos",
            options=["Trimestral", "Mensual"],
            index=0,
            help="Frecuencia de pago de dividendos"
        )
        
        anos_simulacion = st.number_input(
            "Años de Simulación",
            min_value=1,
            max_value=50,
            value=30,
            step=1,
            help="Horizonte temporal de la simulación"
        )
        
        # Price with automatic value if available
        default_precio = auto_precio if auto_precio is not None else 29.63
        precio_actual = st.number_input(
            "Precio Actual de la Acción ($)" + (f" - Actual: ${auto_precio:.2f}" if auto_precio is not None else ""),
            min_value=0.01,
            value=default_precio,
            step=0.01,
            format="%.2f",
            help="Precio actual por acción" + (" (obtenido automáticamente)" if auto_precio is not None else "")
        )
        
        # Dividend with automatic value if available
        default_dividendo = auto_dividendo if auto_dividendo is not None else 1.76
        dividendo_anual = st.number_input(
            "Dividendo Anual por Acción ($)" + (f" - TTM: ${auto_dividendo:.2f}" if auto_dividendo is not None else ""),
            min_value=0.0,
            value=default_dividendo,
            step=0.01,
            format="%.2f",
            help="Dividendo anual por acción" + (" (últimos 12 meses)" if auto_dividendo is not None else "")
        )
    
    st.markdown("---")
    
    # Simulate button
    if st.button("🚀 Simular", type="primary", use_container_width=True):
        # Validate inputs
        if precio_actual <= 0:
            st.error("❌ El precio de la acción debe ser mayor a 0")
            return
        
        if dividendo_anual < 0:
            st.error("❌ El dividendo anual no puede ser negativo")
            return
        
        # Run simulation
        with st.spinner("Ejecutando simulación..."):
            df = _simulate_dividends(
                inversion_inicial=inversion_inicial,
                aportes_mensuales=aportes_mensuales,
                costo_vida_mensual=costo_vida_mensual,
                inflacion_anual=inflacion_anual,
                rentabilidad_precio_anual=rentabilidad_precio,
                cagr_dividendo=cagr_dividendo,
                tipo_distribucion=tipo_distribucion,
                anos_simulacion=anos_simulacion,
                precio_actual=precio_actual,
                dividendo_anual=dividendo_anual,
            )
        
        # Display summary KPIs
        st.markdown("### 📈 Resultados de la Simulación")
        
        # Calculate KPIs
        kpis = _calculate_kpis(
            df=df,
            inversion_inicial=inversion_inicial,
            aportes_mensuales=aportes_mensuales,
            inflacion_anual=inflacion_anual,
            anos_simulacion=anos_simulacion
        )
        
        # SECCIÓN PRINCIPAL: 4 KPIs grandes con formato metric
        st.markdown("#### 💰 Resumen Financiero")
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(
                "Capital Total",
                f"${int(kpis['capital_total']):,}",
                delta=f"+{kpis['crecimiento_capital']:.2f}%",
                delta_color="normal"
            )
        
        with col2:
            st.metric(
                "Aportes Totales",
                f"${int(kpis['aportes_totales']):,}"
            )
        
        with col3:
            st.metric(
                "Total Dividendos Cobrados",
                f"${int(kpis['dividendos_totales']):,}"
            )
        
        with col4:
            st.metric(
                "Año de Cobertura",
                kpis['ano_cobertura']['text']
            )
        
        # SECCIÓN SECUNDARIA: KPIs adicionales con tooltips
        
        col5, col6, col17, col18 = st.columns(4)
        
        with col5:
            st.metric(
                "Dividendo Mensual Final",
                f"${int(kpis['dividendo_mensual_final']):,}",
                help="Dividendo mensual que recibirás en el último año"
            )
        
        with col6:
            st.metric(
                "Costo de Vida Final",
                f"${int(kpis['costo_vida_final']):,}/mes",
                help="Costo de vida mensual ajustado por inflación"
            )
        
        st.divider()
        
        # Charts
        st.markdown("### 📊 Gráficos de Evolución")
        
        chart_tab1, chart_tab2, chart_tab3 = st.tabs(["Valor del Portafolio", "Acciones Acumuladas", "Cobertura de Gastos"])
        
        with chart_tab1:
            # Portfolio value evolution
            fig1 = go.Figure()
            fig1.add_trace(go.Scatter(
                x=df["Mes Absoluto"],
                y=df["Valor del Portafolio"],
                mode="lines",
                name="Valor del Portafolio",
                line=dict(color=COLOR_PRIMARY, width=2),
                fill="tozeroy",
                fillcolor=f"rgba(255, 109, 1, 0.1)"
            ))
            fig1.add_trace(go.Scatter(
                x=df["Mes Absoluto"],
                y=df["Inversión Acumulada"],
                mode="lines",
                name="Inversión Acumulada",
                line=dict(color=COLOR_TERTIARY, width=2, dash="dash")
            ))
            fig1.update_layout(
                title="Evolución del Valor del Portafolio vs Inversión",
                xaxis_title="Mes",
                yaxis_title="Valor ($)",
                plot_bgcolor=COLOR_BACKGROUND,
                paper_bgcolor=COLOR_BACKGROUND,
                font=dict(color=COLOR_TEXT),
                hovermode="x unified"
            )
            st.plotly_chart(fig1, use_container_width=True)
        
        with chart_tab2:
            # Shares accumulation
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(
                x=df["Mes Absoluto"],
                y=df["Q. Acciones (Inversión Inicial)"],
                mode="lines",
                name="Inversión Inicial",
                line=dict(color=COLOR_TERTIARY, width=2),
                stackgroup="one"
            ))
            fig2.add_trace(go.Scatter(
                x=df["Mes Absoluto"],
                y=df["Q. Acciones (Aportes)"],
                mode="lines",
                name="Aportes Mensuales",
                line=dict(color=COLOR_PRIMARY, width=2),
                stackgroup="one"
            ))
            fig2.add_trace(go.Scatter(
                x=df["Mes Absoluto"],
                y=df["Q. Acciones (Reinversión Dividendos)"],
                mode="lines",
                name="Reinversión Dividendos",
                line=dict(color=COLOR_SECONDARY, width=2),
                stackgroup="one"
            ))
            fig2.update_layout(
                title="Acumulación de Acciones por Fuente",
                xaxis_title="Mes",
                yaxis_title="Cantidad de Acciones",
                plot_bgcolor=COLOR_BACKGROUND,
                paper_bgcolor=COLOR_BACKGROUND,
                font=dict(color=COLOR_TEXT),
                hovermode="x unified"
            )
            st.plotly_chart(fig2, use_container_width=True)
        
        with chart_tab3:
            # Coverage percentage
            fig3 = go.Figure()
            fig3.add_trace(go.Scatter(
                x=df["Mes Absoluto"],
                y=df["% Cobertura"],
                mode="lines",
                name="% Cobertura",
                line=dict(color=COLOR_PRIMARY, width=2),
                fill="tozeroy",
                fillcolor=f"rgba(255, 109, 1, 0.1)"
            ))
            # Add 100% reference line
            fig3.add_hline(
                y=100,
                line_dash="dash",
                line_color=COLOR_SECONDARY,
                annotation_text="100% Cobertura",
                annotation_position="right"
            )
            fig3.update_layout(
                title="Cobertura del Costo de Vida con Dividendos",
                xaxis_title="Mes",
                yaxis_title="% Cobertura",
                plot_bgcolor=COLOR_BACKGROUND,
                paper_bgcolor=COLOR_BACKGROUND,
                font=dict(color=COLOR_TEXT),
                hovermode="x unified"
            )
            st.plotly_chart(fig3, use_container_width=True)
        
        st.markdown("---")
        
        # Data table
        st.markdown("### 📋 Tabla de Resultados Mensuales")
        
        # Display options
        display_option = st.radio(
            "Mostrar datos:",
            options=["Anualmente (Diciembre)", "Todos los meses"],
            index=0,
            horizontal=True
        )
        
        if display_option == "Anualmente (Diciembre)":
            df_display = df[df["Mes"] == 12].copy()
        else:
            df_display = df.copy()
        
        # Format DataFrame for display
        df_formatted = df_display[[
            "Año", "Mes", "Precio Proyectado", "DPA Proyectado",
            "Q. Acciones Totales", "Valor del Portafolio",
            "Dividendo Mensual Generado", "% Cobertura"
        ]].copy()
        
        # Format currency columns
        for col in ["Precio Proyectado", "DPA Proyectado", "Valor del Portafolio", "Dividendo Mensual Generado"]:
            df_formatted[col] = df_formatted[col].apply(lambda x: f"${x:,.2f}")
        
        df_formatted["Q. Acciones Totales"] = df_formatted["Q. Acciones Totales"].apply(lambda x: f"{x:,.2f}")
        df_formatted["% Cobertura"] = df_formatted["% Cobertura"].apply(lambda x: f"{x:.1f}%")
        
        st.dataframe(df_formatted, use_container_width=True, height=400)
        
        # Download option
        csv = df.to_csv(index=False)
        st.download_button(
            label="📥 Descargar resultados completos (CSV)",
            data=csv,
            file_name=f"simulacion_dividendos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True
        )
