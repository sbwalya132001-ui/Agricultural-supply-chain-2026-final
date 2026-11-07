from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from urllib.parse import urlencode

from accounts.decorators import (
    ROLE_DEALER,
    ROLE_DISTRICT,
    ROLE_MINISTRY,
    ROLE_SUPPLIER,
    get_user_district,
    get_user_role,
    role_required,
)
from farmers.models import Farmer
from forecasting.climate import (
    RAINFALL_CATEGORY_LABELS,
    seas5_rainfall_category,
    target_rainfall_season,
)
from .models import DailyWeather, GlobalModelTemperature, MonthlySeasonalOutlook
from .services import (
    ECMWF_SEASONAL_MODEL,
    ECMWF_SEASONAL_SOURCE,
    ECMWF_SOURCE,
    GLOBAL_TEMPERATURE_MODELS,
    WeatherServiceError,
    fetch_district_forecast,
    fetch_district_seasonal_outlook,
    fetch_national_seasonal_outlook,
    get_seasonal_outlook_summary,
)
from .seas5_field import build_seas5_field
from .seasonal_map import seasonal_map_data


def _attach_model_temperatures(district, days):
    """Attach each global model's min/max to the consensus rows for display."""
    by_date = {}
    for row in GlobalModelTemperature.objects.filter(
        district__iexact=district, date__in=[day.date for day in days],
    ):
        by_date.setdefault(row.date, {})[row.model] = row
    for day in days:
        models_for_day = by_date.get(day.date, {})
        day.model_temperatures = [
            {'label': label, 'row': models_for_day.get(model)}
            for model, label in GLOBAL_TEMPERATURE_MODELS.items()
        ]
        maximums = [row.temperature_max_c for row in models_for_day.values() if row.temperature_max_c is not None]
        day.temperature_max_spread_c = max(maximums) - min(maximums) if len(maximums) > 1 else None
    return days


ALLOWED_WEATHER_ROLES = (ROLE_MINISTRY, ROLE_DISTRICT, ROLE_SUPPLIER, ROLE_DEALER)


@role_required(*ALLOWED_WEATHER_ROLES)
def weather_dashboard(request):
    user_district = get_user_district(request.user)
    is_ministry = get_user_role(request.user) == ROLE_MINISTRY
    farmer_districts = list(
        Farmer.objects.exclude(district='')
        .order_by('district')
        .values_list('district', flat=True)
        .distinct()
    )
    districts = sorted(set(farmer_districts), key=str.casefold)

    if is_ministry:
        if request.method == 'POST':
            requested_district = request.POST.get('district', '')
            selected_district = requested_district if requested_district in districts else ''
        else:
            selected_district = request.GET.get('district', '')
        if request.method != 'POST' and selected_district not in districts:
            selected_district = districts[0] if districts else ''
    else:
        selected_district = user_district or ''

    if request.method == 'POST' and request.POST.get('action') == 'refresh_seasonal_national':
        if not is_ministry:
            messages.error(request, 'Only Ministry users can refresh the national seasonal outlook.')
        else:
            try:
                result = fetch_national_seasonal_outlook()
                # Rebuild the smooth map field from the same SEAS5 run.
                field = build_seas5_field()
            except WeatherServiceError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request,
                    f"Updated the ECMWF SEAS5 outlook for {result['district_count']} districts "
                    f"and the map field from {field['grid_points']} grid points.",
                )
        return redirect(f'{reverse("weather_dashboard")}#seasonal-map')

    if request.method == 'POST':
        action = request.POST.get('action', 'refresh_short_range')
        allowed_actions = {'refresh_short_range', 'refresh_seasonal'}
        if is_ministry and not selected_district:
            messages.error(request, 'Select a district from the available options.')
        elif not selected_district:
            messages.error(request, 'Your account is not assigned to a district yet.')
        elif action not in allowed_actions:
            messages.error(request, 'Select a supported weather refresh action.')
        else:
            try:
                if action == 'refresh_seasonal':
                    result = fetch_district_seasonal_outlook(selected_district)
                else:
                    result = fetch_district_forecast(selected_district)
            except WeatherServiceError as exc:
                messages.error(request, str(exc))
            else:
                if action == 'refresh_seasonal':
                    messages.success(
                        request,
                        f"Updated {result['count']} ECMWF SEAS5 monthly outlook values for {selected_district}.",
                    )
                else:
                    models_used = ', '.join(result.get('temperature_models', [])) or 'none'
                    messages.success(
                        request,
                        f"Updated {result['historical_count']} past days and "
                        f"{result['forecast_count']} forecast days for {selected_district} "
                        f"(temperature models: {models_used}).",
                    )
        if is_ministry and selected_district:
            return redirect(f'{reverse("weather_dashboard")}?{urlencode({"district": selected_district})}')
        return redirect('weather_dashboard')

    forecasts = DailyWeather.objects.none()
    recent_weather = DailyWeather.objects.none()
    seasonal_outlooks = MonthlySeasonalOutlook.objects.none()
    season_rainfall = None
    latest_update = None
    if selected_district:
        forecasts = DailyWeather.objects.filter(
            district__iexact=selected_district,
            record_type='forecast',
            source=ECMWF_SOURCE,
        ).order_by('date')
        recent_weather = DailyWeather.objects.filter(
            district__iexact=selected_district,
            record_type='historical',
            source=ECMWF_SOURCE,
        ).order_by('-date')
        seasonal_outlooks = MonthlySeasonalOutlook.objects.filter(
            district__iexact=selected_district,
            model=ECMWF_SEASONAL_MODEL,
            source=ECMWF_SEASONAL_SOURCE,
        ).order_by('-retrieved_date', 'valid_month')
        latest_daily_weather = forecasts.first() or recent_weather.first()
        latest_update = (
            seasonal_outlooks.first().fetched_at if seasonal_outlooks
            else latest_daily_weather.fetched_at if latest_daily_weather
            else None
        )
        forecasts = _attach_model_temperatures(selected_district, list(forecasts))
        season = target_rainfall_season()
        outlook = get_seasonal_outlook_summary(selected_district, season)
        if outlook and outlook['rainfall_anomaly_percent'] is not None:
            season_rainfall = {
                'season': season,
                'anomaly_percent': outlook['rainfall_anomaly_percent'],
                'category': RAINFALL_CATEGORY_LABELS[
                    seas5_rainfall_category(outlook['rainfall_anomaly_percent'])
                ],
                'months': outlook['months_with_rainfall'],
            }

    return render(request, 'weather/weather_dashboard.html', {
        'districts': districts if is_ministry else [],
        'selected_district': selected_district,
        'forecasts': forecasts,
        'season_rainfall': season_rainfall,
        'seasonal_map': seasonal_map_data(),
        'can_refresh_national': is_ministry,
        'recent_weather': recent_weather,
        'seasonal_outlooks': seasonal_outlooks,
        'latest_update': latest_update,
        'can_select_district': is_ministry,
    })