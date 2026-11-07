# Supervisor Demonstration: Register 340 Farmers and Generate Forecasts

This guide demonstrates the complete process from a clean database to the 2021/2022 Southern Province farmer registrations and their target-season forecasts.

No application source code needs to be changed.

## 1. What the demonstration creates

The source workbook contains 340 farmer records across four districts:

- Choma
- Kalomo
- Monze
- Pemba

Each farmer gets one input-use record for maize seed and two records for fertilizer, because total fertilizer is split equally into D Compound and urea:

$$340 \times 3 = 1,020$$

input-use records. The totals should therefore be:

- Farmers: 340
- Districts: 4
- 2021/2022 maize seed records: 340
- 2021/2022 D Compound records: 340
- 2021/2022 urea records: 340
- Total input-use records: 1,020

## 2. Recommended safe setup

Use a demonstration copy of the database. Do not reset the working database immediately before a presentation unless you can restore it afterwards.

From Windows PowerShell in the project directory:

```powershell
Copy-Item db.sqlite3 db.supervisor-demo-backup.sqlite3
```

Then activate the Python environment:

```powershell
.\venv\Scripts\Activate.ps1
```

If Django has no migration applied, initialize the database structure:

```powershell
python manage.py migrate
```

## 3. Start from an empty demonstration dataset

Run the following only when the supervisor demonstration database is expected to contain no previously loaded survey or forecast records:

```powershell
python manage.py flush --no-input
python manage.py migrate
```

`flush` removes data from the database but retains the migration structure.

## 4. Import the 64-season national FAOSTAT series

```powershell
python manage.py import_faostat_series
```

Expected verification: each supported national input series contains 64 seasons:

```powershell
python manage.py shell -c "from forecasting.models import NationalInputSeries; print(list(NationalInputSeries.objects.values('input_type').annotate(count=models.Count('id')).values_list('input_type', 'count')));"
```

If Django shell reports that `models` is not defined in that one-line command, use this clearer command:

```powershell
python manage.py shell -c "from django.db.models import Count; from forecasting.models import NationalInputSeries; print(list(NationalInputSeries.objects.values('input_type').annotate(count=Count('id')).values_list('input_type', 'count')))"
```

## 5. Register the 340 farmers

Import the real Southern Province workbook:

```powershell
python manage.py import_fisp_survey
```

The survey importer performs the following operations:

1. Reads `Sheet1` from `forecasting/data/fisp_southern_province_2021_22.xlsx`.
2. Matches each respondent number with district codes 1 to 4.
3. Creates or updates a farmer using the key `FISP-SP-0001`, `FISP-SP-0002`, and so on.
4. Saves the farmer's farm size and maize primary crop.
5. Creates the 2021/2022 maize seed record and two fertilizer records.
6. Splits the recorded fertilizer total equally between D Compound and urea.

The relevant registration code is:

```python
national_id = f'FISP-SP-{number:04d}'
farmer, _ = Farmer.objects.update_or_create(
    national_id=national_id,
    defaults={
        'first_name': 'Survey respondent',
        'last_name': f'{number:04d}',
        'district': district,
        'farm_size_hectares': Decimal(str(values[columns['total_ha']])),
        'primary_crop': 'maize',
    },
)
```

The three usage records are created with:

```python
fertilizer = Decimal(str(values[columns['fertilizer_kg']]))
quantities = {'seed_maize': Decimal(str(values[columns['seed_kg']]))}
quantities.update({
    input_type: fertilizer * share for input_type, share in FERTILIZER_SPLIT.items()
})
```

The fertilizer split is defined as:

```python
FERTILIZER_SPLIT = {'fertilizer_d': Decimal('0.5'),
                   'fertilizer_urea': Decimal('0.5')}
```

## 6. Verify the 340 registered farmers

Run:

```powershell
python manage.py shell
```

At the Django shell prompt enter:

```python
from farmers.models import Farmer, FarmerInputUsage

print("Survey farmers:", Farmer.objects.filter(national_id__startswith='FISP-SP-').count())
print("Input-use records:", FarmerInputUsage.objects.filter(farmer__national_id__startswith='FISP-SP-', season='2021/2022').count())

for district in ('Choma', 'Kalomo', 'Monze', 'Pemba'):
    count = Farmer.objects.filter(national_id__startswith='FISP-SP-', district=district).count()
    print(district, count)
```

Expected district result:

```text
Choma   86
Kalomo  85
Monze   85
Pemba   84
```

Check the input type counts:

```python
from django.db.models import Count
print(list(FarmerInputUsage.objects.filter(
    farmer__national_id__startswith='FISP-SP-',
    season='2021/2022'
).values('input_type').annotate(count=Count('id')).values_list('input_type', 'count')))
```

Each of `fertilizer_d`, `fertilizer_urea`, and `seed_maize` should have 340 records.

Exit the shell with `exit()`.

## 7. Generate forecasts from scratch

