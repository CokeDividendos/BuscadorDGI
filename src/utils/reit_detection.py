"""
Utilidades para detección y cálculo de métricas de REITs.
NO hace llamadas a API, usa solo datos ya cargados.
"""
from typing import Dict, Any, Optional
import pandas as pd


def is_reit(info: Dict[str, Any]) -> bool:
    """
    Detecta si una empresa es un REIT usando datos ya disponibles.
    
    Criterios:
    1. Sector contiene "Real Estate"
    2. Industry contiene "REIT"
    3. Symbol en lista conocida de REITs grandes
    
    Args:
        info: Dict de yfinance ya cargado (NO hace llamadas API)
    
    Returns:
        bool: True si es REIT
    """
    if not isinstance(info, dict):
        return False
    
    # Detección por sector/industria
    sector = str(info.get("sector", "")).lower()
    industry = str(info.get("industry", "")).lower()
    
    if "real estate" in sector or "reit" in industry:
        return True
    
    # Lista de REITs conocidos (fallback)
    known_reits = {
        "O", "PLD", "AMT", "EQIX", "PSA", "DLR", "SPG", "WELL", 
        "AVB", "EQR", "VTR", "ARE", "MAA", "INVH", "ESS", "UDR"
    }
    symbol = str(info.get("symbol", "")).upper()
    
    return symbol in known_reits


def calculate_ffo(income_df: pd.DataFrame, cashflow_df: pd.DataFrame) -> Optional[pd.Series]:
    """
    Calcula FFO (Funds From Operations) desde DataFrames ya cargados.
    
    Fórmula simplificada: FFO = Net Income + Depreciation & Amortization
    
    Nota: Esta es una aproximación. La fórmula completa de FFO también resta 
    ganancias de ventas de propiedades, pero esta información no siempre está 
    disponible en los estados financieros estandarizados.
    
    Args:
        income_df: DataFrame de income statement (ya cargado)
        cashflow_df: DataFrame de cash flow (ya cargado)
    
    Returns:
        pd.Series con FFO por año, o None si faltan datos
    """
    if income_df.empty or cashflow_df.empty:
        return None
    
    try:
        # Buscar Net Income
        net_income_col = None
        for col in income_df.columns:
            if "net income" in str(col).lower():
                net_income_col = col
                break
        
        if not net_income_col:
            return None
        
        net_income = pd.to_numeric(income_df[net_income_col], errors="coerce")
        
        # Buscar Depreciation & Amortization
        depreciation_col = None
        for col in cashflow_df.columns:
            col_lower = str(col).lower()
            if "depreciation" in col_lower or "amortization" in col_lower:
                depreciation_col = col
                break
        
        if not depreciation_col:
            return None
        
        depreciation = pd.to_numeric(cashflow_df[depreciation_col], errors="coerce")
        
        # Alinear índices
        common_index = net_income.index.intersection(depreciation.index)
        if len(common_index) == 0:
            return None
        
        ffo = net_income[common_index] + depreciation[common_index].abs()
        
        return ffo.dropna()
        
    except Exception:
        return None


def calculate_affo(ffo: pd.Series, balance_df: pd.DataFrame, cashflow_df: pd.DataFrame) -> Optional[pd.Series]:
    """
    Calcula AFFO (Adjusted FFO) desde datos ya cargados.
    
    Fórmula: AFFO = FFO - CapEx de mantenimiento (aprox)
    
    Args:
        ffo: Serie de FFO calculada
        balance_df: DataFrame de balance (ya cargado)
        cashflow_df: DataFrame de cash flow (ya cargado)
    
    Returns:
        pd.Series con AFFO por año, o None si faltan datos
    """
    if ffo is None or ffo.empty or cashflow_df.empty:
        return None
    
    try:
        # Buscar CapEx
        capex_col = None
        for col in cashflow_df.columns:
            if "capital expenditure" in str(col).lower():
                capex_col = col
                break
        
        if not capex_col:
            return None
        
        # CapEx is typically negative in cash flow statements, so we use abs()
        # to convert to positive for the subtraction: AFFO = FFO - |CapEx|
        capex = pd.to_numeric(cashflow_df[capex_col], errors="coerce").abs()
        
        # Alinear índices
        common_index = ffo.index.intersection(capex.index)
        if len(common_index) == 0:
            return None
        
        # AFFO = FFO - CapEx (aproximación conservadora)
        affo = ffo[common_index] - capex[common_index]
        
        return affo.dropna()
        
    except Exception:
        return None


def get_reit_metrics(info: Dict[str, Any], income_df: pd.DataFrame, 
                     cashflow_df: pd.DataFrame, balance_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Calcula todas las métricas relevantes para REITs.
    
    Args:
        info: Dict de yfinance (ya cargado)
        income_df: Income statement (ya cargado)
        cashflow_df: Cash flow (ya cargado)
        balance_df: Balance sheet (ya cargado)
    
    Returns:
        Dict con métricas: ffo, affo, p_ffo, ffo_yield, etc.
    """
    metrics = {
        "is_reit": False,
        "ffo": None,
        "affo": None,
        "ffo_per_share": None,
        "p_ffo": None,
        "ffo_yield": None,
    }
    
    if not is_reit(info):
        return metrics
    
    metrics["is_reit"] = True
    
    # Calcular FFO
    ffo = calculate_ffo(income_df, cashflow_df)
    if ffo is not None and not ffo.empty:
        metrics["ffo"] = ffo
        
        # Calcular FFO per share
        shares_col = None
        for col in income_df.columns:
            if "shares outstanding" in str(col).lower() or "diluted average shares" in str(col).lower():
                shares_col = col
                break
        
        if shares_col:
            shares = pd.to_numeric(income_df[shares_col], errors="coerce")
            common_index = ffo.index.intersection(shares.index)
            if len(common_index) > 0:
                ffo_per_share = ffo[common_index] / shares[common_index]
                metrics["ffo_per_share"] = ffo_per_share.dropna()
                
                # Calcular P/FFO usando precio actual
                current_price = info.get("currentPrice")
                if current_price and isinstance(current_price, (int, float)) and not ffo_per_share.empty:
                    latest_ffo_per_share = ffo_per_share.iloc[-1]
                    if latest_ffo_per_share > 0:
                        metrics["p_ffo"] = current_price / latest_ffo_per_share
                        metrics["ffo_yield"] = (latest_ffo_per_share / current_price) * 100
    
    # Calcular AFFO
    if metrics["ffo"] is not None:
        affo = calculate_affo(metrics["ffo"], balance_df, cashflow_df)
        metrics["affo"] = affo
    
    return metrics
