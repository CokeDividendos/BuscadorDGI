# src/services/chile_data.py
from __future__ import annotations

import pandas as pd
from pathlib import Path
from typing import Any, Dict

# Rutas base
_REPO_ROOT = Path(__file__).parent.parent.parent
_DATA_CL = _REPO_ROOT / "data" / "chile" / "financials"
_TICKERS_MAP = _REPO_ROOT / "data" / "chile_tickers_map.csv"


def _load_tickers_map() -> pd.DataFrame:
    """Load chile_tickers_map.csv. Returns empty DataFrame if not found."""
    try:
        return pd.read_csv(_TICKERS_MAP, sep=",", dtype=str).fillna("")
    except Exception:
        return pd.DataFrame(columns=["ticker", "nombre"])


def is_cl_ticker(ticker: str) -> bool:
    """Return True if ticker exists in chile_tickers_map.csv."""
    df = _load_tickers_map()
    return ticker.upper() in df["ticker"].str.upper().values


def get_cl_company_name(ticker: str) -> str:
    """Return company name from chile_tickers_map.csv, or ticker if not found."""
    df = _load_tickers_map()
    row = df[df["ticker"].str.upper() == ticker.upper()]
    if not row.empty:
        return row.iloc[0].get("nombre", ticker)
    return ticker


def get_cl_tickers_list() -> list:
    """Return list of all available CL tickers."""
    df = _load_tickers_map()
    return df["ticker"].tolist()


def _parse_csv(path: Path) -> pd.DataFrame:
    """
    Parse a financial statement CSV.
    - Separator: ;
    - First column 'Cuenta' becomes the index (account names)
    - Year columns remain as string columns
    - Returns DataFrame with account names as index, year strings as columns
      (same orientation as yfinance balance_sheet / income_stmt / cashflow)
    - Values are converted to numeric; rows that are all-NaN or all-zero dropped
    """
    if not path.exists():
        return pd.DataFrame()

    try:
        df = pd.read_csv(
            path,
            sep=";",
            index_col=0,
            encoding="utf-8-sig",  # handles BOM
            dtype=str,
        )

        # Drop rows where index is empty or looks like a section separator
        df = df[df.index.notna()]
        df.index = df.index.astype(str)
        df = df[~df.index.str.strip().str.startswith("===")]
        df = df[df.index.str.strip() != ""]

        # Strip whitespace from index and column names
        df.index = df.index.str.strip()
        df.columns = [str(c).strip() for c in df.columns]

        # Convert all values to numeric
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # Drop rows that are entirely NaN or entirely zero
        df = df[~(df.fillna(0) == 0).all(axis=1)]
        df = df.dropna(how="all")

        return df

    except Exception:
        return pd.DataFrame()


def load_cl_financial_statements(ticker: str) -> Dict[str, Any]:
    """
    Load balance sheet, income statement and cashflow from local CSVs.

    Returns the same structure as _load_financial_statements() in analysis.py:
    {"balance_sheet": df, "income_stmt": df, "cashflow": df}

    DataFrames have account names as index and year strings as columns,
    matching the orientation returned by yfinance (so _prepare_financial_df
    and all chart functions work without modification).
    """
    folder = _DATA_CL / ticker.upper()

    balance_sheet = _parse_csv(folder / "balance.csv")
    income_stmt = _parse_csv(folder / "income.csv")
    cashflow = _parse_csv(folder / "cashflow.csv")

    return {
        "balance_sheet": balance_sheet,
        "income_stmt": income_stmt,
        "cashflow": cashflow,
    }


def load_cl_dividends(ticker: str) -> pd.Series:
    """
    Load dividends from dividends.csv if it exists.
    Returns pd.Series with DatetimeIndex (compatible with yf tk.dividends).
    Returns empty Series if file not found.

    Expected CSV format (separator ;):
        Date;Dividends
        2024-05-15;50.5
        2023-05-10;45.2
    """
    path = _DATA_CL / ticker.upper() / "dividends.csv"
    if not path.exists():
        return pd.Series(dtype=float)

    try:
        df = pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype=str)
        df.columns = [c.strip() for c in df.columns]
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df["Dividends"] = pd.to_numeric(df["Dividends"], errors="coerce")
        df = df.dropna(subset=["Date", "Dividends"])
        df = df.set_index("Date").sort_index()
        series = df["Dividends"].astype(float)
        series.index.name = None
        return series
    except Exception:
        return pd.Series(dtype=float)


def get_cl_yf_ticker(ticker_cl: str) -> str:
    """
    Convert a CL ticker to its Yahoo Finance equivalent.
    Appends .SN (Bolsa de Santiago) suffix.
    Examples: ANDINA-B -> ANDINA-B.SN, FALABELLA -> FALABELLA.SN
    """
    return f"{ticker_cl.upper()}.SN"
