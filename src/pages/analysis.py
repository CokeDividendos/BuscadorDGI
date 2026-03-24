def _plot_geraldine_weiss(price_daily):
    # Ensure price_daily has a DatetimeIndex
    if not pd.api.types.is_datetime64_any_dtype(price_daily.index):
        price_daily.index = pd.to_datetime(price_daily.index).dropna()
        price_daily = price_daily.sort_index()
    
    # Proceed with resampling
    monthly_data = price_daily.resample('M').mean()  # Keep rest unchanged
    #... rest of the function ...