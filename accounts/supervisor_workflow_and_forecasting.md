# FISP System: Brief Workflow and Forecasting Explanation

## What to say to my supervisor

> “The system uses registered farmers and their recorded input usage from past seasons to estimate next season’s demand for each input in each district. It groups the history by district, input type, and season, then applies an ARIMA time-series model to forecast one season ahead. The forecast is passed to an inventory allocation optimizer, which considers the available supply and input costs and distributes planned quantities to suppliers, agro-dealers, and farmers. The system can then generate supplier-to-dealer collection routes. A supplier records an issue, and the agro-dealer confirms what was actually collected; dealer stock is updated only after that confirmation. This helps planners estimate demand and coordinate distribution, while the recorded transactions show what stock is actually on hand.”

## How the workflow works

1. **Register farmers and record history.** Farmer input usage is recorded by season, input type, and quantity. Historical usage can also be imported from a CSV or spreadsheet.
2. **Forecast demand.** The system totals the historical quantities for each district and input type by season, then forecasts the next season.
3. **Allocate planned supply.** An inventory optimization step uses the forecasts, available quantities, and costs to determine district allocations and distribute them among suppliers, agro-dealers, and farmers.
4. **Plan collection routes.** Route generation creates supplier-to-agro-dealer collection legs from the latest allocation. It uses Mapbox driving routes when configured, with straight-line distance as a fallback.
5. **Record actual stock movement.** The supplier records inputs issued to a dealer. The dealer records the amount actually collected. The dealer’s available stock changes only when receipt is confirmed.

## How ARIMA works here

- **Model:** ARIMA(1, 1, 1), implemented with the `statsmodels` ARIMA time-series model.
- **Input data:** Historical farmer input usage, aggregated by district, input type, and season.
- **Prediction:** One step ahead—the next season in the system’s season sequence.
- **Minimum history:** At least four seasonal data points are required for a district/input pair; otherwise, that forecast is skipped.
- **Plain-language explanation:** ARIMA looks at how demand changed over time. It uses the recent past, accounts for a trend by looking at changes between seasons, and smooths short-term variation to estimate the next season. Negative predictions are set to zero because demand cannot be negative.

## Seasonal weather context and allocation safeguard

- The Weather page can retrieve monthly ECMWF SEAS5 precipitation means and anomalies from Open-Meteo for the 2026/2027 October-to-March season. Retrieved outlook snapshots are retained with their retrieval dates so the displayed evidence can be traced.
- The monthly anomaly is relative to ECMWF's own model climatology; it is not the ZMD 1991-2020 normal and the seasonal product is not bias-corrected. Treat it as broad-area, uncertain planning guidance.
- The ZMD category-based percentage is retained only as a clearly labelled illustrative scenario. `weather_scenario_quantity_kg` stores that scenario, while `baseline_predicted_quantity_kg` and `predicted_quantity_kg` remain equal to the ARIMA baseline.
- Inventory allocation, its supply totals, and the dashboard demand KPI use the ARIMA baseline. The ECMWF seasonal outlook and ZMD scenario do not currently alter what inventory allocates.
- A trustworthy learned weather effect would require multiple years of matched district/input demand, observed rainfall, and archived forecasts, followed by chronological backtesting against the demand-only ARIMA baseline.

The numbers are estimates based on the available historical data, not guarantees. Forecast quality depends on the amount and accuracy of the recorded seasonal history.

## If asked what “(1, 1, 1)” means

- **1 (autoregressive):** Uses the recent past value as part of the estimate.
- **1 (differencing):** Looks at changes between seasons to account for trend.
- **1 (moving average):** Uses recent forecast errors to smooth the estimate.

## Very short version

> “ARIMA(1,1,1) forecasts next-season input demand from seasonal usage history, separately for each district and input. The system then optimizes allocations, plans supplier-to-dealer collection routes, and updates dealer stock only after the dealer confirms receipt.”

