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

        # Drop columns with empty names or auto-generated "Unnamed: N" headers
        # (produced by trailing semicolons in CSV files)
        df = df[[c for c in df.columns if c and not c.startswith("Unnamed:")]]

        # Normalize comma decimals (e.g. "183,53" → "183.53") before numeric conversion
        for col in df.columns:
            df[col] = df[col].astype(str).str.replace(",", ".", regex=False)
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
    Load dividends for a CL ticker.  Supports two file formats:

    1. ``dividend.csv`` (pivot format, preferred):
       Separator ``;``, first column = dividend type, remaining columns = years.
       The row whose index contains "total" (case-insensitive) is used.
       Example::

           ;2019;2020;2021
           Provisorio;47;53,46;60,5
           Total Dividend;94,3;110,66;117,7

    2. ``dividends.csv`` (series format, legacy fallback):
       Separator ``;``, columns ``Date`` and ``Dividends``.
       Example::

           Date;Dividends
           2024-05-15;50.5

    Decimal commas are normalised (``","`` → ``"."``) before numeric conversion.
    Returns a ``pd.Series`` with ``DatetimeIndex`` compatible with yf dividends.
    Returns empty Series if no file is found or on error.
    """
    ticker_upper = ticker.upper()
    path_pivot = _DATA_CL / ticker_upper / "dividend.csv"
    path_series = _DATA_CL / ticker_upper / "dividends.csv"

    if path_pivot.exists():
        try:
            df = pd.read_csv(path_pivot, sep=";", index_col=0, encoding="utf-8-sig", dtype=str)
            df.index = df.index.astype(str).str.strip()
            df.columns = [c.strip() for c in df.columns]

            # Find "Total Dividend" row (case-insensitive match on "total")
            total_row = next(
                (idx for idx in df.index if "total" in idx.lower()),
                None,
            )
            if total_row is None:
                return pd.Series(dtype=float)

            row = df.loc[total_row].copy()
            # Normalize comma decimals
            row = row.astype(str).str.replace(",", ".", regex=False)
            row = pd.to_numeric(row, errors="coerce").dropna()

            # Build DatetimeIndex: one entry per year at Dec 31
            dates = pd.to_datetime(
                [f"{yr}-12-31" for yr in row.index], errors="coerce"
            )
            mask = dates.notna()
            series = pd.Series(
                row.values[mask], index=dates[mask], dtype=float
            )
            series = series.sort_index()
            series.index.name = None
            # Only include data from 2019 onwards
            series = series[series.index >= pd.Timestamp("2019-01-01")]
            return series
        except Exception:
            return pd.Series(dtype=float)

    if path_series.exists():
        try:
            df = pd.read_csv(path_series, sep=";", encoding="utf-8-sig", dtype=str)
            df.columns = [c.strip() for c in df.columns]
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
            # Normalize comma decimals in the Dividends column
            df["Dividends"] = df["Dividends"].astype(str).str.replace(",", ".", regex=False)
            df["Dividends"] = pd.to_numeric(df["Dividends"], errors="coerce")
            df = df.dropna(subset=["Date", "Dividends"])
            df = df.set_index("Date").sort_index()
            series = df["Dividends"].astype(float)
            series.index.name = None
            # Only include data from 2019 onwards
            series = series[series.index >= pd.Timestamp("2019-01-01")]
            return series
        except Exception:
            return pd.Series(dtype=float)

    return pd.Series(dtype=float)


def get_cl_yf_ticker(ticker_cl: str) -> str:
    """
    Convert a CL ticker to its Yahoo Finance equivalent.
    Appends .SN (Bolsa de Santiago) suffix.
    Examples: ANDINA-B -> ANDINA-B.SN, FALABELLA -> FALABELLA.SN
    """
    return f"{ticker_cl.upper()}.SN"
