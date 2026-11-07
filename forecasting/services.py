"""
Core forecasting logic: aggregates historical FarmerInputUsage records
by district and input type, fits an ARIMA model on the resulting time
series, and predicts the next season's demand.

Kept separate from views.py so this logic can be tested/reused (e.g.
called from a management command or a Celery task later) without
depending on Django's request/response cycle.
"""
import re
import warnings
from decimal import Decimal, InvalidOperation
from functools import lru_cache

import numpy as np
import pandas as pd
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from statsmodels.tsa.arima.model import ARIMA

from farmers.models import FarmerInputUsage
from farmers.models import Farmer
from . import backtest
from .models import Forecast, NationalBacktest, NationalInputSeries
from .climate import (
    get_seas5_demand_adjustment,
    get_weather_demand_adjustment,
    scale_adjustment_for_input,
    target_rainfall_season,
)
from weather.services import get_seasonal_outlook_summary

# Season labels are "YYYY/YYYY" with consecutive years (enforced on import), so
# sorting the strings puts them in chronological order for any year.
SEASON_PATTERN = re.compile(r'(\d{4})/(\d{4})')

MIN_SEASONS_REQUIRED = 4  # ARIMA needs a handful of points to be meaningful
REQUIRED_IMPORT_COLUMNS = {'national_id', 'season', 'input_type', 'quantity_kg'}
EVENT_ID_IMPORT_COLUMN = 'usage_event_id'
VALID_INPUT_TYPES = {
    input_type for input_type, _ in FarmerInputUsage.INPUT_TYPE_CHOICES
}


def _is_season(label: str) -> bool:
    match = SEASON_PATTERN.fullmatch(label or '')
    return bool(match) and int(match.group(2)) == int(match.group(1)) + 1


def _next_season(last_season: str) -> str:
    """'2023/2024' -> '2024/2025'. Falls back to a label if unknown."""
    if _is_season(last_season):
        start = int(last_season[:4]) + 1
        return f'{start}/{start + 1}'
    return f"{last_season} + 1"


