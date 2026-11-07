# Weather-informed demand forecasting: supervisor notes

## Short explanation to present

> “The system forecasts agricultural-input demand by district and input type using historical farmer usage. It first creates an ARIMA baseline. For the 2026/2027 planning season, the system also records the Zambia Meteorological Department’s seasonal rainfall categories and retrieves monthly ECMWF SEAS5 rainfall outlooks from Open-Meteo. A provisional ZMD-based percentage is shown as a separate planning scenario; the baseline remains the quantity used for inventory allocation. SEAS5 and the shorter-range ECMWF IFS readings provide weather context, but they are not yet statistically calibrated to alter demand.”

## The workflow, step by step

1. **Historical demand is recorded or imported.** Farmer usage records contain farmer, district (through the farmer record), agricultural season, input type, and quantity in kilograms. The forecasting page accepts CSV/XLSX uploads. Event-based files may contain repeated farmer/input/season rows when each row has a unique `usage_event_id`.
2. **ARIMA creates a demand baseline.** For each district/input combination, the system sums usage by season, orders the seasonal values, requires at least four seasons, and fits ARIMA(1,1,1). For 2026/2027 it projects from the last season present in the usage history to the requested target season. Negative estimates are clamped to zero.
3. **The ZMD outlook is represented as a scenario assumption.** The system stores the configured rainfall category for each of OND, NDJ, DJF, and JFM. It maps categories to provisional percentages (−5%, −2.5%, +2.5%, +5%) and averages the four periods. In the current Kitwe and Ndola configuration, OND, NDJ, and JFM are “Normal to Below Normal” and DJF is “Below Normal”, giving −3.13% after rounding.
4. **A scenario is calculated separately.** The illustrative quantity is baseline × (1 + adjustment/100). For example, a baseline of 1,000 kg and a −3.13% assumption gives a scenario of about 968.70 kg. This percentage is a project assumption; it is not supplied by ZMD or estimated from local weather-demand history.
5. **ECMWF SEAS5 supplies additional seasonal evidence.** From the Weather page, an authorized user selects Kitwe or Ndola and clicks “Refresh SEAS5 seasonal outlook”. Open-Meteo’s Seasonal Forecast API returns monthly precipitation mean and anomaly values. The app saves each value with district, valid month, model, source, and retrieval date, preserving snapshots so later refreshes can be compared. The demand run attaches the latest cached October–March summaries to the 2026/2027 forecasts.
6. **ECMWF IFS supplies recent/near-term weather.** The other Weather-page action fetches 31 past days and 10 forecast days of hourly temperature, humidity, and rain, then aggregates them to daily summaries. The Forecasts page can show the coming-10-day rainfall total as short-term context. IFS is not the seasonal outlook and does not change the seasonal demand calculation.
7. **Inventory allocation uses the ARIMA baseline.** The baseline is retained as the forecast’s allocation quantity. The ZMD scenario and SEAS5 values are displayed for planning and explanation but are not used by the inventory optimizer.

## What to emphasize about ZMD and SEAS5

- The ZMD 2026/2027 document gives categorical rainfall outlooks by overlapping three-month periods, not exact daily rainfall values or a formula translating rainfall into kilograms of input demand.
- The current configured ZMD mapping covers **Kitwe and Ndola** only. It is based on the document’s detailed Copperbelt outlook: OND and NDJ Normal to Below Normal, DJF Below Normal, JFM Normal to Below Normal.
- The ZMD adjustment percentages are **provisional planning assumptions**, not values statistically learned from weather or demand observations. All input types currently use the same percentage because input-specific weather response is not established.
- ECMWF SEAS5 provides broad-area, monthly probabilistic/ensemble guidance out to several months. Open-Meteo documents it at roughly 36 km resolution and notes that it is not bias-corrected; its anomaly is relative to the ECMWF model climatology, not the ZMD 1991–2020 reference period. Treat it as supporting context, not a district rain-gauge measurement.
- The monthly SEAS5 outlook is not automatically converted into the ZMD category or the adjustment percentage. It is attached as separate evidence so the planner can interpret both sources.

## How to describe forecast validation and limitations

- The current system demonstrates **ARIMA baseline plus transparent weather-informed scenario/context**. It is not yet a validated weather-based demand model.
- A defensible calibrated weather effect needs multiple seasons of actual input usage and observed rainfall matched by district, crop/input type, and season. Archived seasonal forecasts from the time they were issued are especially valuable for checking whether outlook information would have been available to planners then.
- Validation should use chronological backtesting: train on earlier seasons, predict later held-out seasons, and compare the weather-informed result against the ARIMA-only baseline using MAE/RMSE or similar errors.
- One rainy season or one set of sample data cannot establish a reliable causal adjustment, especially separately for each input type. Label generated sample records as synthetic; do not present them as government or observed farmer records.
- Until backtesting supports a weather coefficient, keep the ZMD result as a separate scenario and keep inventory allocation tied to the baseline. This avoids changing procurement quantities based on an unverified assumption.

## If asked why the same −3.13% appears for both districts

Both currently configured districts have the same four ZMD categories. The code maps Normal to Below Normal to −2.5% and Below Normal to −5%; averaging the three −2.5% periods and one −5% period gives −3.125%, rounded to −3.13%. It is therefore the same because the source categories and provisional rule are the same—not because the system has learned identical district weather impacts.

## Suggested demonstration during the defence

1. Open **Forecasts** and point out the ARIMA baseline/allocation column.
2. Explain the separate ZMD scenario quantity, adjustment, and categories.
3. Open **Weather**, select Kitwe or Ndola, and refresh the **SEAS5 seasonal outlook**; explain mean rainfall, anomaly, valid month, and retrieval date.
4. Optionally refresh **ECMWF IFS weather** to show recent weather and the 10-day outlook, clarifying that it is not seasonal.
5. Explain that refreshing or displaying weather does not silently change inventory allocations; those remain tied to the ARIMA baseline.

## Technical references in this project

- `forecasting/services.py`: seasonal demand aggregation, ARIMA fitting, baseline/scenario storage, and forecast orchestration.
- `forecasting/climate.py`: the configured ZMD categories and provisional category-to-percentage rule.
- `weather/services.py`: Open-Meteo ECMWF IFS and ECMWF SEAS5 API requests, data validation, and persistence.
- `weather/models.py`: daily IFS data and timestamped monthly SEAS5 outlook snapshots.
- `inventory/services.py`: consumes the explicit allocation baseline.
- `templates/forecasting/forecast_list.html` and `templates/weather/weather_dashboard.html`: user-facing forecast evidence and weather information.
