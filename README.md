# Agricultural-supply-chain-2026

## Run it locally

Requires **Python 3.12** (numpy 1.26 / pandas 2.2 do not install on 3.13+).

```
py -3.12 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Open http://127.0.0.1:8000 and log in with the demo Ministry account **demo / demo1234**.
The included `db.sqlite3` holds the real survey farmers and FAOSTAT series (see below), their
2026/2027 forecasts and cached weather; use
"Refresh global-model weather" and "Refresh SEAS5 for all districts" on the Weather page
to pull the latest forecasts.

## Real datasets behind the demand forecast

| Data | Source | Used for |
|---|---|---|
| `forecasting/data/fisp_southern_province_2021_22.xlsx` | Iyioku, G. (2024). *Farmer Input Support Programme – Southern Province Data*. Mendeley Data, V1. doi:10.17632/fspbympxky.1 (CC BY 4.0). Survey of 340 maize farmers in Choma, Kalomo, Monze and Pemba, collected Jul–Sep 2022 about the 2021/2022 season. | Real farmers and their 2021/2022 maize seed and fertilizer use. Total fertilizer is split 50/50 into D Compound and urea, as in the standard FISP pack. |
| `forecasting/data/faostat_zambia_inputs.csv` | FAO (2025). FAOSTAT: *Fertilizers by Nutrient* (agricultural use of N and P2O5, tonnes) and *Crops and livestock products* (maize area harvested, ha), Zambia, 1961–2024 (CC BY 4.0). | 64-season national trends: N → urea, P2O5 → D Compound, maize area → maize seed. |

Load them with:

```
python manage.py import_faostat_series
python manage.py import_fisp_survey
```

Districts with at least four seasons of farmer records are forecast with ARIMA(1,1,1) on their own history.
Districts with fewer seasons, such as the survey districts, are forecast with "ARIMA(1,1,1) national trend":
ARIMA is fitted to the FAOSTAT national series, and the district's real 2021/2022 total is scaled by the predicted
national change from 2021/2022 to the target season.