def import_demand_file(uploaded_file) -> int:
    """Validate and import farmer demand history from CSV or XLSX."""
    filename = uploaded_file.name.lower()
    try:
        if filename.endswith('.csv'):
            frame = pd.read_csv(uploaded_file)
        else:
            frame = pd.read_excel(uploaded_file)
    except Exception as exc:
        raise ValidationError(f'Unable to read the uploaded file: {exc}') from exc

    frame.columns = [str(column).strip() for column in frame.columns]
    missing_columns = REQUIRED_IMPORT_COLUMNS - set(frame.columns)
    if missing_columns:
        columns = ', '.join(sorted(missing_columns))
        raise ValidationError(f'Missing required column(s): {columns}.')
    if frame.empty:
        raise ValidationError('The uploaded file does not contain any records.')

    has_event_ids = EVENT_ID_IMPORT_COLUMN in frame.columns
    selected_columns = list(REQUIRED_IMPORT_COLUMNS)
    if has_event_ids:
        selected_columns.append(EVENT_ID_IMPORT_COLUMN)
    rows = frame[selected_columns].copy()
    rows['national_id'] = rows['national_id'].astype('string').str.strip()
    rows['season'] = rows['season'].astype('string').str.strip()
    rows['input_type'] = rows['input_type'].astype('string').str.strip()
    rows['quantity_kg'] = pd.to_numeric(rows['quantity_kg'], errors='coerce')

    if has_event_ids:
        rows[EVENT_ID_IMPORT_COLUMN] = rows[EVENT_ID_IMPORT_COLUMN].astype('string').str.strip()

    required_values = ['national_id', 'season', 'input_type', 'quantity_kg']
    if has_event_ids:
        required_values.append(EVENT_ID_IMPORT_COLUMN)
    if rows[required_values].isnull().any().any():
        raise ValidationError('Every row must contain a farmer ID, season, input type, and numeric quantity.')
    if has_event_ids and (rows[EVENT_ID_IMPORT_COLUMN] == '').any():
        raise ValidationError('Every event row must have a non-empty usage_event_id.')
    if (rows['quantity_kg'] < 0).any():
        raise ValidationError('Quantities cannot be negative.')
    if (~rows['season'].str.fullmatch(r'\d{4}/\d{4}')).any():
        raise ValidationError('Seasons must use the format YYYY/YYYY, for example 2024/2025.')
    invalid_inputs = sorted(set(rows['input_type']) - VALID_INPUT_TYPES)
    if invalid_inputs:
        raise ValidationError(f'Unsupported input type(s): {", ".join(invalid_inputs)}.')
    if has_event_ids:
        if rows[EVENT_ID_IMPORT_COLUMN].duplicated().any():
            raise ValidationError('The file contains duplicate usage_event_id values.')
    else:
        duplicate_rows = rows.duplicated(subset=['national_id', 'season', 'input_type'])
        if duplicate_rows.any():
            raise ValidationError(
                'The file contains multiple events for a farmer/input/season. '
                'Add a unique usage_event_id column to import multiple events safely.'
            )

    national_ids = set(rows['national_id'])
    farmers = {
        farmer.national_id: farmer
        for farmer in Farmer.objects.filter(national_id__in=national_ids)
    }
    missing_farmers = sorted(national_ids - set(farmers))
    if missing_farmers:
        raise ValidationError(f'Unknown farmer national ID(s): {", ".join(missing_farmers)}.')

    with transaction.atomic():
        if has_event_ids:
            event_ids = rows[EVENT_ID_IMPORT_COLUMN].tolist()
            existing_events = {
                usage.source_event_id: usage
                for usage in FarmerInputUsage.objects.filter(source_event_id__in=event_ids)
            }
            new_records = []
            for row in rows.itertuples(index=False):
                try:
                    quantity = Decimal(str(row.quantity_kg)).quantize(Decimal('0.01'))
                except (InvalidOperation, ValueError) as exc:
                    raise ValidationError(f'Invalid quantity for farmer {row.national_id}.') from exc
                event_id = getattr(row, EVENT_ID_IMPORT_COLUMN)
                existing = existing_events.get(event_id)
                if existing:
                    if (
                        existing.farmer_id != farmers[row.national_id].pk
                        or existing.season != row.season
                        or existing.input_type != row.input_type
                        or existing.quantity_kg != quantity
                    ):
                        raise ValidationError(
                            f'usage_event_id {event_id} already exists with different data.'
                        )
                    continue
                new_records.append(FarmerInputUsage(
                    farmer=farmers[row.national_id],
                    season=row.season,
                    input_type=row.input_type,
                    quantity_kg=quantity,
                    source_event_id=event_id,
                ))
            FarmerInputUsage.objects.bulk_create(new_records, batch_size=1000)
            imported_count = len(new_records)
        else:
            imported_count = 0
            for row in rows.itertuples(index=False):
                try:
                    quantity = Decimal(str(row.quantity_kg)).quantize(Decimal('0.01'))
                except (InvalidOperation, ValueError) as exc:
                    raise ValidationError(f'Invalid quantity for farmer {row.national_id}.') from exc
                farmer = farmers[row.national_id]
                existing = list(FarmerInputUsage.objects.filter(
                    farmer=farmer,
                    season=row.season,
                    input_type=row.input_type,
                )[:2])
                if len(existing) > 1 or (existing and existing[0].source_event_id):
                    raise ValidationError(
                        f'{row.national_id}/{row.season}/{row.input_type} already contains event-level records. '
                        f'Include a unique {EVENT_ID_IMPORT_COLUMN} column to import safely.'
                    )
                if existing:
                    existing[0].quantity_kg = quantity
                    existing[0].save(update_fields=['quantity_kg'])
                else:
                    FarmerInputUsage.objects.create(
                        farmer=farmer,
                        season=row.season,
                        input_type=row.input_type,
                        quantity_kg=quantity,
                    )
                imported_count += 1
    return imported_count


def get_district_input_combinations():
    """All distinct (district, input_type) pairs present in the data."""
    return (
        FarmerInputUsage.objects
        .order_by()  # clear the model's default ordering (by season) —
                     # otherwise Django adds it to SELECT DISTINCT and
                     # every season counts as a separate "distinct" row
        .values_list('farmer__district', 'input_type')
        .distinct()
    )


def build_time_series(district: str, input_type: str) -> pd.Series:
    """
    Aggregates total quantity_kg per season for one district + input
    type, ordered chronologically. Returns a pandas Series indexed by
    season, ready to feed into ARIMA.
    """
    rows = (
        FarmerInputUsage.objects
        .filter(farmer__district=district, input_type=input_type)
        .values('season')
        .annotate(total_qty=Sum('quantity_kg'))
    )
    data = {row['season']: float(row['total_qty']) for row in rows}

    # Sort chronologically, dropping any malformed season labels rather than
    # crashing on unexpected data.
    ordered_seasons = sorted(s for s in data if _is_season(s))
    values = [data[s] for s in ordered_seasons]

    return pd.Series(values, index=ordered_seasons)


def build_national_series(input_type: str) -> pd.Series:
    """The imported FAOSTAT national series for an input type, indexed by season."""
    rows = NationalInputSeries.objects.filter(input_type=input_type).order_by('season')
    data = {row.season: float(row.value) for row in rows if _is_season(row.season)}
    return pd.Series(list(data.values()), index=list(data))


