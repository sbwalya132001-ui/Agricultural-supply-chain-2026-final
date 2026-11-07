from django.contrib import messages
from django.db.models import Count, Sum
from django.shortcuts import render, redirect
from django.utils import timezone
from zoneinfo import ZoneInfo

from .models import Forecast, NationalBacktest, NationalInputSeries
from .forms import DemandDataUploadForm
from .services import import_demand_file, run_all_forecasts
from .climate import OUTLOOK_PERIODS, target_rainfall_season
from farmers.models import FarmerInputUsage
from weather.models import DailyWeather
from weather.seasonal_map import seasonal_map_data
from weather.services import ECMWF_SOURCE
from accounts.decorators import ROLE_DISTRICT, ROLE_MINISTRY, get_user_district, get_user_role, role_required


def _forecast_rows(forecasts):
    today = timezone.localtime(timezone.now(), ZoneInfo('Africa/Lusaka')).date()
    weather_by_district = {
        row['district'].casefold(): row
        for row in DailyWeather.objects.filter(
            record_type='forecast',
            source=ECMWF_SOURCE,
            date__gte=today,
        ).values('district').annotate(
            rainfall_total_mm=Sum('rainfall_mm'),
            forecast_days=Count('id'),
        )
    }
    return [
        {
            'forecast': forecast,
            'ecmwf_weather': weather_by_district.get(forecast.district.casefold()),
        }
        for forecast in forecasts
    ]


def _backtest_rows(season):
    """Stored national back-tests for the season, with the series each one tested."""
    latest_series = {}
    for series in NationalInputSeries.objects.order_by('season'):
        latest_series[series.input_type] = series
    rows = []
    for evaluation in NationalBacktest.objects.filter(forecast_season=season):
        errors = {
            'fixed': evaluation.test_mape_fixed,
            'auto': evaluation.test_mape_auto,
            'naive': evaluation.test_mape_naive,
            'drift': evaluation.test_mape_drift,
        }
        rows.append({
            'backtest': evaluation,
            'series': latest_series.get(evaluation.input_type),
            'errors': errors,
            'best': min(errors, key=errors.get),
        })
    return rows


WEATHER_SCENARIOS = ('zmd', 'seas5')


def _selected_scenario(request):
    scenario = request.GET.get('scenario', '')
    return scenario if scenario in WEATHER_SCENARIOS else WEATHER_SCENARIOS[0]


def _scenario_context(request, forecasts):
    """The ZMD/SEAS5 switch plus the seasonal map that follows it."""
    scenario = _selected_scenario(request)
    forecast_districts = sorted({forecast.district for forecast in forecasts}, key=str.casefold)
    # A district chosen on the map (?district=) sticks across reloads; district
    # users stay on their own district.
    selected_district = (
        get_user_district(request.user)
        or request.GET.get('district', '').strip()
        or (forecast_districts[0] if forecast_districts else '')
    )
    return {
        'scenario': scenario,
        'target_season': target_rainfall_season(),
        'seasonal_map': seasonal_map_data(),
        'initial_map_layer': 'seas5' if scenario == 'seas5' else f'zmd:{OUTLOOK_PERIODS[0]}',
        # Opens the map's district card and filters the forecast table.
        'selected_district': selected_district,
        'forecast_districts': forecast_districts,
        'can_refresh_national': get_user_role(request.user) == ROLE_MINISTRY,
    }


@role_required(ROLE_MINISTRY, ROLE_DISTRICT)
def forecast_list(request):
    forecasts = Forecast.objects.all()
    district = get_user_district(request.user)
    if district:
        forecasts = forecasts.filter(district__iexact=district)
    forecast_items = list(forecasts)
    return render(request, 'forecasting/forecast_list.html', {
        'forecasts': forecast_items,
        'forecast_rows': _forecast_rows(forecast_items),
        'backtests': _backtest_rows(target_rainfall_season()),
        'upload_form': DemandDataUploadForm(),
        **_scenario_context(request, forecast_items),
    })


@role_required(ROLE_MINISTRY)
def upload_demand_data(request):
    if request.method != 'POST':
        return redirect('forecast_list')
    form = DemandDataUploadForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            imported_count = import_demand_file(form.cleaned_data['demand_file'])
        except Exception as exc:
            form.add_error('demand_file', str(exc))
        else:
            messages.success(request, f'Imported {imported_count} demand records successfully.')
            return redirect('forecast_list')
    forecasts = Forecast.objects.all()
    district = get_user_district(request.user)
    if district:
        forecasts = forecasts.filter(district__iexact=district)
    forecast_items = list(forecasts)
    return render(request, 'forecasting/forecast_list.html', {
        'forecasts': forecast_items,
        'forecast_rows': _forecast_rows(forecast_items),
        'backtests': _backtest_rows(target_rainfall_season()),
        'upload_form': form,
        **_scenario_context(request, forecast_items),
    })


@role_required(ROLE_MINISTRY)
def run_forecast(request):
    """
    Triggers ARIMA across every district/input_type combination found
    in the data. This is a POST-only action (not a page you can GET/
    refresh accidentally) since it writes to the database.
    """
    if request.method == 'POST':
        if not FarmerInputUsage.objects.exists():
            messages.error(
                request,
                'No historical input-usage records are loaded. Import the usage CSV first, '
                'then run forecast generation again.',
            )
            return redirect('forecast_list')

        season = target_rainfall_season()
        results = run_all_forecasts(forecast_season=season)
        if results['succeeded']:
            messages.success(
                request,
                f"{season} baseline and weather scenario generation complete: "
                f"{len(results['succeeded'])} forecasts generated."
            )
        else:
            messages.warning(
                request,
                'No forecasts were generated. Check that each district/input combination has at least '
                'four supported historical seasons and a ZMD or cached SEAS5 outlook.',
            )
        if results['skipped']:
            skipped_desc = ', '.join(f"{d}/{i}" for d, i in results['skipped'])
            messages.warning(
                request,
                f"Skipped (not enough historical seasons yet): {skipped_desc}"
            )
        if results.get('unmapped'):
            unmapped_desc = ', '.join(sorted({district for district, _ in results['unmapped']}))
            messages.warning(
                request,
                f"No ZMD outlook or cached SEAS5 outlook for: {unmapped_desc}. "
                'Refresh the SEAS5 seasonal outlook on the Weather page, then generate again.',
            )
        if results.get('missing_seasonal_outlook'):
            messages.warning(
                request,
                'No cached ECMWF SEAS5 seasonal outlook was available for: '
                + ', '.join(results['missing_seasonal_outlook'])
                + '. Their SEAS5 scenario is left blank; refresh SEAS5 on the Weather page.',
            )
        if results.get('missing_zmd_outlook'):
            messages.warning(
                request,
                'No ZMD outlook zone covers: '
                + ', '.join(results['missing_zmd_outlook'])
                + '. Their ZMD scenario is left blank.',
            )
    return redirect('forecast_list')