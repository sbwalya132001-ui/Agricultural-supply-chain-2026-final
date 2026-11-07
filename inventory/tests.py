from django.test import TestCase
from django.contrib.auth.models import Group, User
from django.db.models import Sum
from django.urls import reverse
from decimal import Decimal
from unittest.mock import patch

from accounts.models import UserProfile

from forecasting.models import Forecast
from farmers.models import Farmer, FarmerInputUsage
from logistics.models import AgroDealer, Supplier

from .models import DealerInputAllocation, FarmerAllocation, InventoryAllocation, SupplierDispatch
from .forms import InventoryAllocationForm
from .services import latest_forecast_demand_totals, run_inventory_allocation


class ForecastQuantityAllocationFormTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_superuser(
			username='allocation-ministry', password='test-pass-123', email='ministry@example.com',
		)
		Forecast.objects.create(
			district='Kitwe', input_type='fertilizer_d', forecast_season='2025/2026',
			predicted_quantity_kg=Decimal('125.50'), seasons_used=5,
		)
		Forecast.objects.create(
			district='Ndola', input_type='fertilizer_d', forecast_season='2025/2026',
			predicted_quantity_kg=Decimal('250.25'), seasons_used=5,
		)
		Forecast.objects.create(
			district='Kitwe', input_type='fertilizer_d', forecast_season='2024/2025',
			predicted_quantity_kg=Decimal('999.00'), seasons_used=4,
		)

	def test_quantities_are_summed_from_latest_forecasts(self):
		self.client.force_login(self.user)

		response = self.client.get(reverse('run_allocation'))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context['form']['supply_fertilizer_d'].value(), Decimal('375.75'))
		self.assertTrue(response.context['form'].fields['supply_fertilizer_d'].disabled)
		self.assertEqual(
			latest_forecast_demand_totals()['fertilizer_d'],
			Decimal('375.75'),
		)
		self.assertContains(response, 'Forecast total (kg)')
		self.assertContains(response, 'Price per kg (K)')

	def test_allocation_supply_totals_use_baseline_not_scenario_quantity(self):
		Forecast.objects.filter(district='Kitwe', forecast_season='2025/2026').update(
			predicted_quantity_kg=Decimal('999.00'),
			baseline_predicted_quantity_kg=Decimal('125.50'),
			weather_scenario_quantity_kg=Decimal('90.00'),
		)
		Forecast.objects.filter(district='Ndola', forecast_season='2025/2026').update(
			predicted_quantity_kg=Decimal('999.00'),
			baseline_predicted_quantity_kg=Decimal('250.25'),
			weather_scenario_quantity_kg=Decimal('300.00'),
		)

		totals = latest_forecast_demand_totals()

		self.assertEqual(totals['fertilizer_d'], Decimal('375.75'))

	def test_inventory_optimizer_allocates_baseline_not_weather_scenario(self):
		Forecast.objects.filter(district='Kitwe', forecast_season='2025/2026').update(
			predicted_quantity_kg=Decimal('999.00'),
			baseline_predicted_quantity_kg=Decimal('125.50'),
			weather_scenario_quantity_kg=Decimal('90.00'),
		)
		Forecast.objects.filter(district='Ndola', forecast_season='2025/2026').update(
			predicted_quantity_kg=Decimal('999.00'),
			baseline_predicted_quantity_kg=Decimal('250.25'),
			weather_scenario_quantity_kg=Decimal('300.00'),
		)
		for district, latitude, longitude in (
			('Kitwe', -12.80, 28.22), ('Ndola', -12.97, 28.64),
		):
			Supplier.objects.create(
				name=f'{district} baseline supplier', district=district,
				latitude=latitude, longitude=longitude, is_active=True,
			)
			AgroDealer.objects.create(
				name=f'{district} baseline dealer', district=district,
				latitude=latitude, longitude=longitude,
			)

		result = run_inventory_allocation(
			{'fertilizer_d': Decimal('1000.00')},
			{'fertilizer_d': Decimal('2.00')},
		)

		self.assertIsNone(result['error'])
		allocations = {
			allocation.district: allocation.allocated_quantity_kg
			for allocation in InventoryAllocation.objects.all()
		}
		self.assertEqual(allocations, {'Kitwe': Decimal('125.50'), 'Ndola': Decimal('250.25')})

	@patch('inventory.views.run_inventory_allocation')
	def test_post_uses_server_calculated_totals_not_submitted_quantities(self, run_allocation):
		run_allocation.return_value = {
			'error': None,
			'succeeded': [],
			'skipped': [],
		}
		self.client.force_login(self.user)
		post_data = {
			f'cost_{input_type}': '2.50'
			for input_type in InventoryAllocationForm.INPUT_TYPES
		}
		post_data['supply_fertilizer_d'] = '1.00'

		response = self.client.post(reverse('run_allocation'), post_data)

		self.assertRedirects(response, reverse('allocation_list'))
		supply_values, cost_values = run_allocation.call_args.args
		self.assertEqual(supply_values['fertilizer_d'], Decimal('375.75'))
		self.assertEqual(cost_values['fertilizer_d'], Decimal('2.50'))

	@patch('inventory.views.run_inventory_allocation')
	def test_ministry_can_select_zmd_scenario_quantity_for_allocation(self, run_allocation):
		Forecast.objects.filter(district='Kitwe', forecast_season='2025/2026').update(
			baseline_predicted_quantity_kg=Decimal('125.50'),
			weather_scenario_quantity_kg=Decimal('90.00'),
		)
		Forecast.objects.filter(district='Ndola', forecast_season='2025/2026').update(
			baseline_predicted_quantity_kg=Decimal('250.25'),
			weather_scenario_quantity_kg=Decimal('300.00'),
		)
		run_allocation.return_value = {
			'error': None,
			'succeeded': [],
			'skipped': [],
		}
		self.client.force_login(self.user)
		post_data = {
			f'cost_{input_type}': '2.50'
			for input_type in InventoryAllocationForm.INPUT_TYPES
		}
		post_data['allocation_quantity_source'] = 'zmd_scenario'

		response = self.client.post(reverse('run_allocation'), post_data)

		self.assertRedirects(response, reverse('allocation_list'))
		supply_values, cost_values = run_allocation.call_args.args
		self.assertEqual(supply_values['fertilizer_d'], Decimal('390.00'))
		self.assertEqual(cost_values['fertilizer_d'], Decimal('2.50'))

	@patch('inventory.views.run_inventory_allocation')
	def test_ministry_can_select_seas5_scenario_quantity_for_allocation(self, run_allocation):
		Forecast.objects.filter(district='Kitwe', forecast_season='2025/2026').update(
			baseline_predicted_quantity_kg=Decimal('125.50'),
			weather_scenario_quantity_kg=Decimal('90.00'),
			seas5_scenario_quantity_kg=Decimal('120.00'),
		)
		Forecast.objects.filter(district='Ndola', forecast_season='2025/2026').update(
			baseline_predicted_quantity_kg=Decimal('250.25'),
			weather_scenario_quantity_kg=Decimal('300.00'),
			seas5_scenario_quantity_kg=Decimal('240.00'),
		)
		run_allocation.return_value = {
			'error': None,
			'succeeded': [],
			'skipped': [],
		}
		self.client.force_login(self.user)
		post_data = {
			f'cost_{input_type}': '2.50'
			for input_type in InventoryAllocationForm.INPUT_TYPES
		}
		post_data['allocation_quantity_source'] = 'seas5_scenario'

		response = self.client.post(reverse('run_allocation'), post_data)

		self.assertRedirects(response, reverse('allocation_list'))
		supply_values, _ = run_allocation.call_args.args
		self.assertEqual(supply_values['fertilizer_d'], Decimal('360.00'))
		self.assertEqual(run_allocation.call_args.kwargs['quantity_source'], 'seas5_scenario')


