from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Sum
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from accounts.decorators import ROLE_MINISTRY
from farmers.models import Farmer, FarmerInputUsage
from .models import Forecast, NationalInputSeries
from .climate import (
	get_seas5_demand_adjustment,
	get_weather_demand_adjustment,
	scale_adjustment_for_input,
	seas5_rainfall_category,
	season_slug,
	target_rainfall_season,
)
from .services import _next_season, build_time_series, forecast_district_input, import_demand_file
from .services import ensure_national_backtest, run_all_forecasts
from . import backtest
from weather.models import DailyWeather
from weather.services import ECMWF_SOURCE


@override_settings(FORECAST_SEASON='2026/2027')
class DemandImportTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(username='ministry-test', password='test-pass-123')
		self.user.groups.add(Group.objects.create(name=ROLE_MINISTRY))
		self.farmer = Farmer.objects.create(
			first_name='Test',
			last_name='Farmer',
			national_id='IMPORT-001',
			district='Ndola',
			farm_size_hectares=2,
		)

	def upload(self, content, filename='demand.csv'):
		self.client.force_login(self.user)
		return self.client.post(
			reverse('upload_demand_data'),
			{'demand_file': SimpleUploadedFile(filename, content.encode(), content_type='text/csv')},
		)

	def test_ministry_can_import_valid_csv(self):
		content = '\n'.join([
			'national_id,season,input_type,quantity_kg',
			'IMPORT-001,2017/2018,fertilizer_d,100',
			'IMPORT-001,2018/2019,fertilizer_d,110',
			'IMPORT-001,2019/2020,fertilizer_d,120',
			'IMPORT-001,2020/2021,fertilizer_d,130',
		])

		response = self.upload(content)

		self.assertEqual(response.status_code, 302)
		self.assertEqual(FarmerInputUsage.objects.count(), 4)
		imported_record = FarmerInputUsage.objects.get(season='2017/2018')
		self.assertEqual(imported_record.quantity_kg, 100)

	def test_invalid_upload_does_not_create_partial_records(self):
		content = '\n'.join([
			'national_id,season,input_type,quantity_kg',
			'IMPORT-001,2017/2018,fertilizer_d,100',
			'UNKNOWN,2018/2019,fertilizer_d,110',
		])

		response = self.upload(content)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(FarmerInputUsage.objects.count(), 0)
		self.assertContains(response, 'Unknown farmer national ID')

	def test_event_csv_import_accepts_repeated_combinations_and_is_idempotent(self):
		content = '\n'.join([
			'usage_event_id,national_id,season,input_type,quantity_kg',
			'EVT-001,IMPORT-001,2017/2018,fertilizer_d,12.50',
			'EVT-002,IMPORT-001,2017/2018,fertilizer_d,7.25',
		])

		first_import = import_demand_file(SimpleUploadedFile('events.csv', content.encode()))
		second_import = import_demand_file(SimpleUploadedFile('events.csv', content.encode()))

		self.assertEqual(first_import, 2)
		self.assertEqual(second_import, 0)
		self.assertEqual(FarmerInputUsage.objects.count(), 2)
		self.assertEqual(
			FarmerInputUsage.objects.filter(farmer=self.farmer).aggregate(total=Sum('quantity_kg'))['total'],
			Decimal('19.75'),
		)

	def test_event_import_rejects_reused_id_with_conflicting_data(self):
		first = 'usage_event_id,national_id,season,input_type,quantity_kg\nEVT-CONFLICT,IMPORT-001,2017/2018,fertilizer_d,12.50'
		conflict = 'usage_event_id,national_id,season,input_type,quantity_kg\nEVT-CONFLICT,IMPORT-001,2017/2018,fertilizer_d,99.00'
		import_demand_file(SimpleUploadedFile('first.csv', first.encode()))

		with self.assertRaises(ValidationError):
			import_demand_file(SimpleUploadedFile('conflict.csv', conflict.encode()))

		self.assertEqual(FarmerInputUsage.objects.count(), 1)
		self.assertEqual(FarmerInputUsage.objects.get().quantity_kg, Decimal('12.50'))

	def test_non_ministry_cannot_upload_demand(self):
		user = User.objects.create_user(username='district-test', password='test-pass-123')
		self.client.force_login(user)

		response = self.client.post(reverse('upload_demand_data'))

		self.assertEqual(response.status_code, 403)

	def test_arima_prediction_is_saved(self):
		for season, quantity in zip(
			['2017/2018', '2018/2019', '2019/2020', '2020/2021'],
			[100, 110, 125, 140],
		):
			FarmerInputUsage.objects.create(
				farmer=self.farmer,
				season=season,
				input_type='fertilizer_d',
				quantity_kg=quantity,
			)

		forecast = forecast_district_input('Ndola', 'fertilizer_d')

		self.assertIsNotNone(forecast)
		self.assertEqual(forecast.forecast_season, '2021/2022')
		self.assertEqual(forecast.seasons_used, 4)
		self.assertEqual(forecast.model_used, 'ARIMA(1,1,1)')
		self.assertTrue(Forecast.objects.filter(pk=forecast.pk).exists())

	def test_new_seed_types_import_and_forecast(self):
		seasons = ['2017/2018', '2018/2019', '2019/2020', '2020/2021']
		input_types = ['seed_soybeans', 'seed_sunflower', 'seed_popcorn']
		rows = ['national_id,season,input_type,quantity_kg']
		for type_index, input_type in enumerate(input_types):
			for season_index, season in enumerate(seasons):
				quantity = 100 + type_index * 20 + season_index * 10
				rows.append(f'{self.farmer.national_id},{season},{input_type},{quantity}')

		response = self.upload('\n'.join(rows))

		self.assertEqual(response.status_code, 302)
		self.assertEqual(FarmerInputUsage.objects.count(), 12)
		for input_type in input_types:
			forecast = forecast_district_input('Ndola', input_type)
			self.assertIsNotNone(forecast)
			self.assertEqual(forecast.model_used, 'ARIMA(1,1,1)')

	def test_copperbelt_zmd_outlook_uses_conservative_weighted_adjustment(self):
		# Kitwe's majority ZMD zones (ZEWCO 2026/27 consensus zones): Normal to
		# Below for OND, NDJ and DJF, Below for JFM.
		outlook = get_weather_demand_adjustment('Kitwe', '2026/2027')

		self.assertEqual(outlook['adjustment_percent'], Decimal('-3.13'))
		self.assertIn('DJF: Normal to Below Normal', outlook['summary'])
		self.assertIn('JFM: Below Normal', outlook['summary'])
		self.assertEqual(outlook['source'], 'ZMD outlook')
		self.assertIsNone(get_weather_demand_adjustment('Unmapped District', '2026/2027'))

	def test_zmd_outlook_covers_districts_beyond_the_copperbelt(self):
		# Lusaka sits in the Below Normal zone for all four periods.
		self.assertEqual(get_weather_demand_adjustment('Lusaka', '2026/2027')['adjustment_percent'], Decimal('-5.00'))

	def test_target_season_forecast_stores_baseline_and_weather_adjustment(self):
		for season, quantity in zip(
			['2017/2018', '2018/2019', '2019/2020', '2020/2021'],
			[100, 110, 125, 140],
		):
			FarmerInputUsage.objects.create(
				farmer=self.farmer,
				season=season,
				input_type='fertilizer_d',
				quantity_kg=quantity,
			)

		forecast = forecast_district_input(
			'Ndola',
			'fertilizer_d',
			forecast_season='2026/2027',
			weather_adjustment_percent=Decimal('-3.13'),
			weather_summary='DJF: Below Normal',
		)

		self.assertEqual(forecast.forecast_season, '2026/2027')
		self.assertEqual(forecast.weather_adjustment_percent, Decimal('-3.13'))
		self.assertEqual(forecast.predicted_quantity_kg, forecast.baseline_predicted_quantity_kg)
		self.assertEqual(forecast.allocation_quantity_kg, forecast.baseline_predicted_quantity_kg)
		self.assertEqual(forecast.weather_scenario_quantity_kg, (forecast.baseline_predicted_quantity_kg * Decimal('0.9687')).quantize(Decimal('0.01')))
		self.assertEqual(forecast.weather_summary, 'DJF: Below Normal')
		self.assertIn('weather scenario', forecast.model_used)

	def test_seas5_context_is_saved_without_changing_baseline_allocation(self):
		for season, quantity in zip(
			['2017/2018', '2018/2019', '2019/2020', '2020/2021'],
			[100, 110, 125, 140],
		):
			FarmerInputUsage.objects.create(
				farmer=self.farmer,
				season=season,
				input_type='fertilizer_d',
				quantity_kg=quantity,
			)

		forecast = forecast_district_input(
			'Ndola',
			'fertilizer_d',
			forecast_season='2026/2027',
			weather_adjustment_percent=Decimal('-3.13'),
			weather_summary='ZMD outlook scenario',
			seasonal_weather_summary='Oct: -12.0 mm anomaly; Nov: +18.0 mm anomaly',
			seasonal_weather_retrieved_date=timezone.localdate(),
		)

		forecast.refresh_from_db()
		self.assertEqual(forecast.predicted_quantity_kg, forecast.baseline_predicted_quantity_kg)
		self.assertEqual(forecast.allocation_quantity_kg, forecast.baseline_predicted_quantity_kg)
		self.assertNotEqual(forecast.weather_scenario_quantity_kg, forecast.allocation_quantity_kg)
		self.assertIn('Oct:', forecast.seasonal_weather_summary)
		self.assertEqual(forecast.seasonal_weather_retrieved_date, timezone.localdate())

	def test_full_forecast_run_attaches_seas5_but_keeps_allocation_on_arima_baseline(self):
		for season, quantity in zip(
			['2017/2018', '2018/2019', '2019/2020', '2020/2021'],
			[100, 110, 125, 140],
		):
			FarmerInputUsage.objects.create(
				farmer=self.farmer,
				season=season,
				input_type='fertilizer_d',
				quantity_kg=quantity,
			)
		from weather.models import MonthlySeasonalOutlook
		MonthlySeasonalOutlook.objects.create(
			district='Ndola', model='ecmwf_seas5', retrieved_date=timezone.localdate(),
			valid_month=date(2026, 10, 1),
			precipitation_mean_mm=Decimal('155.4'),
			precipitation_anomaly_mm=Decimal('-19.9'),
		)

		result = run_all_forecasts(forecast_season='2026/2027')
		forecast = result['succeeded'][0]

		self.assertEqual(len(result['succeeded']), 1)
		self.assertEqual(forecast.predicted_quantity_kg, forecast.baseline_predicted_quantity_kg)
		self.assertEqual(forecast.allocation_quantity_kg, forecast.baseline_predicted_quantity_kg)
		self.assertNotEqual(forecast.weather_scenario_quantity_kg, forecast.allocation_quantity_kg)
		self.assertIn('Oct:', forecast.seasonal_weather_summary)
		# Oct SEAS5: 155.4 mm vs a 175.3 mm model normal = -11.4%, Normal to Below Normal.
		self.assertEqual(forecast.seas5_adjustment_percent, Decimal('-2.50'))
		self.assertIn('SEAS5', forecast.seas5_summary)
		self.assertEqual(
			forecast.seas5_scenario_quantity_kg,
			(forecast.baseline_predicted_quantity_kg * Decimal('0.975')).quantize(Decimal('0.01')),
		)
		# The ZMD scenario is stored independently alongside SEAS5.
		self.assertEqual(forecast.weather_adjustment_percent, Decimal('-3.13'))
		self.assertIn('DJF: Normal to Below Normal', forecast.weather_summary)

	def test_seas5_rainfall_categories_and_input_sensitivity(self):
		cases = [
			(Decimal('-20.0'), 'below'),
			(Decimal('-15.0'), 'normal_below'),
			(Decimal('-5.1'), 'normal_below'),
			(Decimal('0.0'), 'normal'),
			(Decimal('5.0'), 'normal_above'),
			(Decimal('15.0'), 'above'),
		]
		for anomaly, category in cases:
			with self.subTest(anomaly=anomaly):
				self.assertEqual(seas5_rainfall_category(anomaly), category)

		adjustment = get_seas5_demand_adjustment({'rainfall_anomaly_percent': Decimal('-18.0'), 'months_with_rainfall': 6})
		self.assertEqual(adjustment['adjustment_percent'], Decimal('-5.00'))
		self.assertEqual(scale_adjustment_for_input(adjustment, 'fertilizer_urea')['adjustment_percent'], Decimal('-6.00'))
		self.assertEqual(scale_adjustment_for_input(adjustment, 'seed_sunflower')['adjustment_percent'], Decimal('-2.50'))
		self.assertIn('x0.5', scale_adjustment_for_input(adjustment, 'seed_sunflower')['summary'])
		self.assertIsNone(get_seas5_demand_adjustment({'rainfall_anomaly_percent': None}))

	def test_full_forecast_run_without_seas5_leaves_seas5_blank_and_keeps_zmd(self):
		for season, quantity in zip(
			['2017/2018', '2018/2019', '2019/2020', '2020/2021'],
			[100, 110, 125, 140],
		):
			FarmerInputUsage.objects.create(
				farmer=self.farmer,
				season=season,
				input_type='fertilizer_urea',
				quantity_kg=quantity,
			)

		result = run_all_forecasts(forecast_season='2026/2027')
		forecast = result['succeeded'][0]

		self.assertEqual(result['missing_seasonal_outlook'], ['Ndola'])
		self.assertEqual(result['missing_zmd_outlook'], [])
		# No fallback: the SEAS5 scenario stays empty rather than copying ZMD.
		self.assertIsNone(forecast.seas5_adjustment_percent)
		self.assertIsNone(forecast.seas5_scenario_quantity_kg)
		self.assertEqual(forecast.seas5_summary, '')
		# ZMD Ndola average is -3.13%, scaled by urea's x1.2 sensitivity.
		self.assertEqual(forecast.weather_adjustment_percent, Decimal('-3.76'))

	def test_forecast_page_switches_between_zmd_and_seas5_scenarios(self):
		Forecast.objects.create(
			district='Ndola', input_type='fertilizer_d', forecast_season='2026/2027',
			predicted_quantity_kg=Decimal('100.00'), baseline_predicted_quantity_kg=Decimal('100.00'),
			weather_scenario_quantity_kg=Decimal('96.87'), weather_adjustment_percent=Decimal('-3.13'),
			weather_summary='DJF: Normal to Below Normal',
			seas5_scenario_quantity_kg=Decimal('97.50'), seas5_adjustment_percent=Decimal('-2.50'),
			seas5_summary='SEAS5 Oct-Mar rainfall -7.3% vs model normal', seasons_used=4,
		)
		self.client.force_login(self.user)

		response = self.client.get(reverse('forecast_list'))
		self.assertEqual(response.context['scenario'], 'zmd')
		self.assertContains(response, '96.87')
		self.assertContains(response, '97.50')
		self.assertContains(response, 'id="scenario-seas5"')

		response = self.client.get(reverse('forecast_list'), {'scenario': 'seas5'})
		self.assertEqual(response.context['scenario'], 'seas5')
		response = self.client.get(reverse('forecast_list'), {'scenario': 'bogus'})
		self.assertEqual(response.context['scenario'], 'zmd')

	def test_forecast_page_shows_ifs_daily_rainfall_as_separate_context(self):
		forecast = Forecast.objects.create(
			district='Ndola', input_type='fertilizer_d', forecast_season='2026/2027',
			predicted_quantity_kg=Decimal('100.00'), baseline_predicted_quantity_kg=Decimal('100.00'),
			weather_scenario_quantity_kg=Decimal('96.87'), weather_adjustment_percent=Decimal('-3.13'),
			weather_summary='ZMD categories', seasons_used=4,
		)
		DailyWeather.objects.create(
			district='Ndola', record_type='forecast', date=timezone.localdate(),
			rainfall_mm=Decimal('4.20'), source=ECMWF_SOURCE,
		)
		self.client.force_login(self.user)

		response = self.client.get(reverse('forecast_list'))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context['forecast_rows'][0]['forecast'], forecast)
		self.assertContains(response, 'ECMWF IFS Rain Next 10 Days')
		self.assertContains(response, '4.2 mm')
		self.assertContains(response, 'Allocation safeguard')

	def test_forecast_page_bad_upload_renders_without_error_when_no_forecasts_exist(self):
		self.client.force_login(self.user)

		response = self.client.post(reverse('upload_demand_data'), {
			'demand_file': SimpleUploadedFile('bad.csv', b'not,a,valid,header', content_type='text/csv'),
		})

		self.assertEqual(response.status_code, 200)

	@patch('forecasting.views.run_all_forecasts', return_value={
		'succeeded': [], 'skipped': [], 'unmapped': [],
	})
	def test_run_forecast_action_targets_2026_2027(self, run_forecasts):
		FarmerInputUsage.objects.create(
			farmer=self.farmer,
			season='2024/2025',
			input_type='fertilizer_d',
			quantity_kg=Decimal('100.00'),
		)
		self.client.force_login(self.user)

		response = self.client.post(reverse('run_forecast'))

		self.assertRedirects(response, reverse('forecast_list'))
		run_forecasts.assert_called_once_with(forecast_season='2026/2027')

	@patch('forecasting.views.run_all_forecasts')
	def test_run_forecast_explains_when_usage_csv_has_not_been_imported(self, run_forecasts):
		self.client.force_login(self.user)

		response = self.client.post(reverse('run_forecast'), follow=True)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'No historical input-usage records are loaded')
		run_forecasts.assert_not_called()


