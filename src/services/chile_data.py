# src/services/chile_data.py
"""
Capa orquestadora de datos para Buscador CL.

Coordina la carga de archivos, normalización de EEFF, cálculo de métricas
y generación de gráficos para empresas chilenas.

Arquitectura interna:
  chile_data (orquestador)
    ├── chile_profiles    → perfiles por ticker
    ├── chile_normalizer  → mapeo a cuentas canónicas en español
    ├── chile_metrics     → métricas por profile_type
    └── chile_charts      → gráficos por profile_type
"""
from __future__ import annotations

import pandas as pd
from pathlib import Path
from typing import Any, Dict, Optional

from src.services.cache_store import cache_get, cache_set

# TTL para el bundle normalizado de datos chilenos (7 días).
# Los datos provienen de archivos CSV estáticos que rara vez cambian.
_CL_BUNDLE_CACHE_TTL = 60 * 60 * 24 * 7  # 7 días

# Rutas base
_REPO_ROOT = Path(__file__).parent.parent.parent
_DATA_CL = _REPO_ROOT / "data" / "chile" / "financials"
_TICKERS_MAP = _REPO_ROOT / "data" / "chile_tickers_map.csv"


# ---------------------------------------------------------------------------
# Helpers de serialización para caché
# ---------------------------------------------------------------------------

def _df_to_cache(df: pd.DataFrame) -> Optional[dict]:
    """Serializa un DataFrame a dict para almacenar en caché."""
    if df is None or df.empty:
        return None
    try:
        return df.to_dict(orient="tight")
    except Exception:
        return None


def _cache_to_df(data: Optional[dict]) -> pd.DataFrame:
    """Reconstruye un DataFrame desde datos de caché."""
    if not data:
        return pd.DataFrame()
    try:
        return pd.DataFrame.from_dict(data, orient="tight")
    except Exception:
        return pd.DataFrame()


def _series_to_cache(s: Any) -> Optional[dict]:
    """Serializa una pandas Series a dict para almacenar en caché."""
    if s is None:
        return None
    try:
        return dict(s)
    except Exception:
        return None


def _cache_to_series(data: Optional[dict]) -> pd.Series:
    """Reconstruye una pandas Series desde datos de caché."""
    if not data:
        return pd.Series(dtype=float)
    try:
        return pd.Series(data)
    except Exception:
        return pd.Series(dtype=float)


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


def _parse_eeff_chile_csv(path: Path) -> dict:
    """
    Parse an EEFF_Chile_<TICKER>.csv file.

    Expected format::

        Seccion;Cuenta;2019;2020;2021;...
        METADATA;acciones_promedio;946570604;...
        BALANCE;efectivo_y_equivalentes;157567986;...
        EERR;ingresos;1779025115;...
        EFE;flujo_operacional;255148474;...

    - Separator: ``;``
    - First column ``Seccion`` (or ``Sección``): one of METADATA, BALANCE, EERR, EFE
    - Second column ``Cuenta``: canonical Spanish account name
    - Remaining columns: year values

    Returns a dict with keys ``"METADATA"``, ``"BALANCE"``, ``"EERR"``, ``"EFE"``,
    each containing a DataFrame with canonical account names as index and year strings
    as columns.  Returns DataFrames of empty shape for any missing section.
    """
    empty: dict = {
        "METADATA": pd.DataFrame(),
        "BALANCE": pd.DataFrame(),
        "EERR": pd.DataFrame(),
        "EFE": pd.DataFrame(),
    }

    if not path.exists():
        return empty

    try:
        df = pd.read_csv(
            path,
            sep=";",
            encoding="utf-8-sig",
            dtype=str,
        )

        # Normalize column names
        df.columns = [str(c).strip() for c in df.columns]

        # Drop auto-generated "Unnamed: N" trailing columns
        df = df[[c for c in df.columns if not c.startswith("Unnamed:")]]

        # Find the section column (Seccion or Sección)
        seccion_col = None
        for candidate in ("Seccion", "Sección", "seccion", "sección"):
            if candidate in df.columns:
                seccion_col = candidate
                break

        if seccion_col is None or "Cuenta" not in df.columns:
            return empty

        df[seccion_col] = df[seccion_col].astype(str).str.strip().str.upper()
        df["Cuenta"] = df["Cuenta"].astype(str).str.strip()

        # Drop separator / empty rows
        df = df[~df["Cuenta"].str.startswith("===", na=False)]
        df = df[df["Cuenta"].notna()]
        df = df[df["Cuenta"] != ""]
        df = df[df["Cuenta"] != "nan"]

        year_cols = [c for c in df.columns if c not in (seccion_col, "Cuenta")]

        result: dict = {}
        for section in ("METADATA", "BALANCE", "EERR", "EFE"):
            subset = df[df[seccion_col] == section][["Cuenta"] + year_cols].copy()
            if subset.empty:
                result[section] = pd.DataFrame()
                continue

            subset = subset.set_index("Cuenta")

            # Normalize comma decimals before numeric conversion
            for col in subset.columns:
                subset[col] = subset[col].astype(str).str.replace(",", ".", regex=False)
                subset[col] = pd.to_numeric(subset[col], errors="coerce")

            # Drop rows that are entirely NaN
            subset = subset.dropna(how="all")

            result[section] = subset

        return result

    except Exception:
        return empty


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