class DirectDealerAllocationTests(TestCase):
	def setUp(self):
		Supplier.objects.create(
			name='Kitwe Central', district='Kitwe', latitude=-12.8,
			longitude=28.2, is_active=True,
		)
		Supplier.objects.create(
			name='Ndola Central', district='Ndola', latitude=-12.9,
			longitude=28.6, is_active=True,
		)
		for district in ('Kitwe', 'Ndola'):
			for farmer_index, quantity in enumerate((100, 300), start=1):
				farmer = Farmer.objects.create(
					first_name=district,
					last_name=f'Farmer {farmer_index}',
					national_id=f'{district.upper()}-ALLOCATION-{farmer_index}',
					district=district,
					farm_size_hectares=2,
				)
				FarmerInputUsage.objects.create(
					farmer=farmer,
					season='2024/2025',
					input_type='fertilizer_d',
					quantity_kg=quantity,
				)
			for index in range(3):
				AgroDealer.objects.create(
					name=f'{district} Dealer {index}',
					district=district,
					latitude=-12.8,
					longitude=28.2,
				)
		Forecast.objects.create(
			district='Kitwe', input_type='fertilizer_d',
			forecast_season='2025/2026', predicted_quantity_kg=100,
			seasons_used=4,
		)
		Forecast.objects.create(
			district='Ndola', input_type='fertilizer_d',
			forecast_season='2025/2026', predicted_quantity_kg=200,
			seasons_used=4,
		)

	def test_allocates_directly_to_dealers_and_names_supplier(self):
		result = run_inventory_allocation(
			{'fertilizer_d': Decimal('1000')},
			{'fertilizer_d': Decimal('2.50')},
		)

		self.assertIsNone(result['error'])
		self.assertEqual(len(result['supplier_allocations']), 2)
		self.assertEqual(len(result['dealer_allocations']), 6)
		for supplier_allocation in result['supplier_allocations']:
			dealer_total = sum(
				allocation.quantity_kg
				for allocation in DealerInputAllocation.objects.filter(
					supplier=supplier_allocation['supplier'],
					forecast=supplier_allocation['forecast'],
					allocation_run=supplier_allocation['allocation_run'],
				)
			)
			self.assertEqual(dealer_total, supplier_allocation['quantity_kg'])
		self.assertEqual(
			DealerInputAllocation.objects.filter(agro_dealer__district='Kitwe').count(),
			3,
		)
		self.assertEqual(
			DealerInputAllocation.objects.filter(agro_dealer__district='Ndola').count(),
			3,
		)
		self.assertEqual(
			Supplier.objects.get(district='Kitwe').stock_fertilizer_d_kg,
			Decimal('100'),
		)
		self.assertEqual(
			Supplier.objects.get(district='Ndola').stock_fertilizer_d_kg,
			Decimal('200'),
		)
		for district, expected_total in (('Kitwe', Decimal('100')), ('Ndola', Decimal('200'))):
			farmer_total = sum(
				allocation.quantity_kg
				for allocation in FarmerAllocation.objects.filter(farmer__district=district)
			)
			self.assertEqual(farmer_total, expected_total)


class SupplierDispatchTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(username='supplier-user', password='test-pass-123')
		self.user.groups.add(Group.objects.get_or_create(name='Supplier')[0])
		UserProfile.objects.create(user=self.user, district='Ndola')
		self.supplier = Supplier.objects.create(
			name='Ndola Supplier', district='Ndola', latitude=-12.9,
			longitude=28.6, current_stock_kg=500,
			stock_seed_maize_kg=500,
			is_active=True,
		)
		self.dealer = AgroDealer.objects.create(
			name='Ndola Dealer', district='Ndola', latitude=-12.91,
			longitude=28.61, stock_quantity_kg=10,
		)
		self.other_dealer = AgroDealer.objects.create(
			name='Kitwe Dealer', district='Kitwe', latitude=-12.8,
			longitude=28.2, stock_quantity_kg=10,
		)
		forecast = Forecast.objects.create(
			district='Ndola', input_type='seed_maize', forecast_season='2025/2026',
			predicted_quantity_kg=200, seasons_used=8,
		)
		DealerInputAllocation.objects.create(
			supplier=self.supplier, forecast=forecast, input_type='seed_maize',
			agro_dealer=self.dealer,
			quantity_kg=200, allocation_run='dispatch-test',
		)

	def test_supplier_can_issue_only_allocated_stock_within_ndola(self):
		self.client.force_login(self.user)

		response = self.client.post(reverse('supplier_dispatch'), {
			'supplier': self.supplier.id,
			'agro_dealer': self.dealer.id,
			'input_type': 'seed_maize',
			'quantity_kg': '125.50',
		})

		self.assertRedirects(response, reverse('supplier_dispatch'))
		self.supplier.refresh_from_db()
		self.dealer.refresh_from_db()
		self.assertEqual(self.supplier.current_stock_kg, Decimal('374.50'))
		self.assertEqual(self.supplier.stock_seed_maize_kg, Decimal('374.50'))
		self.assertEqual(self.dealer.stock_quantity_kg, Decimal('10'))
		self.assertEqual(self.dealer.stock_seed_maize_kg, Decimal('0'))
		self.assertEqual(SupplierDispatch.objects.count(), 1)
		self.assertEqual(SupplierDispatch.objects.get().dispatched_by, self.user)
		self.assertEqual(SupplierDispatch.objects.get().allocation_run, 'dispatch-test')
		self.assertIsNone(SupplierDispatch.objects.get().received_at)

	def test_kitwe_supplier_can_dispatch_to_every_allocated_kitwe_dealer(self):
		kitwe_user = User.objects.create_user(username='kitwe-supplier-user', password='test-pass-123')
		kitwe_user.groups.add(Group.objects.get_or_create(name='Supplier')[0])
		UserProfile.objects.create(user=kitwe_user, district='Kitwe')
		kitwe_supplier = Supplier.objects.create(
			name='Kitwe Supplier', district='Kitwe', latitude=-12.8,
			longitude=28.2, current_stock_kg=300,
			stock_seed_maize_kg=300, is_active=True,
		)
		forecast = Forecast.objects.create(
			district='Kitwe', input_type='seed_maize', forecast_season='2025/2026',
			predicted_quantity_kg=300, seasons_used=8,
		)
		dealers = [
			AgroDealer.objects.create(
				name=f'Kitwe Dealer {index}', district='Kitwe',
				latitude=-12.8, longitude=28.2,
			)
			for index in range(3)
		]
		for dealer in dealers:
			DealerInputAllocation.objects.create(
				supplier=kitwe_supplier, forecast=forecast, input_type='seed_maize',
				agro_dealer=dealer, quantity_kg=100, allocation_run='kitwe-dispatch-test',
			)

		self.client.force_login(kitwe_user)
		for dealer in dealers:
			with self.subTest(dealer=dealer.name):
				response = self.client.post(reverse('supplier_dispatch'), {
					'supplier': kitwe_supplier.pk,
					'agro_dealer': dealer.pk,
					'input_type': 'seed_maize',
					'quantity_kg': '100.00',
				})
				self.assertRedirects(response, reverse('supplier_dispatch'))

		self.assertEqual(SupplierDispatch.objects.filter(supplier=kitwe_supplier).count(), 3)
		self.assertSetEqual(
			set(SupplierDispatch.objects.filter(supplier=kitwe_supplier).values_list('agro_dealer_id', flat=True)),
			{dealer.pk for dealer in dealers},
		)
		kitwe_supplier.refresh_from_db()
		self.assertEqual(kitwe_supplier.current_stock_kg, Decimal('0.00'))
		self.assertEqual(kitwe_supplier.stock_seed_maize_kg, Decimal('0.00'))

	def test_dealer_receipt_updates_stock_once(self):
		self.client.force_login(self.user)
		self.client.post(reverse('supplier_dispatch'), {
			'supplier': self.supplier.id,
			'agro_dealer': self.dealer.id,
			'input_type': 'seed_maize',
			'quantity_kg': '125.50',
		})
		dispatch = SupplierDispatch.objects.get()
		dealer_user = User.objects.create_user(username='dealer-account', password='test-pass-123')
		dealer_user.groups.add(Group.objects.create(name='Agro-Dealer'))
		self.dealer.user = dealer_user
		self.dealer.save(update_fields=['user'])
		self.client.force_login(dealer_user)

		portal_response = self.client.get(reverse('dealer_portal'))
		self.assertContains(portal_response, 'Inputs awaiting receipt confirmation')
		self.assertContains(portal_response, '125.50 kg')
		self.assertContains(portal_response, 'name="quantity_kg"')
		response = self.client.post(
			reverse('dealer_confirm_stock_receipt', args=[dispatch.pk]),
			{'quantity_kg': '50.00'},
		)

		self.assertRedirects(response, reverse('dealer_portal'))
		self.dealer.refresh_from_db()
		dispatch.refresh_from_db()
		self.assertEqual(self.dealer.stock_quantity_kg, Decimal('60.00'))
		self.assertEqual(self.dealer.stock_seed_maize_kg, Decimal('50.00'))
		self.assertIsNone(dispatch.received_at)
		self.assertEqual(dispatch.receipts.aggregate(total=Sum('quantity_kg'))['total'], Decimal('50.00'))

		response = self.client.post(
			reverse('dealer_confirm_stock_receipt', args=[dispatch.pk]),
			{'quantity_kg': '80.00'},
		)
		self.assertRedirects(response, reverse('dealer_portal'))
		self.dealer.refresh_from_db()
		self.assertEqual(self.dealer.stock_quantity_kg, Decimal('60.00'))

		response = self.client.post(
			reverse('dealer_confirm_stock_receipt', args=[dispatch.pk]),
			{'quantity_kg': '75.50'},
		)
		self.assertRedirects(response, reverse('dealer_portal'))
		self.dealer.refresh_from_db()
		dispatch.refresh_from_db()
		self.assertEqual(self.dealer.stock_quantity_kg, Decimal('135.50'))
		self.assertEqual(self.dealer.stock_seed_maize_kg, Decimal('125.50'))
		self.assertEqual(dispatch.received_by, dealer_user)
		self.assertIsNotNone(dispatch.received_at)
		self.assertEqual(dispatch.receipts.count(), 2)

		response = self.client.post(
			reverse('dealer_confirm_stock_receipt', args=[dispatch.pk]),
			{'quantity_kg': '1.00'},
		)
		self.assertEqual(response.status_code, 404)
		self.dealer.refresh_from_db()
		self.assertEqual(self.dealer.stock_quantity_kg, Decimal('135.50'))

	def test_dispatch_rejects_insufficient_stock_and_other_district_dealer(self):
		self.client.force_login(self.user)

		response = self.client.post(reverse('supplier_dispatch'), {
			'supplier': self.supplier.id,
			'agro_dealer': self.dealer.id,
			'input_type': 'seed_maize',
			'quantity_kg': '600',
		})
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'cannot exceed the remaining allocated quantity')
		self.assertEqual(SupplierDispatch.objects.count(), 0)

		response = self.client.post(reverse('supplier_dispatch'), {
			'supplier': self.supplier.id,
			'agro_dealer': self.other_dealer.id,
			'input_type': 'seed_maize',
			'quantity_kg': '10',
		})
		self.assertEqual(response.status_code, 200)
		self.assertEqual(SupplierDispatch.objects.count(), 0)

	def test_supplier_dispatch_allows_explicit_supplier_when_profile_missing(self):
		user = User.objects.create_user(username='supplier-no-profile', password='test-pass-123')
		user.groups.add(Group.objects.get_or_create(name='Supplier')[0])
		supplier = Supplier.objects.create(
			name='Kitwe Supplier Missing Profile', district='Kitwe', latitude=-12.9,
			longitude=28.6, current_stock_kg=600,
			stock_seed_maize_kg=600,
			is_active=True,
		)
		dealer = AgroDealer.objects.create(
			name='Kitwe Dealer Without Profile', district='Kitwe', latitude=-12.91,
			longitude=28.61, stock_quantity_kg=10,
		)
		forecast = Forecast.objects.create(
			district='Kitwe', input_type='seed_maize', forecast_season='2025/2026',
			predicted_quantity_kg=200, seasons_used=8,
		)
		DealerInputAllocation.objects.create(
			supplier=supplier, forecast=forecast,
			input_type='seed_maize', agro_dealer=dealer,
			quantity_kg=200, allocation_run='dispatch-no-profile',
		)

		self.client.force_login(user)
		response = self.client.post(reverse('supplier_dispatch'), {
			'supplier': supplier.id,
			'agro_dealer': dealer.id,
			'input_type': 'seed_maize',
			'quantity_kg': '125.50',
		})

		self.assertRedirects(response, reverse('supplier_dispatch'))
		self.assertEqual(SupplierDispatch.objects.count(), 1)

	def test_new_seed_types_flow_through_allocation_form_dispatch_and_receipt(self):
		allocation_form = InventoryAllocationForm()
		for input_type in ('seed_soybeans', 'seed_sunflower', 'seed_popcorn'):
			self.assertIn(f'supply_{input_type}', allocation_form.fields)
			self.assertIn(f'cost_{input_type}', allocation_form.fields)

		self.supplier.stock_seed_sunflower_kg = Decimal('100')
		self.supplier.save(update_fields=['stock_seed_sunflower_kg'])
		forecast = Forecast.objects.create(
			district='Ndola', input_type='seed_sunflower', forecast_season='2025/2026',
			predicted_quantity_kg=100, seasons_used=8,
		)
		DealerInputAllocation.objects.create(
			supplier=self.supplier, forecast=forecast, input_type='seed_sunflower',
			agro_dealer=self.dealer, quantity_kg=Decimal('100'),
			allocation_run='sunflower-dispatch-test',
		)
		self.client.force_login(self.user)

		dispatch_response = self.client.post(reverse('supplier_dispatch'), {
			'supplier': self.supplier.id,
			'agro_dealer': self.dealer.id,
			'input_type': 'seed_sunflower',
			'quantity_kg': '25.00',
		})
		self.assertRedirects(dispatch_response, reverse('supplier_dispatch'))
		dispatch = SupplierDispatch.objects.get(input_type='seed_sunflower')
		self.supplier.refresh_from_db()
		self.assertEqual(self.supplier.stock_seed_sunflower_kg, Decimal('75.00'))

		dealer_user = User.objects.create_user(username='sunflower-dealer', password='test-pass-123')
		dealer_user.groups.add(Group.objects.get_or_create(name='Agro-Dealer')[0])
		self.dealer.user = dealer_user
		self.dealer.save(update_fields=['user'])
		self.client.force_login(dealer_user)
		receipt_response = self.client.post(
			reverse('dealer_confirm_stock_receipt', args=[dispatch.pk]),
			{'quantity_kg': '20.00'},
		)
		self.assertRedirects(receipt_response, reverse('dealer_portal'))
		self.dealer.refresh_from_db()
		self.assertEqual(self.dealer.stock_seed_sunflower_kg, Decimal('20.00'))
		self.assertEqual(self.dealer.stock_quantity_kg, Decimal('30.00'))