def _arima_prediction(series: pd.Series, forecast_season: str | None) -> float:
    """Fit ARIMA(1,1,1) and return its prediction for the target season (default: the next one)."""
    # ARIMA(p,d,q) = (1,1,1) is a reasonable general-purpose default:
    # 1 autoregressive term, 1 differencing pass to handle trend,
    # 1 moving-average term to smooth noise. Good starting point for
    # a final-year project; Chapter 5 could discuss tuning this further.
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')  # statsmodels is noisy on short series
        model = ARIMA(series.values, order=(1, 1, 1))
        fitted = model.fit()
        steps = _season_steps(series.index[-1], forecast_season) if forecast_season else 1
        return fitted.forecast(steps=steps)[-1]


def ensure_national_backtest(input_type: str, forecast_season: str, national: pd.Series | None = None):
    """
    Return the stored back-test for an input's national series, recomputing it
    only when the series or methods changed. None when the series is too short.
    """
    national = build_national_series(input_type) if national is None else national
    steps = _season_steps(national.index[-1], forecast_season)
    if not backtest.can_backtest(len(national), steps) or (national <= 0).any():
        return None
    fingerprint = backtest.fingerprint(list(national.index), list(national.values), steps)
    existing = NationalBacktest.objects.filter(input_type=input_type, forecast_season=forecast_season).first()
    if existing and existing.data_fingerprint == fingerprint:
        return existing
    result = backtest.evaluate(list(national.index), national.values, steps)
    stored, _ = NationalBacktest.objects.update_or_create(
        input_type=input_type,
        forecast_season=forecast_season,
        defaults={
            'steps': steps,
            'chosen_method': result['chosen_method'],
            'validation_mape_fixed': result['validation_mape']['fixed'],
            'validation_mape_auto': result['validation_mape']['auto'],
            'test_mape_fixed': result['test_mape']['fixed'],
            'test_mape_auto': result['test_mape']['auto'],
            'test_mape_naive': result['test_mape']['naive'],
            'test_mape_drift': result['test_mape']['drift'],
            'first_test_season': result['first_test_season'],
            'last_test_season': result['last_test_season'],
            'data_fingerprint': fingerprint,
        },
    )
    return stored


@lru_cache(maxsize=32)
def _national_forecast(method: str, values: tuple, steps: int):
    """Every district of an input type shares one national fit, so fit it once."""
    return backtest.CANDIDATES[method](np.asarray(values), steps)


def _national_trend_prediction(district_series: pd.Series, input_type: str, forecast_season: str | None):
    """
    Forecast a district with too few seasons of its own from the national trend.

    ARIMA is fitted to the long FAOSTAT national series; the district's latest
    real season is scaled by the predicted national change since that season.
    The ARIMA variant is the one that did better in the back-test, or
    ARIMA(1,1,1) when the series is too short to back-test.
    Returns (prediction, national seasons used, target season, model label) or None.
    """
    national = build_national_series(input_type)
    if len(national) < MIN_SEASONS_REQUIRED:
        return None
    anchors = [season for season in district_series.index if season in national.index]
    if not anchors or national[anchors[-1]] <= 0:
        return None
    anchor = anchors[-1]
    target = forecast_season or _next_season(national.index[-1])
    evaluation = ensure_national_backtest(input_type, target, national)
    method = evaluation.chosen_method if evaluation else 'fixed'
    national_prediction, label = _national_forecast(
        method, tuple(national.values), _season_steps(national.index[-1], target),
    )
    national_prediction = max(national_prediction, 0)
    return (
        district_series[anchor] * national_prediction / national[anchor],
        len(national),
        target,
        f'{label} national trend',
    )


def _season_steps(last_season: str, forecast_season: str) -> int:
    """Return the number of season-ahead ARIMA steps needed for a target season."""
    try:
        last_start, last_end = (int(part) for part in last_season.split('/'))
        target_start, target_end = (int(part) for part in forecast_season.split('/'))
    except (ValueError, TypeError) as exc:
        raise ValueError('Season labels must use the YYYY/YYYY format.') from exc
    if last_end != last_start + 1 or target_end != target_start + 1:
        raise ValueError('Season labels must be consecutive years in YYYY/YYYY format.')
    steps = target_start - last_start
    if steps < 1:
        raise ValueError('The target forecast season must be after the latest demand season.')
    return steps