def _parse_combined_csv(path: Path) -> Dict[str, pd.DataFrame]:
    """
    Parse a combined financial statements CSV.

    Expected format::

        statement_type;Cuenta;2019;2020;2021;...
        balance;Cash And Cash Equivalents;157567986;...
        income;Total Revenue;1779025115;...
        cashflow;Operating Cash Flow;255148474;...

    - Separator: ``;``
    - First column ``statement_type``: one of ``balance``, ``income``, ``cashflow``
    - Second column ``Cuenta``: account name (becomes DataFrame index)
    - Remaining columns: year values

    Returns a dict with keys ``"balance_sheet"``, ``"income_stmt"``, ``"cashflow"``,
    each containing a DataFrame with account names as index and year strings as columns.
    Returns DataFrames of empty shape for any missing statement type.
    """
    empty: Dict[str, pd.DataFrame] = {
        "balance_sheet": pd.DataFrame(),
        "income_stmt": pd.DataFrame(),
        "cashflow": pd.DataFrame(),
    }

    if not path.exists():
        return empty

    try:
        df = pd.read_csv(
            path,
            sep=";",
            encoding="utf-8-sig",
            dtype=str,
        )

        # Normalise column names
        df.columns = [str(c).strip() for c in df.columns]

        # Drop auto-generated "Unnamed: N" trailing columns
        df = df[[c for c in df.columns if not c.startswith("Unnamed:")]]

        if "statement_type" not in df.columns or "Cuenta" not in df.columns:
            return empty

        df["statement_type"] = df["statement_type"].astype(str).str.strip()
        df["Cuenta"] = df["Cuenta"].astype(str).str.strip()

        # Drop separator / empty rows
        df = df[~df["Cuenta"].str.startswith("===", na=False)]
        df = df[df["Cuenta"] != ""]
        df = df[df["Cuenta"] != "nan"]

        year_cols = [c for c in df.columns if c not in ("statement_type", "Cuenta")]

        result: Dict[str, pd.DataFrame] = {}
        for stmt_key, stmt_label in (
            ("balance_sheet", "balance"),
            ("income_stmt", "income"),
            ("cashflow", "cashflow"),
        ):
            subset = df[df["statement_type"] == stmt_label][["Cuenta"] + year_cols].copy()
            subset = subset.set_index("Cuenta")

            # Normalize comma decimals before numeric conversion
            for col in subset.columns:
                subset[col] = subset[col].astype(str).str.replace(",", ".", regex=False)
                subset[col] = pd.to_numeric(subset[col], errors="coerce")

            # Drop rows that are entirely NaN or entirely zero
            subset = subset[~(subset.fillna(0) == 0).all(axis=1)]
            subset = subset.dropna(how="all")

            result[stmt_key] = subset

        return result

    except Exception:
        return empty