class SeasonHandlingTests(SimpleTestCase):
	def test_planning_season_rolls_over_in_july(self):
		self.assertEqual(target_rainfall_season(date(2026, 6, 30)), '2025/2026')
		self.assertEqual(target_rainfall_season(date(2026, 7, 1)), '2026/2027')
		self.assertEqual(target_rainfall_season(date(2031, 11, 5)), '2031/2032')
		with self.settings(FORECAST_SEASON='2029/2030'):
			self.assertEqual(target_rainfall_season(date(2026, 10, 1)), '2029/2030')

	def test_seasons_beyond_any_fixed_list_are_handled(self):
		self.assertEqual(_next_season('2031/2032'), '2032/2033')
		self.assertEqual(season_slug('2031/2032'), '2031_32')
		self.assertEqual(_next_season('not a season'), 'not a season + 1')

	def test_zmd_outlook_is_only_used_for_its_own_season(self):
		self.assertIsNotNone(get_weather_demand_adjustment('Kitwe', '2026/2027'))
		self.assertIsNone(get_weather_demand_adjustment('Kitwe', '2027/2028'))


class LongHistoryTests(TestCase):
	def test_usage_after_2027_is_part_of_the_time_series(self):
		farmer = Farmer.objects.create(
			first_name='Later', last_name='Seasons', national_id='LATER-01',
			district='Ndola', farm_size_hectares=Decimal('1.00'),
		)
		for season in ['2028/2029', '2027/2028', '2029/2030', '2030/2031', 'bad label']:
			FarmerInputUsage.objects.create(
				farmer=farmer, season=season, input_type='fertilizer_d', quantity_kg=Decimal('10.00'),
			)

		series = build_time_series('Ndola', 'fertilizer_d')

		self.assertEqual(list(series.index), ['2027/2028', '2028/2029', '2029/2030', '2030/2031'])