Each survey district contains one season, so the system enters its national-trend forecasting branch. A district's real 2021/2022 aggregate is scaled by the ARIMA-predicted national change from 2021/2022 to the target season.

The formula is:

$$
\text{Forecast}_{district,target}
=
\text{District real}_{2021/2022}
\times
\frac{\text{National ARIMA prediction}_{target}}
{\text{National FAOSTAT value}_{2021/2022}}
$$

### Baseline demonstration without weather files

Use `forecast_district_input()` directly so the forecast generation demonstration is not blocked by optional weather outlook availability:

```powershell
python manage.py shell
```

Then run:

```python
from forecasting.services import forecast_district_input

forecast_season = '2026/2027'
districts = ('Choma', 'Kalomo', 'Monze', 'Pemba')
input_types = ('fertilizer_d', 'fertilizer_urea', 'seed_maize')

Forecast.objects.filter(forecast_season=forecast_season).delete()
for district in districts:
    for input_type in input_types:
        result = forecast_district_input(district, input_type, forecast_season=forecast_season)
        print(district, input_type, 'created' if result else 'skipped')
```

The final deletion line needs `Forecast` imported first:

```python
from forecasting.models import Forecast
```

Run this complete shell block:

```python
from forecasting.models import Forecast
from forecasting.services import forecast_district_input

forecast_season = '2026/2027'
districts = ('Choma', 'Kalomo', 'Monze', 'Pemba')
input_types = ('fertilizer_d', 'fertilizer_urea', 'seed_maize')

Forecast.objects.filter(forecast_season=forecast_season).delete()
for district in districts:
    for input_type in input_types:
        result = forecast_district_input(district, input_type, forecast_season=forecast_season)
        print(district, input_type, 'created' if result else 'skipped')
```

## 8. Verify generated forecasts

```python
from django.db.models import Sum
from forecasting.models import Forecast

forecasts = Forecast.objects.filter(forecast_season='2026/2027')
print("Forecast count:", forecasts.count())
print("District count:", forecasts.values('district').distinct().count())

print(list(forecasts.values('district', 'input_type', 'model_used', 'seasons_used', 'predicted_quantity_kg')))

for district in ('Choma', 'Kalomo', 'Monze', 'Pemba'):
    total = forecasts.filter(district=district).aggregate(total=Sum('predicted_quantity_kg'))['total']
    print(district, total)
```

Expected baseline forecast count is 12: four districts multiplied by three input types.

Every record should show `national trend` in `model_used`, for example:

```text
ARIMA(1,1,1) national trend
```
or the log-ARIMA variant selected by the national series back-test.

`seasons_used` should equal the number of national FAOSTAT observations, which is 64 for each input type.

## 9. Full application demonstration with all districts and weather scenarios

Start the development server:

```powershell
python manage.py runserver
```

Open:

```text
http://127.0.0.1:8000
```

Use the Forecast page to demonstrate generated baseline quantities. The complete application runner is:

```python
from forecasting.services import run_all_forecasts

results = run_all_forecasts(forecast_season='2026/2027')
print('succeeded:', len(results['succeeded']))
print('skipped:', results['skipped'])
print('missing outlook:', results['unmapped'])
```

Important: `run_all_forecasts()` may skip district/input combinations during the planning season when neither a usable ZMD outlook nor a cached SEAS5 outlook is available. This weather check does not prevent the direct baseline demonstration in Section 7.

## 10. Supervisor presentation script

Use this sequence while presenting:

1. Explain that the survey supplies one real season, 2021/2022.
2. Import the national FAOSTAT series with `import_faostat_series`.
3. Show that each national series contains 64 seasons.
4. Import `import_fisp_survey`.
5. Verify that the importer creates 340 farmers and 1,020 usage records.
6. Open a Django shell and show the district counts of 86, 85, 85, and 84.
7. Explain that ARIMA is trained on the national input series, not on only one district season.
8. Generate 12 baseline forecasts for four districts and three input types.
9. Show that the forecast equals the real district 2021/2022 aggregate multiplied by the national predicted change factor.
10. Finally open the forecasting page and inventory dashboard so the supervisor can see the result in the application.

## 11. Show the calculation behind one forecast

For Choma, replace the example names with the actual database values during the presentation:

```python
from farmers.models import FarmerInputUsage
from forecasting.models import NationalInputSeries
from forecasting.services import forecast_district_input
from django.db.models import Sum

season = '2021/2022'
district = 'Choma'
input_type = 'fertilizer_urea'
target = '2026/2027'

district_2021_2022 = FarmerInputUsage.objects.filter(
    farmer__district=district,
    season=season,
    input_type=input_type
).aggregate(total=Sum('quantity_kg'))['total']

national_2021_2022 = NationalInputSeries.objects.get(
    input_type=input_type,
    season=season
).value

forecast = forecast_district_input(district, input_type, target)
print('District 2021/2022 kg:', district_2021_2022)
print('National 2021/2022 value:', national_2021_2022)
print('Target forecast kg:', forecast.predicted_quantity_kg)