def load_cl_financial_statements(ticker: str) -> Dict[str, Any]:
    """
    Load balance sheet, income statement and cashflow for a CL ticker.

    Looks first for the new unified CSV at::

        data/chile/financials/<TICKER>/EEFF_Chile_<TICKER>.csv

    with the format::

        Seccion;Cuenta;2019;2020;...
        BALANCE;efectivo_y_equivalentes;...
        EERR;ingresos;...
        EFE;flujo_operacional;...

    Falls back to a legacy single combined CSV at::

        data/chile/financials/<TICKER>.csv

    with the format::

        statement_type;Cuenta;2019;2020;...
        balance;Cash And Cash Equivalents;...

    Falls back to the legacy three-file layout inside a per-ticker folder::

        data/chile/financials/<TICKER>/balance.csv
        data/chile/financials/<TICKER>/income.csv
        data/chile/financials/<TICKER>/cashflow.csv

    Returns the same structure as _load_financial_statements() in analysis.py:
    {"balance_sheet": df, "income_stmt": df, "cashflow": df}

    DataFrames have account names as index and year strings as columns.
    """
    ticker_upper = ticker.upper()

    # ── New EEFF_Chile_<TICKER>.csv format ────────────────────────────────
    eeff_path = _DATA_CL / ticker_upper / f"EEFF_Chile_{ticker_upper}.csv"
    if eeff_path.exists():
        sections = _parse_eeff_chile_csv(eeff_path)
        return {
            "balance_sheet": sections.get("BALANCE", pd.DataFrame()),
            "income_stmt": sections.get("EERR", pd.DataFrame()),
            "cashflow": sections.get("EFE", pd.DataFrame()),
            "_eeff_sections": sections,  # keep full sections for normalizer
        }

    # ── Legacy single-file combined format ───────────────────────────────
    combined_path = _DATA_CL / f"{ticker_upper}.csv"
    if combined_path.exists():
        return _parse_combined_csv(combined_path)

    # ── Legacy three-file format (fallback) ─────────────────────────────
    folder = _DATA_CL / ticker_upper
    return {
        "balance_sheet": _parse_csv(folder / "balance.csv"),
        "income_stmt": _parse_csv(folder / "income.csv"),
        "cashflow": _parse_csv(folder / "cashflow.csv"),
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


# ---------------------------------------------------------------------------
# Capa de orquestación: normalización + métricas + gráficos
# ---------------------------------------------------------------------------


def load_chile_financials_bundle(ticker: str) -> dict:
    """
    Carga los EEFF crudos de un ticker chileno y los normaliza al
    esquema canónico en español.

    Orquesta chile_profiles, chile_normalizer y chile_schema.

    Cuando existe el formato EEFF_Chile_<TICKER>.csv, usa
    normalize_from_sections() que reindexará directamente a las cuentas
    canónicas (sin mapa de cuentas). En formatos legacy, aplica el flujo
    antiguo con chile_account_map.csv.

    Los resultados se almacenan en caché (Redis/SQLite) por ``_CL_BUNDLE_CACHE_TTL``
    segundos para evitar re-parseo y re-normalización en cada carga de página.

    Args:
        ticker: Código de la empresa (e.g. 'ANDINA-B').

    Returns:
        dict con:
          - 'balance_raw': DataFrame crudo
          - 'income_raw': DataFrame crudo
          - 'cashflow_raw': DataFrame crudo
          - 'balance_norm': DataFrame normalizado (cuentas canónicas)
          - 'income_norm': DataFrame normalizado
          - 'cashflow_norm': DataFrame normalizado
          - 'derived': dict de cuentas derivadas (valores como pandas Series)
          - 'profile': dict del perfil de la empresa
    """
    ticker_upper = ticker.upper()
    cache_key = f"cl:bundle:{ticker_upper}"

    # ── Intentar recuperar desde caché ───────────────────────────────────
    cached = cache_get(cache_key)
    if cached:
        try:
            return {
                "balance_raw": _cache_to_df(cached.get("balance_raw")),
                "income_raw": _cache_to_df(cached.get("income_raw")),
                "cashflow_raw": _cache_to_df(cached.get("cashflow_raw")),
                "balance_norm": _cache_to_df(cached.get("balance_norm")),
                "income_norm": _cache_to_df(cached.get("income_norm")),
                "cashflow_norm": _cache_to_df(cached.get("cashflow_norm")),
                "derived": {
                    k: _cache_to_series(v)
                    for k, v in (cached.get("derived") or {}).items()
                },
                "profile": cached.get("profile", {}),
            }
        except Exception:
            pass  # Si la reconstrucción falla, continuar y recalcular

    from src.services.chile_profiles import get_company_profile_cl
    from src.services.chile_normalizer import (
        normalize_balance_cl,
        normalize_income_cl,
        normalize_cashflow_cl,
        normalize_from_sections,
        derive_missing_accounts_cl,
        load_account_map_cl,
    )

    profile = get_company_profile_cl(ticker)
    profile_type = profile.get("profile_type", "normal")

    # Cargar datos (raw puede incluir _eeff_sections si viene del nuevo formato)
    raw = load_cl_financial_statements(ticker)
    balance_raw = raw.get("balance_sheet", pd.DataFrame())
    income_raw = raw.get("income_stmt", pd.DataFrame())
    cashflow_raw = raw.get("cashflow", pd.DataFrame())

    # Si tenemos secciones del nuevo EEFF_Chile format, usar normalizer directo
    eeff_sections = raw.get("_eeff_sections")
    if eeff_sections is not None:
        balance_norm, income_norm, cashflow_norm = normalize_from_sections(eeff_sections)
    else:
        # Flujo legacy: mapeo desde nombres crudos a canónicos con account_map
        account_map = load_account_map_cl()
        balance_norm = normalize_balance_cl(balance_raw, profile_type, account_map)
        income_norm = normalize_income_cl(income_raw, profile_type, account_map)
        cashflow_norm = normalize_cashflow_cl(cashflow_raw, profile_type, account_map)

    # Derivar cuentas faltantes
    derived = derive_missing_accounts_cl(balance_norm, income_norm, cashflow_norm, profile_type)

    bundle = {
        "balance_raw": balance_raw,
        "income_raw": income_raw,
        "cashflow_raw": cashflow_raw,
        "balance_norm": balance_norm,
        "income_norm": income_norm,
        "cashflow_norm": cashflow_norm,
        "derived": derived,
        "profile": profile,
    }

    # ── Guardar en caché ──────────────────────────────────────────────────
    try:
        cache_data = {
            "balance_raw": _df_to_cache(balance_raw),
            "income_raw": _df_to_cache(income_raw),
            "cashflow_raw": _df_to_cache(cashflow_raw),
            "balance_norm": _df_to_cache(balance_norm),
            "income_norm": _df_to_cache(income_norm),
            "cashflow_norm": _df_to_cache(cashflow_norm),
            "derived": {k: _series_to_cache(v) for k, v in derived.items()},
            "profile": profile,
        }
        cache_set(cache_key, cache_data, ttl_seconds=_CL_BUNDLE_CACHE_TTL)
    except Exception:
        pass  # El fallo al cachear no debe interrumpir la respuesta al usuario

    return bundle


def get_normalized_financials_cl(ticker: str) -> dict:
    """
    Retorna los EEFF normalizados (cuentas canónicas en español) de un ticker chileno.

    Args:
        ticker: Código de la empresa.

    Returns:
        dict con 'balance', 'income', 'cashflow', 'derived', 'profile'.
    """
    bundle = load_chile_financials_bundle(ticker)
    return {
        "balance": bundle["balance_norm"],
        "income": bundle["income_norm"],
        "cashflow": bundle["cashflow_norm"],
        "derived": bundle["derived"],
        "profile": bundle["profile"],
    }


def get_metrics_cl(ticker: str, market_data: Optional[dict] = None) -> dict:
    """
    Calcula y retorna las métricas financieras de un ticker chileno.

    Usa la lógica diferenciada por profile_type.

    Args:
        ticker: Código de la empresa.
        market_data: Dict con precio, market_cap, shares_outstanding, etc.

    Returns:
        Dict con métricas calculadas según el perfil de la empresa.
    """
    from src.services.chile_metrics import compute_metrics_cl

    bundle = load_chile_financials_bundle(ticker)
    profile_type = bundle["profile"].get("profile_type", "normal")

    return compute_metrics_cl(
        balance_df=bundle["balance_norm"],
        income_df=bundle["income_norm"],
        cashflow_df=bundle["cashflow_norm"],
        derived=bundle["derived"],
        profile_type=profile_type,
        market_data=market_data,
    )


def get_chart_data_cl(ticker: str, market_data: Optional[dict] = None) -> dict:
    """
    Genera y retorna los gráficos específicos para un ticker chileno.

    Selecciona los gráficos adecuados según el profile_type.

    Args:
        ticker: Código de la empresa.
        market_data: Dict con datos de mercado para enriquecer métricas.

    Returns:
        Dict donde la clave es el nombre del gráfico y el valor es la figura Plotly.
    """
    from src.services.chile_charts import get_charts_for_profile_cl
    from src.services.chile_metrics import compute_metrics_cl

    bundle = load_chile_financials_bundle(ticker)
    profile = bundle["profile"]
    profile_type = profile.get("profile_type", "normal")
    moneda = profile.get("moneda_reporte", "CLP")

    metrics = compute_metrics_cl(
        balance_df=bundle["balance_norm"],
        income_df=bundle["income_norm"],
        cashflow_df=bundle["cashflow_norm"],
        derived=bundle["derived"],
        profile_type=profile_type,
        market_data=market_data,
    )

    return get_charts_for_profile_cl(ticker, metrics, profile_type, moneda)