class NationalTrendTests(TestCase):
	def setUp(self):
		self.farmer = Farmer.objects.create(
			first_name='Survey', last_name='One', national_id='SURVEY-01',
			district='Choma', farm_size_hectares=Decimal('3.00'),
		)
		FarmerInputUsage.objects.create(
			farmer=self.farmer, season='2021/2022', input_type='fertilizer_urea', quantity_kg=Decimal('200.00'),
		)

	def add_national(self, values):
		for start, value in enumerate(values, start=2016):
			NationalInputSeries.objects.create(
				input_type='fertilizer_urea', season=f'{start}/{start + 1}', value=value, unit='t', source='test',
			)

	def test_single_season_district_is_scaled_by_national_arima_forecast(self):
		self.add_national([100, 110, 120, 130, 140, 150, 160, 170, 180])

		forecast = forecast_district_input('Choma', 'fertilizer_urea', forecast_season='2026/2027')

		self.assertIsNotNone(forecast)
		self.assertEqual(forecast.model_used, 'ARIMA(1,1,1) national trend')
		self.assertEqual(forecast.seasons_used, 9)
		# 2021/2022 national value is 150; a steady +10 trend reaches ~200 by 2026/2027.
		self.assertAlmostEqual(float(forecast.baseline_predicted_quantity_kg), 200 * 200 / 150, delta=10)

	def test_single_season_district_without_national_series_is_skipped(self):
		self.assertIsNone(forecast_district_input('Choma', 'fertilizer_urea', forecast_season='2026/2027'))

	def test_national_series_must_cover_the_district_season(self):
		NationalInputSeries.objects.create(
			input_type='fertilizer_urea', season='2010/2011', value=1, unit='t', source='test',
		)
		self.add_national([100, 110, 120, 130])  # 2016/2017 to 2019/2020, before the survey season

		self.assertIsNone(forecast_district_input('Choma', 'fertilizer_urea', forecast_season='2026/2027'))


