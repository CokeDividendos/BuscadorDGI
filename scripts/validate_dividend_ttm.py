"""
validate_dividend_ttm.py
------------------------
Validates the TTM dividend calculation for a given ticker, comparing the
old method (window anchored to last payment date) with the new method
(window anchored to today UTC).

Usage:
    python scripts/validate_dividend_ttm.py [TICKER]

Default ticker: NKE
"""

from __future__ import annotations

import sys
import pandas as pd
import yfinance as yf


def _old_method(divs: pd.Series) -> float | None:
    """Original calculation: window anchored to last payment date."""
    if divs is None or len(divs) == 0:
        return None
    last_date = divs.index.max()
    start_date = last_date - pd.DateOffset(days=365)
    div_ttm = divs[divs.index > start_date]
    return float(div_ttm.sum()) if len(div_ttm) >= 1 else None


def _new_method(divs: pd.Series) -> float | None:
    """Fixed calculation: window anchored to today (UTC)."""
    if divs is None or len(divs) == 0:
        return None
    s = divs.copy()
    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.to_datetime(s.index, errors="coerce")
        s = s[s.index.notna()]
    if getattr(s.index, "tz", None) is not None:
        s.index = s.index.tz_convert("UTC").tz_localize(None)
    end_date = pd.Timestamp.now("UTC").tz_localize(None)
    start_date = end_date - pd.DateOffset(days=365)
    ttm = s[(s.index > start_date) & (s.index <= end_date)]
    return float(ttm.sum()) if len(ttm) >= 1 else None


def main() -> None:
    ticker = sys.argv[1] if len(sys.argv) > 1 else "NKE"
    print(f"\n=== TTM Dividend Validation: {ticker} ===\n")

    tk = yf.Ticker(ticker)
    divs = tk.dividends

    if divs is None or len(divs) == 0:
        print("No dividend history found.")
        return

    # Normalise index for display
    s = divs.copy()
    if getattr(s.index, "tz", None) is not None:
        s.index = s.index.tz_convert("UTC").tz_localize(None)

    end_date = pd.Timestamp.now("UTC").tz_localize(None)
    start_today = end_date - pd.DateOffset(days=365)

    last_date = s.index.max()
    start_last = last_date - pd.DateOffset(days=365)

    payments_new = s[(s.index > start_today) & (s.index <= end_date)]
    payments_old = s[s.index > start_last]

    print(f"Today (UTC):                {end_date.date()}")
    print(f"Last payment date:          {last_date.date()}")
    print()
    print(f"--- New method (window: today - 365d) ---")
    print(f"  Start date:               {start_today.date()}")
    print(f"  Payments in window:       {len(payments_new)}")
    print(f"  TTM sum (new):            ${_new_method(divs):.4f}")
    print()
    print(f"--- Old method (window: last_payment - 365d) ---")
    print(f"  Start date:               {start_last.date()}")
    print(f"  Payments in window:       {len(payments_old)}")
    print(f"  TTM sum (old):            ${_old_method(divs):.4f}")
    print()

    # Show what get_dividend_kpis returns after the fix
    try:
        import importlib
        sys.path.insert(0, ".")
        fd = importlib.import_module("src.services.finance_data")
        kpis = fd.get_dividend_kpis(ticker)
        print(f"--- get_dividend_kpis({ticker}) ---")
        print(f"  annual_div:  {kpis.get('annual_div')}")
        print(f"  div_yield:   {kpis.get('div_yield')}")
        print(f"  payout:      {kpis.get('payout')}")
    except Exception as exc:
        print(f"(Could not call get_dividend_kpis: {exc})")

    print()


if __name__ == "__main__":
    main()
