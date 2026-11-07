"""Open-Meteo ECMWF IFS daily and SEAS5 seasonal weather integrations."""
import json
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import Avg, Max

from farmers.models import Farmer
from .models import DailyWeather, GlobalModelTemperature, MonthlySeasonalOutlook


OPEN_METEO_FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'
OPEN_METEO_SEASONAL_URL = 'https://seasonal-api.open-meteo.com/v1/seasonal'
OPEN_METEO_GEOCODING_URL = 'https://geocoding-api.open-meteo.com/v1/search'
ECMWF_MODEL = 'ecmwf_ifs'
ECMWF_SOURCE = 'Open-Meteo ECMWF IFS'
# Global deterministic models used for the temperature consensus. ECMWF IFS
# remains the rainfall/humidity source; temperature is the mean of whichever
# models report a value for that day (ICON's horizon is shorter than 10 days).
GLOBAL_TEMPERATURE_MODELS = {
    'ecmwf_ifs': 'ECMWF IFS',
    'gfs_global': 'NOAA GFS',
    'icon_global': 'DWD ICON',
}
ECMWF_SEASONAL_MODEL = 'ecmwf_seas5'
ECMWF_SEASONAL_SOURCE = 'Open-Meteo ECMWF SEAS5'
PAST_DAYS = 31
FORECAST_DAYS = 10
LOCAL_TIMEZONE = ZoneInfo('Africa/Lusaka')
# Simplified OCHA admin-2 boundaries (116 districts), built by the
# build_district_geojson management command.
DISTRICT_GEOJSON_PATH = settings.BASE_DIR / 'static' / 'geo' / 'zambia_districts.geojson'
PROVINCE_GEOJSON_PATH = settings.BASE_DIR / 'static' / 'geo' / 'zambia_provinces.geojson'
COUNTRY_GEOJSON_PATH = settings.BASE_DIR / 'static' / 'geo' / 'zambia_country.geojson'
# Open-Meteo accepts several coordinates per request; keep URLs a sensible length.
SEASONAL_BATCH_SIZE = 40


class WeatherServiceError(Exception):
    """Raised when district location or Open-Meteo weather data cannot be fetched."""


def _request_json(url, params):
    request = Request(
        f'{url}?{urlencode(params)}',
        headers={'Accept': 'application/json', 'User-Agent': 'FISP-System/1.0'},
    )
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode('utf-8'))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise WeatherServiceError(
            'Could not contact the weather service. Check your internet connection and try again.'
        ) from exc


def _valid_coordinates(latitude, longitude):
    return (
        latitude is not None
        and longitude is not None
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
        and not (latitude == 0 and longitude == 0)
    )


def resolve_district_coordinates(district):
    """Use the mean of valid farmer GPS points, then the district's boundary centre, then geocoding."""
    farmer_location = Farmer.objects.filter(
        district__iexact=district,
        latitude__isnull=False,
        longitude__isnull=False,
        latitude__gte=-90,
        latitude__lte=90,
        longitude__gte=-180,
        longitude__lte=180,
    ).exclude(
        latitude=0,
        longitude=0,
    ).aggregate(latitude=Avg('latitude'), longitude=Avg('longitude'))
    latitude = farmer_location['latitude']
    longitude = farmer_location['longitude']
    if _valid_coordinates(latitude, longitude):
        return float(latitude), float(longitude)

    try:
        boundaries = load_zambia_districts()
    except WeatherServiceError:
        boundaries = []
    for boundary in boundaries:
        if district.strip().casefold() == boundary['name'].casefold():
            return boundary['center_lat'], boundary['center_lon']

    payload = _request_json(OPEN_METEO_GEOCODING_URL, {
        'name': district,
        'count': 10,
        'language': 'en',
        'format': 'json',
    })
    for result in payload.get('results', []):
        if result.get('country_code') == 'ZM':
            latitude = result.get('latitude')
            longitude = result.get('longitude')
            if _valid_coordinates(latitude, longitude):
                return float(latitude), float(longitude)
    raise WeatherServiceError(
        f'Could not find a location for {district} in Zambia. Add valid GPS coordinates to farmers in that district.'
    )


def _decimal_or_none(value):
    if value is None:
        return None
    try:
        return Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise WeatherServiceError('The weather service returned invalid numeric data.') from exc


def _mean_or_none(values):
    return sum(values, Decimal('0')) / len(values) if values else None