class RealDatasetImportTests(TestCase):
	def test_faostat_import_maps_series_to_input_types_and_seasons(self):
		call_command('import_faostat_series', stdout=StringIO())

		urea = NationalInputSeries.objects.get(input_type='fertilizer_urea', season='2021/2022')
		seed = NationalInputSeries.objects.get(input_type='seed_maize', season='2021/2022')
		self.assertEqual(urea.unit, 't')
		self.assertEqual(urea.value, Decimal('178634.00'))  # FAOSTAT N use, 2021
		self.assertEqual(seed.unit, 'ha')
		self.assertEqual(seed.value, Decimal('1115489.00'))  # maize area harvested, 2022
		self.assertGreaterEqual(NationalInputSeries.objects.filter(input_type='fertilizer_d').count(), 60)

	def test_fisp_survey_import_is_idempotent_and_splits_fertilizer(self):
		call_command('import_fisp_survey', stdout=StringIO())
		call_command('import_fisp_survey', stdout=StringIO())

		self.assertEqual(Farmer.objects.filter(national_id__startswith='FISP-SP-').count(), 340)
		self.assertEqual(
			set(Farmer.objects.values_list('district', flat=True)), {'Choma', 'Kalomo', 'Monze', 'Pemba'},
		)
		usage = FarmerInputUsage.objects.filter(season='2021/2022')
		self.assertEqual(usage.count(), 340 * 3)
		totals = dict(usage.values_list('input_type').annotate(total=Sum('quantity_kg')))
		self.assertEqual(totals['fertilizer_d'], totals['fertilizer_urea'])
		self.assertEqual(totals['fertilizer_d'] + totals['fertilizer_urea'], Decimal('103579.00'))
		self.assertEqual(totals['seed_maize'], Decimal('12325.00'))


