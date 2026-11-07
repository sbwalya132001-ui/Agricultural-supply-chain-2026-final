import tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import numpy as np
from django.contrib.auth.models import Group, User
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.decorators import ROLE_DISTRICT, ROLE_MINISTRY
from accounts.models import UserProfile
from farmers.models import Farmer
from . import rasters, seas5_field
from .models import DailyWeather, GlobalModelTemperature, MonthlySeasonalOutlook
from .services import (
    ECMWF_SOURCE,
    ECMWF_SEASONAL_SOURCE,
    LOCAL_TIMEZONE,
    WeatherServiceError,
    fetch_district_forecast,
    fetch_district_seasonal_outlook,
    fetch_national_seasonal_outlook,
    get_seasonal_outlook_summary,
    resolve_district_coordinates,
)


@override_settings(FORECAST_SEASON='2026/2027')
class WeatherDashboardTests(TestCase):
    def make_user(self, username, role, district=''):
        user = User.objects.create_user(username=username, password='test-pass-123')
        user.groups.add(Group.objects.create(name=role))
        if district:
            UserProfile.objects.create(user=user, district=district)
        return user

    def test_ministry_can_view_dashboard_and_choose_a_district(self):
        Farmer.objects.create(
            first_name='Weather', last_name='Kitwe', national_id='WEATHER-KITWE-01',
            district='Kitwe', farm_size_hectares=Decimal('1.00'),
        )
        self.client.force_login(self.make_user('weather-ministry', ROLE_MINISTRY))

        response = self.client.get(reverse('weather_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Weather intelligence')
        self.assertContains(response, 'Kitwe')

    def test_forecast_card_shows_the_condition_icon(self):
        DailyWeather.objects.create(
            district='Ndola', record_type='forecast', date=datetime.now(LOCAL_TIMEZONE).date(),
            temperature_max_c=Decimal('30'), weather_code=61, source=ECMWF_SOURCE,
        )
        self.client.force_login(self.make_user('weather-icons', ROLE_DISTRICT, district='Ndola'))

        response = self.client.get(reverse('weather_dashboard'))

        self.assertContains(response, 'bi-cloud-rain-fill weather-icon')
        self.assertContains(response, 'Light rain')

    def test_district_user_is_limited_to_assigned_district(self):
        self.client.force_login(self.make_user('weather-district', ROLE_DISTRICT, district='Ndola'))

        response = self.client.get(reverse('weather_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_district'], 'Ndola')
        self.assertFalse(response.context['can_select_district'])

    def test_weather_page_exposes_both_ifs_daily_weather_and_seas5_seasonal_outlook(self):
        Farmer.objects.create(
            first_name='Weather', last_name='Kitwe', national_id='WEATHER-KITWE-03',
            district='Kitwe', farm_size_hectares=Decimal('1.00'),
        )
        self.client.force_login(self.make_user('weather-seasonal-only', ROLE_MINISTRY))

        response = self.client.get(reverse('weather_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Refresh SEAS5 seasonal outlook')
        self.assertContains(response, 'Refresh global-model weather')
        self.assertContains(response, 'No daily forecast is cached')

    @patch('weather.views.fetch_district_seasonal_outlook')
    @patch('weather.views.fetch_district_forecast')
    def test_ministry_can_refresh_ifs_and_seas5_separately(self, fetch_forecast, fetch_seasonal):
        Farmer.objects.create(
            first_name='Weather', last_name='Kitwe', national_id='WEATHER-KITWE-02',
            district='Kitwe', farm_size_hectares=Decimal('1.00'),
        )
        fetch_forecast.return_value = {'historical_count': 31, 'forecast_count': 10}
        fetch_seasonal.return_value = {'count': 6}
        self.client.force_login(self.make_user('weather-no-ifs', ROLE_MINISTRY))

        daily_response = self.client.post(reverse('weather_dashboard'), {
            'action': 'refresh_short_range', 'district': 'Kitwe',
        }, follow=True)
        seasonal_response = self.client.post(reverse('weather_dashboard'), {
            'action': 'refresh_seasonal', 'district': 'Kitwe',
        }, follow=True)

        self.assertEqual(daily_response.status_code, 200)
        self.assertEqual(seasonal_response.status_code, 200)
        fetch_forecast.assert_called_once_with('Kitwe')
        fetch_seasonal.assert_called_once_with('Kitwe')

    @patch('weather.views.fetch_district_seasonal_outlook')
    def test_ministry_cannot_submit_an_unknown_district(self, fetch_outlook):
        self.client.force_login(self.make_user('weather-ministry-invalid', ROLE_MINISTRY))

        response = self.client.post(reverse('weather_dashboard'), {
            'action': 'refresh_seasonal', 'district': 'Not a district',
        })

        self.assertRedirects(response, reverse('weather_dashboard'))
        fetch_outlook.assert_not_called()

    @patch('weather.views.fetch_district_seasonal_outlook')
    def test_district_user_cannot_refresh_another_district(self, fetch_outlook):
        fetch_outlook.return_value = {'count': 6}
        self.client.force_login(self.make_user('weather-locked-district', ROLE_DISTRICT, district='Ndola'))

        response = self.client.post(reverse('weather_dashboard'), {
            'action': 'refresh_seasonal', 'district': 'Kitwe',
        })

        self.assertRedirects(response, reverse('weather_dashboard'))
        fetch_outlook.assert_called_once_with('Ndola')


@override_settings(FORECAST_SEASON='2026/2027')
class WeatherServiceValidationTests(TestCase):
    def make_user(self, username, role):
        user = User.objects.create_user(username=username, password='test-pass-123')
        user.groups.add(Group.objects.create(name=role))
        return user

    @staticmethod
    def hourly_payload(days, temperatures_by_model):
        """Build a multi-model Open-Meteo hourly payload: 24 hours per day."""
        hourly = {'time': [f'{day.isoformat()}T{hour:02d}:00' for day in days for hour in range(24)]}
        hours = len(hourly['time'])
        hourly['relative_humidity_2m_ecmwf_ifs'] = [50] * hours
        hourly['rain_ecmwf_ifs'] = [0.25] * hours
        for model, daily_temps in temperatures_by_model.items():
            hourly[f'temperature_2m_{model}'] = [
                value for low, high in daily_temps for value in [low] * 12 + [high] * 12
            ]
        return {'hourly': hourly}

    @patch('weather.services.resolve_district_coordinates', return_value=(-12.8, 28.2))
    @patch('weather.services._request_json')
    def test_global_model_fetch_saves_history_forecast_and_temperature_consensus(self, request_json, _resolve_coordinates):
        today = datetime.now(LOCAL_TIMEZONE).date()
        yesterday = today - timedelta(days=1)
        tomorrow = today + timedelta(days=1)
        request_json.return_value = self.hourly_payload([yesterday, today, tomorrow], {
            'ecmwf_ifs': [(18, 30), (19, 31), (20, 32)],
            'gfs_global': [(16, 34), (17, 35), (18, 36)],
            # ICON's horizon ends early: tomorrow has no values.
            'icon_global': [(17, 32), (18, 33), (None, None)],
        })

        result = fetch_district_forecast('Kitwe')

        self.assertEqual(result['historical_count'], 1)
        self.assertEqual(result['forecast_count'], 2)
        self.assertEqual(result['temperature_models'], ['ECMWF IFS', 'NOAA GFS', 'DWD ICON'])
        historical = DailyWeather.objects.get(district='Kitwe', date=yesterday, record_type='historical')
        self.assertEqual(historical.source, ECMWF_SOURCE)
        self.assertEqual(historical.rainfall_mm, Decimal('6.00'))
        self.assertEqual(historical.temperature_max_c, Decimal('32.00'))
        self.assertEqual(historical.temperature_min_c, Decimal('17.00'))
        self.assertEqual(historical.temperature_model_count, 3)
        forecast = DailyWeather.objects.get(district='Kitwe', date=tomorrow, record_type='forecast')
        self.assertEqual(forecast.temperature_max_c, Decimal('34.00'))
        self.assertEqual(forecast.temperature_model_count, 2)
        self.assertEqual(GlobalModelTemperature.objects.filter(district='Kitwe').count(), 8)
        self.assertEqual(
            GlobalModelTemperature.objects.get(district='Kitwe', date=tomorrow, model='gfs_global').temperature_max_c,
            Decimal('36.00'),
        )
        self.assertEqual(request_json.call_args.args[1]['models'], 'ecmwf_ifs,gfs_global,icon_global')

    @patch('weather.services.resolve_district_coordinates', return_value=(-12.8, 28.2))
    @patch('weather.services._request_json')
    def test_ecmwf_daily_weather_code_is_saved_as_a_condition(self, request_json, _resolve_coordinates):
        today = datetime.now(LOCAL_TIMEZONE).date()
        tomorrow = today + timedelta(days=1)
        payload = self.hourly_payload([today, tomorrow], {'ecmwf_ifs': [(18, 30), (19, 31)]})
        payload['daily'] = {
            'time': [today.isoformat(), tomorrow.isoformat()],
            # 95 is a thunderstorm; 42 is not a WMO code Open-Meteo uses.
            'weather_code_ecmwf_ifs': [95, 42],
            'weather_code_gfs_global': [0, 0],
        }
        request_json.return_value = payload

        fetch_district_forecast('Kitwe')

        self.assertEqual(request_json.call_args.args[1]['daily'], 'weather_code')
        stormy = DailyWeather.objects.get(district='Kitwe', date=today)
        self.assertEqual(stormy.weather_code, 95)
        self.assertEqual(stormy.condition['icon'], 'bi-cloud-lightning-rain-fill')
        self.assertEqual(stormy.condition['label'], 'Thunderstorm')
        self.assertIsNone(DailyWeather.objects.get(district='Kitwe', date=tomorrow).condition)

    @patch('weather.services.resolve_district_coordinates', return_value=(-12.8, 28.2))
    @patch('weather.services._request_json')
    def test_global_model_fetch_requires_ecmwf_rainfall(self, request_json, _resolve_coordinates):
        today = datetime.now(LOCAL_TIMEZONE).date()
        payload = self.hourly_payload([today], {'gfs_global': [(16, 34)]})
        del payload['hourly']['rain_ecmwf_ifs']
        request_json.return_value = payload

        with self.assertRaises(WeatherServiceError):
            fetch_district_forecast('Kitwe')
        self.assertFalse(DailyWeather.objects.exists())

    @patch('weather.services.resolve_district_coordinates', return_value=(-12.9587, 28.6366))
    @patch('weather.services._request_json')
    def test_fetches_and_snapshots_seas5_monthly_rainfall(self, request_json, _resolve_coordinates):
        retrieved = datetime.now(LOCAL_TIMEZONE).date()
        first_month = date(retrieved.year, retrieved.month, 1)
        next_month = date(
            first_month.year + (first_month.month == 12),
            1 if first_month.month == 12 else first_month.month + 1,
            1,
        )
        request_json.return_value = {
            'monthly': {
                'time': [first_month.isoformat(), next_month.isoformat()],
                'precipitation_mean': [155.4, 210.1],
                'precipitation_anomaly': [-19.9, 11.5],
            },
        }

        result = fetch_district_seasonal_outlook('Ndola')

        self.assertEqual(result['count'], 2)
        self.assertEqual(MonthlySeasonalOutlook.objects.filter(district='Ndola').count(), 2)
        first = MonthlySeasonalOutlook.objects.get(district='Ndola', valid_month=first_month)
        self.assertEqual(first.model, 'ecmwf_seas5')
        self.assertEqual(first.source, ECMWF_SEASONAL_SOURCE)
        self.assertEqual(first.precipitation_mean_mm, Decimal('155.40'))
        self.assertEqual(first.precipitation_anomaly_mm, Decimal('-19.90'))
        params = request_json.call_args.args[1]
        self.assertEqual(params['models'], 'ecmwf_seas5')
        self.assertEqual(params['monthly'], 'precipitation_mean,precipitation_anomaly')

    def test_seasonal_summary_uses_latest_october_to_march_snapshot(self):
        retrieved = date(2026, 10, 12)
        for month, anomaly in ((10, -12), (11, 18), (4, 30)):
            year = 2026 if month != 4 else 2027
            MonthlySeasonalOutlook.objects.create(
                district='Kitwe', model='ecmwf_seas5', source=ECMWF_SEASONAL_SOURCE,
                retrieved_date=retrieved, valid_month=date(year, month, 1),
                precipitation_anomaly_mm=Decimal(str(anomaly)),
            )

        summary = get_seasonal_outlook_summary('Kitwe', '2026/2027')

        self.assertEqual(len(summary['months']), 2)
        self.assertIn('Oct: -12.0 mm anomaly', summary['summary'])
        self.assertIn('Nov: +18.0 mm anomaly', summary['summary'])
        self.assertNotIn('Apr:', summary['summary'])
        # No precipitation means were stored, so no season percentage.
        self.assertIsNone(summary['rainfall_anomaly_percent'])

    def test_seasonal_summary_computes_season_rainfall_departure_from_model_normal(self):
        retrieved = date(2026, 10, 12)
        # Forecast 180 + 220 = 400 mm against a model normal of 200 + 250 = 450 mm.
        for month, mean, anomaly in ((11, 180, -20), (12, 220, -30)):
            MonthlySeasonalOutlook.objects.create(
                district='Kitwe', model='ecmwf_seas5', source=ECMWF_SEASONAL_SOURCE,
                retrieved_date=retrieved, valid_month=date(2026, month, 1),
                precipitation_mean_mm=Decimal(mean), precipitation_anomaly_mm=Decimal(anomaly),
            )

        summary = get_seasonal_outlook_summary('Kitwe', '2026/2027')

        self.assertEqual(summary['rainfall_anomaly_percent'], Decimal('-11.1'))
        self.assertEqual(summary['months_with_rainfall'], 2)

    @patch('weather.services.load_zambia_districts', return_value=[
        {'name': 'Kitwe', 'province': 'Copperbelt', 'center_lat': -12.8, 'center_lon': 28.2},
        {'name': 'Lusaka', 'province': 'Lusaka', 'center_lat': -15.4, 'center_lon': 28.3},
    ])
    @patch('weather.services._request_json')
    def test_national_seas5_fetch_batches_district_centres(self, request_json, _districts):
        retrieved = datetime.now(LOCAL_TIMEZONE).date()
        month = date(retrieved.year, retrieved.month, 1)

        def location(mean, anomaly):
            return {'monthly': {
                'time': [month.isoformat()],
                'precipitation_mean': [mean],
                'precipitation_anomaly': [anomaly],
            }}
        request_json.return_value = [location(150, -10), location(90, -30)]

        result = fetch_national_seasonal_outlook()

        self.assertEqual(result['district_count'], 2)
        params = request_json.call_args.args[1]
        self.assertEqual(params['latitude'], '-12.8,-15.4')
        self.assertEqual(params['longitude'], '28.2,28.3')
        self.assertEqual(
            MonthlySeasonalOutlook.objects.get(district='Lusaka').precipitation_anomaly_mm,
            Decimal('-30.00'),
        )

    @patch('weather.services.load_zambia_districts', return_value=[
        {'name': 'Kitwe', 'province': 'Copperbelt', 'center_lat': -12.8, 'center_lon': 28.2},
        {'name': 'Lusaka', 'province': 'Lusaka', 'center_lat': -15.4, 'center_lon': 28.3},
    ])
    @patch('weather.services._request_json')
    def test_national_seas5_fetch_rejects_missing_locations(self, request_json, _districts):
        request_json.return_value = {'monthly': {'time': [], 'precipitation_mean': [], 'precipitation_anomaly': []}}

        with self.assertRaises(WeatherServiceError):
            fetch_national_seasonal_outlook()
        self.assertFalse(MonthlySeasonalOutlook.objects.exists())

    def test_map_data_uses_each_districts_latest_seas5_snapshot(self):
        for retrieved, mean, anomaly in ((date(2026, 9, 5), 100, 50), (date(2026, 10, 12), 180, -20)):
            MonthlySeasonalOutlook.objects.create(
                district='Kitwe', model='ecmwf_seas5', source=ECMWF_SEASONAL_SOURCE,
                retrieved_date=retrieved, valid_month=date(2026, 11, 1),
                precipitation_mean_mm=Decimal(mean), precipitation_anomaly_mm=Decimal(anomaly),
            )
        self.client.force_login(self.make_user('map-ministry', ROLE_MINISTRY))

        response = self.client.get(reverse('weather_dashboard'))

        kitwe = response.context['seasonal_map']['seas5']['Kitwe']
        self.assertEqual(kitwe['retrieved'], '2026-10-12')
        self.assertEqual(len(kitwe['months']), 1)
        self.assertEqual(kitwe['months'][0]['normal_mm'], 200.0)
        self.assertEqual(kitwe['departure_percent'], -10.0)
        self.assertEqual(kitwe['category'], 'normal_below')
        self.assertContains(response, 'id="zambia-map"')
        self.assertContains(response, 'Refresh SEAS5 for all districts')

    @patch('weather.views.build_seas5_field')
    @patch('weather.views.fetch_national_seasonal_outlook')
    def test_only_ministry_can_refresh_national_seas5(self, fetch_national, build_field):
        user = self.make_user('map-district', ROLE_DISTRICT)
        UserProfile.objects.create(user=user, district='Ndola')
        self.client.force_login(user)

        response = self.client.post(reverse('weather_dashboard'), {'action': 'refresh_seasonal_national'}, follow=True)

        fetch_national.assert_not_called()
        build_field.assert_not_called()
        self.assertContains(response, 'Only Ministry users can refresh the national seasonal outlook.')
        self.assertNotContains(response, 'value="refresh_seasonal_national"')

    @patch('weather.views.fetch_district_seasonal_outlook')
    def test_ministry_can_refresh_seasonal_outlook_for_selected_district(self, fetch_outlook):
        Farmer.objects.create(
            first_name='Weather', last_name='Ndola', national_id='WEATHER-NDOLA-02',
            district='Ndola', farm_size_hectares=Decimal('1.00'),
        )
        fetch_outlook.return_value = {'count': 6}
        self.client.force_login(self.make_user('seasonal-ministry', ROLE_MINISTRY))

        response = self.client.post(reverse('weather_dashboard'), {
            'action': 'refresh_seasonal', 'district': 'Ndola',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        fetch_outlook.assert_called_once_with('Ndola')
        self.assertContains(response, 'ECMWF SEAS5')

class Seas5FieldTests(SimpleTestCase):
    def test_field_is_smooth_masked_to_zambia_and_tiled(self):
        # A west-to-east gradient from -20% to +20% on the 0.5 degree sample grid.
        lat = np.arange(seas5_field.LAT_MIN + 0.1, seas5_field.LAT_MAX, seas5_field.GRID_STEP)
        lon = np.arange(seas5_field.LON_MIN, seas5_field.LON_MAX, seas5_field.GRID_STEP)
        departures = np.tile(np.linspace(-20, 20, len(lon)), (len(lat), 1))
        departures[0, 0] = np.nan  # a missing grid point is filled, not propagated

        field = seas5_field.render_seas5_field(lat, lon, departures)

        inside = np.isfinite(field)
        self.assertTrue(inside.any())
        self.assertFalse(inside.all())  # DRC pedicle and neighbours are transparent
        self.assertGreaterEqual(np.nanmin(field), -20.5)
        self.assertLessEqual(np.nanmax(field), 20.5)
        # Smooth: neighbouring fine cells differ by a small fraction of a percent.
        self.assertLess(np.nanmax(np.abs(np.diff(field, axis=1))), 0.5)

        with tempfile.TemporaryDirectory() as tmp:
            tiles_dir = Path(tmp) / 'seas5'
            count = rasters.tile_grid(
                field, seas5_field.BOUNDS, ramp=seas5_field.SEAS5_RAMP, tiles_dir=tiles_dir, zooms=range(5, 6),
            )
            self.assertEqual(count, len(list(tiles_dir.rglob('*.png'))))
            self.assertFalse(Path(tmp, 'seas5.building').exists())


class DistrictLocationTests(TestCase):
    def test_district_without_farmer_gps_uses_its_boundary_centre(self):
        with patch('weather.services._request_json') as request_json:
            latitude, longitude = resolve_district_coordinates('Mungwi')
        request_json.assert_not_called()  # no geocoding needed for a known district
        self.assertTrue(-11.5 < latitude < -9.5 and 30.5 < longitude < 32.5)