def fetch_district_forecast(district):
    """Fetch 31 past and 10 future days; ECMWF IFS rain plus a global-model temperature consensus."""
    latitude, longitude = resolve_district_coordinates(district)
    payload = _request_json(OPEN_METEO_FORECAST_URL, {
        'latitude': latitude,
        'longitude': longitude,
        'hourly': 'temperature_2m,relative_humidity_2m,rain',
        'daily': 'weather_code',
        'models': ','.join(GLOBAL_TEMPERATURE_MODELS),
        'past_days': PAST_DAYS,
        'forecast_days': FORECAST_DAYS,
        'timezone': 'Africa/Lusaka',
    })
    # With several models, Open-Meteo suffixes each hourly field with the model name.
    hourly = payload.get('hourly', {})
    timestamps = hourly.get('time', [])
    required_arrays = tuple(
        f'{field}_{ECMWF_MODEL}' for field in ('temperature_2m', 'relative_humidity_2m', 'rain')
    )
    if not timestamps or any(len(hourly.get(key, [])) != len(timestamps) for key in required_arrays):
        raise WeatherServiceError('The ECMWF weather service returned incomplete hourly data. Try again later.')
    temperature_models = [
        model for model in GLOBAL_TEMPERATURE_MODELS
        if len(hourly.get(f'temperature_2m_{model}', [])) == len(timestamps)
    ]

    by_day = defaultdict(lambda: {
        'temperatures': defaultdict(list), 'humidities': [], 'rainfall': [],
    })
    try:
        for index, timestamp in enumerate(timestamps):
            day = datetime.fromisoformat(timestamp).date()
            for api_field, bucket in (
                (f'relative_humidity_2m_{ECMWF_MODEL}', 'humidities'),
                (f'rain_{ECMWF_MODEL}', 'rainfall'),
            ):
                value = hourly[api_field][index]
                if value is not None:
                    by_day[day][bucket].append(Decimal(str(value)))
            for model in temperature_models:
                value = hourly[f'temperature_2m_{model}'][index]
                if value is not None:
                    by_day[day]['temperatures'][model].append(Decimal(str(value)))
    except (ValueError, TypeError, IndexError, InvalidOperation) as exc:
        raise WeatherServiceError('The global weather models returned malformed hourly data.') from exc

    # The day's condition icon follows ECMWF, like rainfall. It is optional:
    # a day without a code simply shows no icon.
    daily = payload.get('daily', {})
    weather_codes = {}
    for day, code in zip(daily.get('time', []), daily.get(f'weather_code_{ECMWF_MODEL}', [])):
        if isinstance(code, (int, float)) and code >= 0:
            weather_codes[date.fromisoformat(day)] = int(code)

    today = datetime.now(LOCAL_TIMEZONE).date()
    records = []
    model_temperatures = []
    for day, values in sorted(by_day.items()):
        humidities = values['humidities']
        rainfall = values['rainfall']
        daily_minimums = []
        daily_maximums = []
        for model, temps in values['temperatures'].items():
            # Skip partial days (e.g. the hour where ICON's horizon ends) so a
            # model's min/max always covers the full day.
            if len(temps) < 24:
                continue
            daily_minimums.append(min(temps))
            daily_maximums.append(max(temps))
            model_temperatures.append({
                'date': day,
                'model': model,
                'temperature_min_c': _decimal_or_none(min(temps)),
                'temperature_max_c': _decimal_or_none(max(temps)),
            })
        records.append({
            'date': day,
            'record_type': 'historical' if day < today else 'forecast',
            'rainfall_mm': _decimal_or_none(sum(rainfall, Decimal('0')) if rainfall else None),
            'temperature_min_c': _decimal_or_none(_mean_or_none(daily_minimums)),
            'temperature_max_c': _decimal_or_none(_mean_or_none(daily_maximums)),
            'temperature_model_count': len(daily_minimums),
            'humidity_mean_percent': _decimal_or_none(_mean_or_none(humidities)),
            'weather_code': weather_codes.get(day),
        })

    historical = [row for row in records if row['record_type'] == 'historical']
    future = [row for row in records if row['record_type'] == 'forecast']
    if not future:
        raise WeatherServiceError('The ECMWF weather service returned no upcoming forecast days.')

    with transaction.atomic():
        for row in records:
            DailyWeather.objects.update_or_create(
                district=district,
                record_type=row['record_type'],
                date=row['date'],
                defaults={
                    **{key: value for key, value in row.items() if key not in ('date', 'record_type')},
                    'source': ECMWF_SOURCE,
                },
            )
        for record_type, group in (('historical', historical), ('forecast', future)):
            cached = DailyWeather.objects.filter(
                district=district,
                record_type=record_type,
                source=ECMWF_SOURCE,
            )
            dates = [row['date'] for row in group]
            if dates:
                cached.exclude(date__in=dates).delete()
            else:
                cached.delete()
        GlobalModelTemperature.objects.filter(district=district).delete()
        GlobalModelTemperature.objects.bulk_create(
            GlobalModelTemperature(district=district, **row) for row in model_temperatures
        )

    return {
        'historical_count': len(historical),
        'forecast_count': len(future),
        'temperature_models': [GLOBAL_TEMPERATURE_MODELS[model] for model in temperature_models],
        'latitude': latitude,
        'longitude': longitude,
    }