def forecast_district_input(
    district: str,
    input_type: str,
    forecast_season: str | None = None,
    weather_adjustment_percent: Decimal = Decimal('0'),
    weather_summary: str = '',
    seasonal_weather_summary: str = '',
    seasonal_weather_retrieved_date=None,
    seas5_adjustment_percent: Decimal | None = None,
    seas5_summary: str = '',
) -> Forecast | None:
    """
    Fit ARIMA and save its baseline plus separate ZMD and SEAS5 rainfall scenarios.

    The persisted predicted_quantity_kg remains equal to the baseline because
    inventory allocation consumes it by default; the scenario quantities are
    alternatives the user can switch to, never a fallback for one another.
    """
    series = build_time_series(district, input_type)

    if len(series) >= MIN_SEASONS_REQUIRED:
        prediction = _arima_prediction(series, forecast_season)
        forecast_season = forecast_season or _next_season(series.index[-1])
        seasons_used = len(series)
        base_model = 'ARIMA(1,1,1)'
    else:
        national = _national_trend_prediction(series, input_type, forecast_season)
        if national is None:
            return None
        prediction, seasons_used, forecast_season, base_model = national

    # ARIMA can occasionally predict a negative number on a short/noisy
    # series, which makes no physical sense for input quantities.
    baseline_quantity = Decimal(str(max(prediction, 0))).quantize(Decimal('0.01'))
    scenario_quantity = _scenario_quantity(baseline_quantity, weather_adjustment_percent)
    seas5_scenario_quantity = (
        _scenario_quantity(baseline_quantity, seas5_adjustment_percent)
        if seas5_adjustment_percent is not None else None
    )

    forecast_obj, _ = Forecast.objects.update_or_create(
        district=district,
        input_type=input_type,
        forecast_season=forecast_season,
        defaults={
            # Keep the value consumed by allocation equal to the baseline.
            'predicted_quantity_kg': baseline_quantity,
            'baseline_predicted_quantity_kg': baseline_quantity,
            'weather_adjustment_percent': weather_adjustment_percent,
            'weather_summary': weather_summary,
            'weather_scenario_quantity_kg': scenario_quantity,
            'seas5_adjustment_percent': seas5_adjustment_percent,
            'seas5_summary': seas5_summary,
            'seas5_scenario_quantity_kg': seas5_scenario_quantity,
            'seasonal_weather_summary': seasonal_weather_summary,
            'seasonal_weather_retrieved_date': seasonal_weather_retrieved_date,
            'seasons_used': seasons_used,
            'model_used': (
                f'{base_model} + weather scenario'
                if weather_summary or seas5_summary or seasonal_weather_summary else base_model
            ),
        },
    )
    return forecast_obj


def _scenario_quantity(baseline_quantity: Decimal, adjustment_percent: Decimal) -> Decimal:
    adjustment_factor = Decimal('1') + (adjustment_percent / Decimal('100'))
    return max((baseline_quantity * adjustment_factor).quantize(Decimal('0.01')), Decimal('0'))


def run_all_forecasts(forecast_season: str | None = None) -> dict:
    """
    Runs forecast_district_input for every district/input_type
    combination found in the data. Returns a summary dict for display
    in the UI (how many succeeded, how many were skipped for lack of
    data, and why).
    """
    combinations = get_district_input_combinations()
    planning_season = target_rainfall_season()
    succeeded = []
    skipped = []
    unmapped = []
    missing_seasonal_outlook = []
    missing_zmd_outlook = []

    for district, input_type in combinations:
        zmd = None
        seas5 = None
        seasonal_outlook = None
        if forecast_season == planning_season:
            # ZMD and SEAS5 scenarios are computed independently; a missing
            # outlook leaves that scenario blank rather than borrowing the other.
            zmd = get_weather_demand_adjustment(district, forecast_season)
            if zmd is None:
                missing_zmd_outlook.append(district)
            seasonal_outlook = get_seasonal_outlook_summary(district, forecast_season)
            seas5 = get_seas5_demand_adjustment(seasonal_outlook)
            if seas5 is None:
                missing_seasonal_outlook.append(district)
            if zmd is None and seas5 is None:
                unmapped.append((district, input_type))
                continue
            zmd = scale_adjustment_for_input(zmd, input_type) if zmd else None
            seas5 = scale_adjustment_for_input(seas5, input_type) if seas5 else None
        result = forecast_district_input(
            district,
            input_type,
            forecast_season=forecast_season,
            weather_adjustment_percent=zmd['adjustment_percent'] if zmd else Decimal('0'),
            weather_summary=zmd['summary'] if zmd else '',
            seasonal_weather_summary=(seasonal_outlook['summary'] if seasonal_outlook else ''),
            seasonal_weather_retrieved_date=(
                seasonal_outlook['retrieved_date'] if seasonal_outlook else None
            ),
            seas5_adjustment_percent=seas5['adjustment_percent'] if seas5 else None,
            seas5_summary=seas5['summary'] if seas5 else '',
        )
        if result:
            succeeded.append(result)
        else:
            skipped.append((district, input_type))

    return {
        'succeeded': succeeded,
        'skipped': skipped,
        'unmapped': unmapped,
        'missing_seasonal_outlook': sorted(set(missing_seasonal_outlook)),
        'missing_zmd_outlook': sorted(set(missing_zmd_outlook)),
    }