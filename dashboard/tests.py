from django.test import TestCase
from django.contrib.auth.models import Group, User
from django.urls import reverse
from decimal import Decimal

from accounts.decorators import ROLE_DEALER, ROLE_MINISTRY
from farmers.models import Farmer
from forecasting.models import Forecast
from inventory.models import DealerStockReceipt, SupplierDispatch
from logistics.models import AgroDealer, Supplier


class DashboardKpiTests(TestCase):
	def test_forecast_kpi_uses_arima_baseline_not_weather_scenario(self):
		user = User.objects.create_user(username='dashboard-forecast-user', password='test-password')
		user.groups.add(Group.objects.create(name=ROLE_MINISTRY))
		Forecast.objects.create(
			district='Kitwe', input_type='fertilizer_d', forecast_season='2026/2027',
			predicted_quantity_kg=Decimal('90.00'),
			baseline_predicted_quantity_kg=Decimal('100.00'),
			weather_scenario_quantity_kg=Decimal('90.00'),
			weather_adjustment_percent=Decimal('-10.00'), seasons_used=4,
		)
		self.client.force_login(user)

		response = self.client.get(reverse('dashboard_home'))

		self.assertEqual(response.context['kpis']['forecast_demand_kg'], Decimal('100.00'))

	def test_dashboard_empty_state_is_safe(self):
		user = User.objects.create_user(username='dashboard-user', password='test-password')
		user.groups.add(Group.objects.create(name=ROLE_MINISTRY))
		self.client.force_login(user)

		response = self.client.get(reverse('dashboard_home'))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context['kpis']['registered_farmers'], 0)
		self.assertEqual(response.context['kpis']['forecast_demand_kg'], 0)
		self.assertEqual(response.context['kpis']['active_suppliers'], 0)
		self.assertEqual(response.context['kpis']['total_available_stock_kg'], 0)

	def test_dashboard_counts_network_entities(self):
		user = User.objects.create_user(username='dashboard-user', password='test-password')
		user.groups.add(Group.objects.create(name=ROLE_MINISTRY))
		supplier = Supplier.objects.create(
			name='Test Supplier', district='Kitwe', latitude=-12.8,
			longitude=28.2, current_stock_kg=250,
			stock_fertilizer_d_kg=250,
			is_active=True,
		)
		Farmer.objects.create(
			first_name='Test', last_name='Farmer', national_id='D001',
			district='Kitwe', farm_size_hectares=1, latitude=-12.8, longitude=28.2,
		)
		first_dealer = AgroDealer.objects.create(
			name='Test Dealer', district='Kitwe', latitude=-12.81, longitude=28.21,
			stock_quantity_kg=Decimal('10'),
			stock_fertilizer_d_kg=10,
			stock_fertilizer_urea_kg=2,
			stock_seed_maize_kg=3,
			stock_seed_other_kg=5,
		)
		second_dealer = AgroDealer.objects.create(
			name='Second Dealer', district='Ndola', latitude=-12.92, longitude=28.62,
			stock_quantity_kg=Decimal('14'),
			stock_fertilizer_d_kg=1,
			stock_fertilizer_urea_kg=1,
			stock_seed_maize_kg=1,
			stock_seed_other_kg=1,
		)
		first_dispatch = SupplierDispatch.objects.create(
			supplier=supplier,
			agro_dealer=first_dealer,
			input_type='fertilizer_d',
			quantity_kg=Decimal('10'),
			dispatched_by=user,
		)
		second_dispatch = SupplierDispatch.objects.create(
			supplier=supplier,
			agro_dealer=second_dealer,
			input_type='fertilizer_d',
			quantity_kg=Decimal('14'),
			dispatched_by=user,
		)
		DealerStockReceipt.objects.create(dispatch=first_dispatch, quantity_kg=Decimal('10'), received_by=user)
		DealerStockReceipt.objects.create(dispatch=second_dispatch, quantity_kg=Decimal('14'), received_by=user)
		self.client.force_login(user)

		response = self.client.get(reverse('dashboard_home'))

		self.assertEqual(response.context['kpis']['registered_farmers'], 1)
		self.assertEqual(response.context['kpis']['active_suppliers'], 1)
		self.assertEqual(response.context['kpis']['total_available_stock_kg'], Decimal('24'))
		self.assertContains(response, 'Total Available Stock')
		self.assertContains(response, 'Current dealer stock after confirmed collections')
		self.assertEqual(response.context['kpis']['agro_dealers'], 2)

	def test_dashboard_available_stock_is_zero_before_dealer_receipt(self):
		user = User.objects.create_user(username='warehouse-stock-user', password='test-password')
		user.groups.add(Group.objects.create(name=ROLE_MINISTRY))
		Supplier.objects.create(
			name='Stocked Supplier', district='Kitwe', latitude=-12.8,
			longitude=28.2, current_stock_kg=500,
			stock_fertilizer_d_kg=500, is_active=True,
		)
		AgroDealer.objects.create(
			name='Not Yet Collected Dealer', district='Kitwe',
			latitude=-12.81, longitude=28.21,
		)
		self.client.force_login(user)

		response = self.client.get(reverse('dashboard_home'))

		self.assertEqual(response.context['kpis']['total_available_stock_kg'], 0)

	def test_dashboard_ignores_stale_dealer_stock_without_confirmed_receipt(self):
		user = User.objects.create_user(username='dashboard-stale-stock-user', password='test-password')
		user.groups.add(Group.objects.create(name=ROLE_MINISTRY))
		AgroDealer.objects.create(
			name='Stale Dealer', district='Kitwe', latitude=-12.81, longitude=28.21,
			stock_quantity_kg=1500,
			stock_fertilizer_d_kg=1500,
		)
		self.client.force_login(user)

		response = self.client.get(reverse('dashboard_home'))

		self.assertEqual(response.context['kpis']['total_available_stock_kg'], 0)

	def test_dashboard_total_increases_after_dealer_records_collection(self):
		ministry_user = User.objects.create_user(username='stock-ministry', password='test-password')
		ministry_user.groups.add(Group.objects.create(name=ROLE_MINISTRY))
		dealer_user = User.objects.create_user(username='stock-dealer', password='test-password')
		dealer_user.groups.add(Group.objects.create(name=ROLE_DEALER))
		supplier = Supplier.objects.create(
			name='Kitwe Supplier', district='Kitwe', latitude=-12.8,
			longitude=28.2, current_stock_kg=200,
			stock_fertilizer_d_kg=200, is_active=True,
		)
		dealer = AgroDealer.objects.create(
			name='Kitwe Dealer', district='Kitwe', latitude=-12.81,
			longitude=28.21, user=dealer_user,
		)
		dispatch = SupplierDispatch.objects.create(
			supplier=supplier,
			agro_dealer=dealer,
			input_type='fertilizer_d',
			quantity_kg=Decimal('75.50'),
			dispatched_by=ministry_user,
		)
		self.client.force_login(dealer_user)

		receipt_response = self.client.post(
			reverse('dealer_confirm_stock_receipt', args=[dispatch.pk]),
			{'quantity_kg': '60.25'},
		)
		self.assertEqual(receipt_response.status_code, 302)
		self.client.force_login(ministry_user)

		response = self.client.get(reverse('dashboard_home'))

		self.assertEqual(response.context['kpis']['total_available_stock_kg'], Decimal('60.25'))

	def test_dashboard_uses_current_stock_not_historical_receipt_total(self):
		user = User.objects.create_user(username='stock-reset-ministry', password='test-password')
		user.groups.add(Group.objects.get_or_create(name=ROLE_MINISTRY)[0])
		supplier = Supplier.objects.create(
			name='Kitwe Supplier', district='Kitwe', latitude=-12.8,
			longitude=28.2, is_active=True,
		)
		dealer = AgroDealer.objects.create(
			name='Nkana Agro-Dealer', district='Kitwe', latitude=-12.81,
			longitude=28.21, stock_quantity_kg=Decimal('0'),
		)
		dispatch = SupplierDispatch.objects.create(
			supplier=supplier,
			agro_dealer=dealer,
			input_type='fertilizer_d',
			quantity_kg=Decimal('532'),
			dispatched_by=user,
		)
		DealerStockReceipt.objects.create(
			dispatch=dispatch,
			quantity_kg=Decimal('532'),
			received_by=user,
		)
		self.client.force_login(user)

		response = self.client.get(reverse('dashboard_home'))

		self.assertEqual(response.context['kpis']['total_available_stock_kg'], Decimal('0'))