@patch('forecasting.backtest.AUTO_TRENDS', ('t',))
@patch('forecasting.backtest.AUTO_ORDERS', [(0, 1, 0)])
class BacktestTests(TestCase):
	def growth_series(self, count=30):
		# Steady 8% growth a season, the shape log-ARIMA with drift captures exactly.
		return [f'{1990 + i}/{1991 + i}' for i in range(count)], [1000 * 1.08 ** i for i in range(count)]

	def test_backtest_scores_methods_on_seasons_not_used_for_choosing(self):
		seasons, values = self.growth_series()

		result = backtest.evaluate(seasons, values, steps=2)

		self.assertEqual(result['chosen_method'], 'auto')
		self.assertLess(result['test_mape']['auto'], 1)
		self.assertLess(result['test_mape']['auto'], result['test_mape']['naive'])
		# Six test seasons, ending with the latest one.
		self.assertEqual(result['last_test_season'], seasons[-1])
		self.assertEqual(result['first_test_season'], seasons[-6])

	def test_short_series_cannot_be_backtested(self):
		self.assertFalse(backtest.can_backtest(9, 2))
		self.assertTrue(backtest.can_backtest(30, 2))

	def test_stored_backtest_is_reused_until_the_series_changes(self):
		seasons, values = self.growth_series()
		for season, value in zip(seasons, values):
			NationalInputSeries.objects.create(
				input_type='fertilizer_urea', season=season, value=Decimal(str(round(value, 2))),
				unit='t', source='test',
			)

		with patch('forecasting.backtest.evaluate', wraps=backtest.evaluate) as evaluate:
			first = ensure_national_backtest('fertilizer_urea', '2021/2022')
			second = ensure_national_backtest('fertilizer_urea', '2021/2022')
			self.assertEqual(evaluate.call_count, 1)
			NationalInputSeries.objects.filter(season='2019/2020').update(value=Decimal('1.00'))
			ensure_national_backtest('fertilizer_urea', '2021/2022')
			self.assertEqual(evaluate.call_count, 2)
		self.assertEqual(first.pk, second.pk)
		self.assertEqual(first.chosen_method, 'auto')

	def test_survey_district_uses_the_backtested_model_and_page_shows_backtest(self):
		seasons, values = self.growth_series(33)  # 1990/1991 to 2022/2023
		for season, value in zip(seasons, values):
			NationalInputSeries.objects.create(
				input_type='fertilizer_urea', season=season, value=Decimal(str(round(value, 2))),
				unit='t', source='FAOSTAT test series',
			)
		farmer = Farmer.objects.create(
			first_name='Survey', last_name='Two', national_id='SURVEY-02',
			district='Choma', farm_size_hectares=Decimal('3.00'),
		)
		FarmerInputUsage.objects.create(
			farmer=farmer, season='2021/2022', input_type='fertilizer_urea', quantity_kg=Decimal('100.00'),
		)

		forecast = forecast_district_input('Choma', 'fertilizer_urea', forecast_season='2026/2027')

		self.assertEqual(forecast.model_used, 'log-ARIMA(0,1,0)+drift national trend')
		# 1.08 growth from 2021/2022 to 2026/2027 is five seasons.
		self.assertAlmostEqual(float(forecast.baseline_predicted_quantity_kg), 100 * 1.08 ** 5, delta=1)

		user = User.objects.create_user(username='ministry-backtest', password='test-pass-123')
		user.groups.add(Group.objects.create(name=ROLE_MINISTRY))
		self.client.force_login(user)
		with override_settings(FORECAST_SEASON='2026/2027'):
			response = self.client.get(reverse('forecast_list'))
		self.assertContains(response, 'forecast-backtest')
		self.assertContains(response, 'FAOSTAT test series')
