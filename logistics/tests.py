from unittest.mock import patch
from datetime import date
from decimal import Decimal

from django.test import TestCase
from farmers.models import Farmer
from farmers.models import FarmerInputUsage
from forecasting.models import Forecast
from inventory.models import DealerInputAllocation, FarmerAllocation

from .models import AgroDealer, RoutePlan, RouteStopInput, Supplier, SupplierDealerRoute
from .services import build_delivery_route


class RouteOptimizationTests(TestCase):
	def test_new_supplier_and_dealer_start_with_zero_stock(self):
		supplier = Supplier.objects.create(
			name='Zero Stock Supplier', district='Lilongwe', latitude=-13.97,
			longitude=33.77, is_active=True,
		)
		dealer = AgroDealer.objects.create(
			name='Zero Stock Dealer', district='Lilongwe', latitude=-13.96,
			longitude=33.78,
		)

		self.assertEqual(supplier.current_stock_kg, Decimal('0'))
		self.assertEqual(supplier.stock_fertilizer_d_kg, Decimal('0'))
		self.assertEqual(supplier.stock_fertilizer_urea_kg, Decimal('0'))
		self.assertEqual(supplier.stock_seed_maize_kg, Decimal('0'))
		self.assertEqual(supplier.stock_seed_other_kg, Decimal('0'))
		self.assertEqual(dealer.stock_quantity_kg, Decimal('0'))
		self.assertEqual(dealer.stock_fertilizer_d_kg, Decimal('0'))
		self.assertEqual(dealer.stock_fertilizer_urea_kg, Decimal('0'))
		self.assertEqual(dealer.stock_seed_maize_kg, Decimal('0'))
		self.assertEqual(dealer.stock_seed_other_kg, Decimal('0'))

	def make_allocation_plan(self, supplier, dealers, quantity=Decimal('100'), run_id='route-test'):
		forecast, _ = Forecast.objects.get_or_create(
			district=supplier.district, input_type='fertilizer_d',
			forecast_season='2025/2026', predicted_quantity_kg=quantity,
			defaults={'seasons_used': 8},
		)
		dealer_quantity = (quantity / len(dealers)).quantize(Decimal('0.01'))
		for dealer in dealers:
			DealerInputAllocation.objects.create(
				supplier=supplier, forecast=forecast, input_type='fertilizer_d',
				agro_dealer=dealer,
				quantity_kg=dealer_quantity, allocation_run=run_id,
			)
	def make_farmer(self, national_id, latitude, longitude):
		return Farmer.objects.create(
			first_name='Test',
			last_name=national_id,
			national_id=national_id,
			district='Lilongwe',
			farm_size_hectares=1,
			latitude=latitude,
			longitude=longitude,
		)

	def test_builds_independent_route_for_each_allocated_dealer(self):
		supplier = Supplier.objects.create(
			name='Lilongwe Route Supplier', district='Lilongwe', latitude=-13.97,
			longitude=33.77, is_active=True,
		)
		dealers = [AgroDealer.objects.create(
			name=f'Lilongwe Dealer {index}', district='Lilongwe',
			latitude=-13.96 - index * 0.01, longitude=33.78 + index * 0.01,
		) for index in range(3)]
		self.make_allocation_plan(supplier, dealers)

		result = build_delivery_route(start_coordinates=(-13.97, 33.77))

		self.assertIsNone(result['error'])
		self.assertEqual(result['stop_count'], 0)
		self.assertEqual(result['distribution_leg_count'], 3)
		self.assertEqual(RoutePlan.objects.count(), 1)
		self.assertFalse(RoutePlan.objects.first().stops.exists())
		self.assertCountEqual(
			SupplierDealerRoute.objects.values_list('agro_dealer_id', flat=True),
			[dealer.id for dealer in dealers],
		)

	def test_combines_duplicate_supplier_dealer_allocations_into_one_leg(self):
		supplier = Supplier.objects.create(
			name='Duplicate Supplier', district='Lilongwe', latitude=-13.97,
			longitude=33.77, is_active=True,
		)
		dealer = AgroDealer.objects.create(
			name='Duplicate Dealer', district='Lilongwe', latitude=-13.96,
			longitude=33.78,
		)
		fertilizer_forecast = Forecast.objects.create(
			district=supplier.district, input_type='fertilizer_d',
			forecast_season='2025/2026', predicted_quantity_kg=Decimal('200'),
			seasons_used=8,
		)
		seed_forecast = Forecast.objects.create(
			district=supplier.district, input_type='seed_maize',
			forecast_season='2025/2026', predicted_quantity_kg=Decimal('100'),
			seasons_used=8,
		)
		DealerInputAllocation.objects.create(
			supplier=supplier, forecast=fertilizer_forecast, input_type='fertilizer_d',
			agro_dealer=dealer, quantity_kg=Decimal('75.00'), allocation_run='dup-test',
		)
		DealerInputAllocation.objects.create(
			supplier=supplier, forecast=seed_forecast, input_type='seed_maize',
			agro_dealer=dealer, quantity_kg=Decimal('25.00'), allocation_run='dup-test',
		)

		result = build_delivery_route(start_coordinates=(-13.97, 33.77), district='Lilongwe')

		self.assertIsNone(result['error'])
		self.assertEqual(result['distribution_leg_count'], 1)
		self.assertEqual(SupplierDealerRoute.objects.count(), 1)
		self.assertEqual(SupplierDealerRoute.objects.get().allocated_quantity_kg, Decimal('100.00'))

	def test_reports_missing_coordinates(self):
		result = build_delivery_route()

		self.assertEqual(result['stop_count'], 0)
		self.assertIn('inventory allocation', result['error'])

	def test_ignores_out_of_range_coordinates(self):
		result = build_delivery_route()

		self.assertEqual(result['stop_count'], 0)
		self.assertIn('inventory allocation', result['error'])

	@patch('logistics.services._mapbox_directions')
	@patch('logistics.services._mapbox_matrix')
	def test_uses_mapbox_matrix_distances(self, matrix_mock, directions_mock):
		supplier = Supplier.objects.create(
			name='Mapbox Supplier', district='Lilongwe', latitude=-13.97,
			longitude=33.77, is_active=True,
		)
		AgroDealer.objects.create(
			name='Mapbox Dealer 1', district='Lilongwe', latitude=-13.90, longitude=33.85,
		)
		AgroDealer.objects.create(
			name='Mapbox Dealer 2', district='Lilongwe', latitude=-13.96, longitude=33.78,
		)
		matrix_mock.return_value = {
			'distances': [[0, 10000], [10000, 0]],
			'durations': [[0, 100], [100, 0]],
		}
		dealers = list(AgroDealer.objects.all())
		self.make_allocation_plan(supplier, dealers)
		directions_mock.side_effect = lambda start, end: [
			[start[1], start[0]], [end[1], end[0]],
		]

		result = build_delivery_route(start_coordinates=(supplier.latitude, supplier.longitude))

		self.assertTrue(result['mapbox_used'])
		self.assertEqual(result['distribution_leg_count'], 2)
		self.assertEqual(matrix_mock.call_count, 2)
		for leg in result['route'].distribution_legs.select_related('supplier', 'agro_dealer'):
			self.assertEqual(leg.distance_from_previous_km, 10)
			self.assertEqual(
				leg.road_geometry[0],
				[leg.agro_dealer.longitude, leg.agro_dealer.latitude],
			)
			self.assertEqual(
				leg.road_geometry[-1],
				[leg.supplier.longitude, leg.supplier.latitude],
			)
			directions_mock.assert_any_call(
				(leg.agro_dealer.latitude, leg.agro_dealer.longitude),
				(leg.supplier.latitude, leg.supplier.longitude),
			)

	@patch('logistics.services._mapbox_matrix')
	@patch('logistics.services._mapbox_directions')
	def test_each_dealer_gets_an_independent_route_to_its_supplier(self, directions_mock, matrix_mock):
		self.make_farmer('R008', -13.90, 33.85)
		supplier = Supplier.objects.create(
			name='Lilongwe Central Supplier', district='Lilongwe', latitude=-13.97,
			longitude=33.77, is_active=True,
		)
		dealers = [AgroDealer.objects.create(
			name=f'Lilongwe Dealer {index}', district='Lilongwe',
			latitude=-13.96 - index * 0.01, longitude=33.78 + index * 0.01,
		) for index in range(3)]
		self.make_allocation_plan(supplier, dealers)
		matrix_mock.return_value = None
		directions_mock.return_value = None

		result = build_delivery_route(start_coordinates=(-13.97, 33.77))

		self.assertEqual(result['distribution_leg_count'], 3)
		legs = list(SupplierDealerRoute.objects.select_related('supplier', 'agro_dealer'))
		self.assertEqual(len(legs), 3)
		self.assertCountEqual([leg.agro_dealer_id for leg in legs], [dealer.id for dealer in dealers])
		for leg in legs:
			self.assertEqual(leg.supplier, supplier)
			self.assertEqual(leg.road_geometry, [])

	@patch('logistics.services._mapbox_matrix', return_value=None)
	@patch('logistics.services._mapbox_directions', return_value=None)
	def test_allocated_route_has_schedule_dealer_and_input_basket(self, directions_mock, matrix_mock):
		farmer = self.make_farmer('R009', -13.90, 33.85)
		farmer.district = 'Lilongwe'
		farmer.save(update_fields=['district'])
		FarmerInputUsage.objects.create(
			farmer=farmer, season='2024/2025', input_type='fertilizer_d', quantity_kg=100,
		)
		forecast = Forecast.objects.create(
			district='Lilongwe', input_type='fertilizer_d', forecast_season='2025/2026',
			predicted_quantity_kg=100, seasons_used=8,
		)
		FarmerAllocation.objects.create(
			farmer=farmer, forecast=forecast, input_type='fertilizer_d',
			quantity_kg=Decimal('100'), allocation_run='route-test',
		)
		supplier = Supplier.objects.create(
			name='Lilongwe Scheduled Supplier', district='Lilongwe', latitude=-13.97,
			longitude=33.77, is_active=True,
		)
		dealer = AgroDealer.objects.create(
			name='Lilongwe Assigned Dealer', district='Lilongwe', latitude=-13.96,
			longitude=33.78,
		)
		DealerInputAllocation.objects.create(
			supplier=supplier, forecast=forecast, input_type='fertilizer_d',
			agro_dealer=dealer,
			quantity_kg=Decimal('100'), allocation_run='route-test',
		)

		result = build_delivery_route(
			district='Lilongwe',
			planned_delivery_date=date(2026, 10, 1),
			vehicle_identifier='TRUCK-001',
		)

		self.assertIsNone(result['error'])
		route = result['route']
		self.assertEqual(route.planned_delivery_date, date(2026, 10, 1))
		self.assertEqual(route.vehicle_identifier, 'TRUCK-001')
		self.assertFalse(route.stops.exists())
		self.assertEqual(route.distribution_legs.get().agro_dealer, dealer)

	@patch('logistics.services._mapbox_matrix', return_value=None)
	@patch('logistics.services._mapbox_directions', return_value=None)
	def test_national_route_assigns_stops_to_same_district_dealers(self, directions_mock, matrix_mock):
		kitwe_farmer = Farmer.objects.create(
			first_name='Kitwe', last_name='Farmer', national_id='R010',
			district='Kitwe', farm_size_hectares=1, latitude=-12.8, longitude=28.2,
		)
		ndola_farmer = Farmer.objects.create(
			first_name='Ndola', last_name='Farmer', national_id='R011',
			district='Ndola', farm_size_hectares=1, latitude=-12.9, longitude=28.6,
		)
		for farmer in (kitwe_farmer, ndola_farmer):
			FarmerInputUsage.objects.create(
				farmer=farmer, season='2024/2025', input_type='fertilizer_d', quantity_kg=100,
			)
			forecast = Forecast.objects.create(
				district=farmer.district, input_type='fertilizer_d', forecast_season='2025/2026',
				predicted_quantity_kg=100, seasons_used=8,
			)
			FarmerAllocation.objects.create(
				farmer=farmer, forecast=forecast, input_type='fertilizer_d',
				quantity_kg=100, allocation_run='national-route-test',
			)
		for district, latitude, longitude in (('Kitwe', -12.81, 28.21), ('Ndola', -12.91, 28.61)):
			supplier = Supplier.objects.create(
				name=f'{district} National Supplier', district=district,
				latitude=latitude, longitude=longitude, is_active=True,
			)
			dealer = AgroDealer.objects.create(
				name=f'{district} National Dealer', district=district,
				latitude=latitude, longitude=longitude,
			)
			self.make_allocation_plan(supplier, [dealer], run_id='national-route-test')

		result = build_delivery_route()

		self.assertIsNone(result['error'])
		for leg in result['route'].distribution_legs.select_related('supplier', 'agro_dealer'):
			self.assertEqual(leg.supplier.district, leg.agro_dealer.district)