def fetch_district_seasonal_outlook(district):
    """Fetch and store ECMWF SEAS5 monthly mean/anomaly rainfall outlook.

    API monthly means and anomalies are outlook evidence for scenario display;
    they are not a calibrated input-demand elasticity.
    """
    latitude, longitude = resolve_district_coordinates(district)
    payload = _request_json(OPEN_METEO_SEASONAL_URL, {
        'latitude': latitude,
        'longitude': longitude,
        'monthly': 'precipitation_mean,precipitation_anomaly',
        'models': ECMWF_SEASONAL_MODEL,
        'timezone': 'Africa/Lusaka',
    })
    outlook_rows, retrieved_date = _seasonal_outlook_rows(district, payload)
    _save_seasonal_outlook_rows(outlook_rows)
    return {
        'count': len(outlook_rows),
        'retrieved_date': retrieved_date,
        'latitude': latitude,
        'longitude': longitude,
    }


def load_zambia_districts():
    """Return name, province and centre point for each district on the map."""
    try:
        collection = json.loads(DISTRICT_GEOJSON_PATH.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise WeatherServiceError(
            'The Zambia district boundaries are missing. Run "python manage.py build_district_geojson".'
        ) from exc
    return [feature['properties'] for feature in collection['features']]


def fetch_national_seasonal_outlook():
    """Fetch SEAS5 monthly rainfall for every Zambian district in batched requests.

    Uses each district's boundary centre point, so map-wide values are
    comparable; one district's figure can differ slightly from a refresh based
    on its farmers' GPS points.
    """
    districts = load_zambia_districts()
    outlook_rows = []
    retrieved_date = None
    for start in range(0, len(districts), SEASONAL_BATCH_SIZE):
        batch = districts[start:start + SEASONAL_BATCH_SIZE]
        payload = _request_json(OPEN_METEO_SEASONAL_URL, {
            'latitude': ','.join(str(district['center_lat']) for district in batch),
            'longitude': ','.join(str(district['center_lon']) for district in batch),
            'monthly': 'precipitation_mean,precipitation_anomaly',
            'models': ECMWF_SEASONAL_MODEL,
            'timezone': 'Africa/Lusaka',
        })
        # A single location comes back as an object, several as a list.
        locations = payload if isinstance(payload, list) else [payload]
        if len(locations) != len(batch):
            raise WeatherServiceError('The seasonal weather service returned an unexpected number of locations.')
        for district, location in zip(batch, locations):
            rows, retrieved_date = _seasonal_outlook_rows(district['name'], location)
            outlook_rows.extend(rows)
    _save_seasonal_outlook_rows(outlook_rows)
    return {
        'district_count': len(districts),
        'count': len(outlook_rows),
        'retrieved_date': retrieved_date,
    }


def _seasonal_outlook_rows(district, payload):
    monthly = payload.get('monthly', {})
    dates = monthly.get('time', [])
    required_arrays = ('precipitation_mean', 'precipitation_anomaly')
    if not dates or any(len(monthly.get(key, [])) != len(dates) for key in required_arrays):
        raise WeatherServiceError(
            'The seasonal weather service returned incomplete ECMWF SEAS5 data. Please try again later.'
        )

    retrieved_date = datetime.now(LOCAL_TIMEZONE).date()
    outlook_rows = []
    try:
        for index, month in enumerate(dates):
            valid_month = date.fromisoformat(month)
            mean = _decimal_or_none(monthly['precipitation_mean'][index])
            anomaly = _decimal_or_none(monthly['precipitation_anomaly'][index])
            if valid_month < date(retrieved_date.year, retrieved_date.month, 1):
                continue
            outlook_rows.append({
                'district': district,
                'model': ECMWF_SEASONAL_MODEL,
                'source': ECMWF_SEASONAL_SOURCE,
                'retrieved_date': retrieved_date,
                'valid_month': date(valid_month.year, valid_month.month, 1),
                'precipitation_mean_mm': mean,
                'precipitation_anomaly_mm': anomaly,
            })
    except (ValueError, TypeError, IndexError) as exc:
        raise WeatherServiceError('The seasonal weather service returned malformed data.') from exc

    if not outlook_rows:
        raise WeatherServiceError('The seasonal weather service returned no current or future months.')
    return outlook_rows, retrieved_date


def _save_seasonal_outlook_rows(outlook_rows):
    with transaction.atomic():
        for row in outlook_rows:
            MonthlySeasonalOutlook.objects.update_or_create(
                district=row['district'],
                model=row['model'],
                retrieved_date=row['retrieved_date'],
                valid_month=row['valid_month'],
                defaults={
                    'source': row['source'],
                    'precipitation_mean_mm': row['precipitation_mean_mm'],
                    'precipitation_anomaly_mm': row['precipitation_anomaly_mm'],
                },
            )


def season_rainfall_departure(outlooks):
    """Return (% departure from the SEAS5 model normal, months used) for monthly outlooks."""
    # SEAS5 anomaly = forecast mean - model climatology, so the model's normal
    # for the season is sum(mean - anomaly) and the departure is relative to it.
    complete = [
        outlook for outlook in outlooks
        if outlook.precipitation_mean_mm is not None and outlook.precipitation_anomaly_mm is not None
    ]
    forecast_total = sum((outlook.precipitation_mean_mm for outlook in complete), Decimal('0'))
    normal_total = forecast_total - sum(
        (outlook.precipitation_anomaly_mm for outlook in complete), Decimal('0'),
    )
    if normal_total <= 0:
        return None, len(complete)
    departure = (forecast_total - normal_total) / normal_total * Decimal('100')
    return departure.quantize(Decimal('0.1')), len(complete)


def get_national_seasonal_outlooks(forecast_season):
    """Return {district: [months]} from each district's latest SEAS5 snapshot (Oct-Mar)."""
    start_year = int(forecast_season.split('/')[0])
    latest = {}
    for outlook in MonthlySeasonalOutlook.objects.filter(
        model=ECMWF_SEASONAL_MODEL,
        valid_month__gte=date(start_year, 10, 1),
        valid_month__lte=date(start_year + 1, 3, 1),
    ).order_by('district', '-retrieved_date', 'valid_month'):
        months = latest.setdefault(outlook.district, [])
        # Rows arrive newest snapshot first, so keep only that snapshot.
        if months and months[0].retrieved_date != outlook.retrieved_date:
            continue
        months.append(outlook)
    return latest


def get_seasonal_outlook_summary(district, forecast_season):
    """Summarize the latest cached SEAS5 October-March outlook for a season."""
    try:
        start_year = int(forecast_season.split('/')[0])
    except (ValueError, IndexError) as exc:
        raise ValueError('Forecast season must use the YYYY/YYYY format.') from exc

    retrieved_date = MonthlySeasonalOutlook.objects.filter(
        district__iexact=district,
        model=ECMWF_SEASONAL_MODEL,
    ).aggregate(latest=Max('retrieved_date'))['latest']
    if retrieved_date is None:
        return None

    first_month = date(start_year, 10, 1)
    last_month = date(start_year + 1, 3, 1)
    outlooks = list(MonthlySeasonalOutlook.objects.filter(
        district__iexact=district,
        model=ECMWF_SEASONAL_MODEL,
        retrieved_date=retrieved_date,
        valid_month__gte=first_month,
        valid_month__lte=last_month,
    ).order_by('valid_month'))
    if not outlooks:
        return None

    rainfall_anomaly_percent, months_with_rainfall = season_rainfall_departure(outlooks)

    summary_parts = []
    for outlook in outlooks:
        if outlook.precipitation_anomaly_mm is None:
            anomaly_text = 'anomaly unavailable'
        else:
            anomaly = outlook.precipitation_anomaly_mm
            sign = '+' if anomaly > 0 else ''
            anomaly_text = f'{sign}{anomaly:.1f} mm anomaly'
        summary_parts.append(f'{outlook.valid_month:%b}: {anomaly_text}')

    return {
        'retrieved_date': retrieved_date,
        'summary': '; '.join(summary_parts)[:500],
        'months': outlooks,
        'rainfall_anomaly_percent': rainfall_anomaly_percent,
        'months_with_rainfall': months_with_rainfall,
    }