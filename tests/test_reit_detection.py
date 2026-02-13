"""
Tests para detección de REITs y cálculo de métricas FFO/AFFO.
"""
import pytest
import pandas as pd
from src.utils.reit_detection import is_reit, calculate_ffo, calculate_affo, get_reit_metrics


def test_is_reit_by_sector():
    """Detecta REITs por sector Real Estate"""
    info = {"sector": "Real Estate", "industry": "REIT - Retail"}
    assert is_reit(info) is True


def test_is_reit_by_industry():
    """Detecta REITs por industria que contiene REIT"""
    info = {"sector": "Other", "industry": "REIT - Diversified"}
    assert is_reit(info) is True


def test_is_reit_by_known_symbol():
    """Detecta REITs conocidos por símbolo"""
    info = {"symbol": "O", "sector": "Other", "industry": "Other"}
    assert is_reit(info) is True


def test_not_reit_tech_company():
    """No detecta empresas tecnológicas como REITs"""
    info = {"sector": "Technology", "industry": "Software - Application"}
    assert is_reit(info) is False


def test_not_reit_empty_info():
    """Maneja dict vacío sin errores"""
    assert is_reit({}) is False
    assert is_reit(None) is False


def test_calculate_ffo_basic():
    """Calcula FFO correctamente con datos válidos"""
    income_df = pd.DataFrame({
        "Net Income": [100, 120, 140],
        "Year": [2021, 2022, 2023]
    }).set_index("Year")
    
    cashflow_df = pd.DataFrame({
        "Depreciation & Amortization": [30, 35, 40],
        "Year": [2021, 2022, 2023]
    }).set_index("Year")
    
    ffo = calculate_ffo(income_df, cashflow_df)
    
    assert ffo is not None
    assert len(ffo) == 3
    assert ffo[2021] == 130  # 100 + 30
    assert ffo[2023] == 180  # 140 + 40


def test_calculate_ffo_empty_dataframes():
    """Devuelve None con DataFrames vacíos"""
    assert calculate_ffo(pd.DataFrame(), pd.DataFrame()) is None


def test_calculate_ffo_missing_columns():
    """Devuelve None si faltan columnas necesarias"""
    income_df = pd.DataFrame({"Random": [1, 2, 3]})
    cashflow_df = pd.DataFrame({"Other": [4, 5, 6]})
    
    assert calculate_ffo(income_df, cashflow_df) is None


def test_calculate_affo_basic():
    """Calcula AFFO correctamente"""
    ffo = pd.Series([130, 155, 180], index=[2021, 2022, 2023])
    
    balance_df = pd.DataFrame()  # No usado en implementación actual
    
    cashflow_df = pd.DataFrame({
        "Capital Expenditures": [-20, -25, -30],
        "Year": [2021, 2022, 2023]
    }).set_index("Year")
    
    affo = calculate_affo(ffo, balance_df, cashflow_df)
    
    assert affo is not None
    assert len(affo) == 3
    assert affo[2021] == 110  # 130 - 20
    assert affo[2023] == 150  # 180 - 30


def test_get_reit_metrics_full():
    """Calcula todas las métricas para un REIT válido"""
    info = {
        "sector": "Real Estate",
        "industry": "REIT - Retail",
        "symbol": "O",
        "currentPrice": 60.0
    }
    
    income_df = pd.DataFrame({
        "Net Income": [1000000000, 1100000000],
        "Diluted Average Shares Outstanding": [500000000, 520000000],
        "Year": [2022, 2023]
    }).set_index("Year")
    
    cashflow_df = pd.DataFrame({
        "Depreciation & Amortization": [400000000, 420000000],
        "Capital Expenditures": [-100000000, -110000000],
        "Year": [2022, 2023]
    }).set_index("Year")
    
    balance_df = pd.DataFrame()
    
    metrics = get_reit_metrics(info, income_df, cashflow_df, balance_df)
    
    assert metrics["is_reit"] is True
    assert metrics["ffo"] is not None
    assert metrics["ffo_per_share"] is not None
    assert metrics["p_ffo"] is not None
    assert metrics["ffo_yield"] is not None
    assert metrics["p_ffo"] > 0
    assert 0 < metrics["ffo_yield"] < 100


def test_get_reit_metrics_non_reit():
    """Devuelve métricas vacías para empresas no-REIT"""
    info = {"sector": "Technology", "industry": "Software"}
    
    metrics = get_reit_metrics(info, pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    
    assert metrics["is_reit"] is False
    assert metrics["ffo"] is None
    assert metrics["affo"] is None
