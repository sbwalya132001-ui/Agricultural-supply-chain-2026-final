from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings
from django.urls import reverse

from .decorators import (
	ROLE_DEALER,
	ROLE_DISTRICT,
	ROLE_MINISTRY,
	ROLE_SUPPLIER,
)
from .models import UserProfile
from farmers.models import Farmer
from forecasting.models import Forecast
from inventory.models import InventoryAllocation
from logistics.models import AgroDealer, RoutePlan, RouteStop, Supplier, SupplierDealerRoute


class StakeholderAccessTests(TestCase):
	def make_user(self, username, role):
		user = User.objects.create_user(username=username, password='test-pass-123')
		user.groups.add(Group.objects.create(name=role))
		return user

	def test_ministry_can_access_all_operational_pages(self):
		self.client.force_login(self.make_user('ministry', ROLE_MINISTRY))

		for page_name in (
			'dashboard_home', 'farmer_list', 'forecast_list',
			'allocation_list', 'route_list',
		):
			with self.subTest(page_name=page_name):
				self.assertEqual(self.client.get(reverse(page_name)).status_code, 200)

	def test_district_officer_can_monitor_but_cannot_run_forecast_or_allocation(self):
		self.client.force_login(self.make_user('district', ROLE_DISTRICT))

		for page_name in ('farmer_list', 'forecast_list', 'allocation_list', 'route_list'):
			with self.subTest(page_name=page_name):
				self.assertEqual(self.client.get(reverse(page_name)).status_code, 200)
		self.assertEqual(self.client.get(reverse('run_forecast')).status_code, 403)
		self.assertEqual(self.client.get(reverse('run_allocation')).status_code, 403)

	def test_supplier_and_dealer_have_narrow_operational_access(self):
		self.client.force_login(self.make_user('supplier', ROLE_SUPPLIER))
		self.assertEqual(self.client.get(reverse('allocation_list')).status_code, 200)
		self.assertEqual(self.client.get(reverse('route_list')).status_code, 200)
		self.assertEqual(self.client.get(reverse('supplier_dispatch')).status_code, 200)
		self.assertEqual(self.client.get(reverse('farmer_list')).status_code, 403)
		self.assertEqual(self.client.get(reverse('forecast_list')).status_code, 403)

		self.client.force_login(self.make_user('dealer', ROLE_DEALER))
		self.assertEqual(self.client.get(reverse('route_list')).status_code, 200)
		self.assertEqual(self.client.get(reverse('allocation_list')).status_code, 403)
		self.assertEqual(self.client.get(reverse('farmer_list')).status_code, 403)

	@override_settings(MAPBOX_ACCESS_TOKEN='test-map-token')
	def test_route_map_offers_browser_location_control(self):
		self.client.force_login(self.make_user('location-user', ROLE_MINISTRY))
		supplier = Supplier.objects.create(
			name='Kitwe Supplier Point', district='Kitwe', latitude=-12.80,
			longitude=28.22, is_active=True,
		)
		dealer = AgroDealer.objects.create(
			name='Kitwe Dealer', district='Kitwe', latitude=-12.81, longitude=28.23,
		)
		route = RoutePlan.objects.create(name='Dealer to supplier route')
		SupplierDealerRoute.objects.create(
			route=route, supplier=supplier, agro_dealer=dealer, sequence=1,
			road_geometry=[[28.23, -12.81], [28.225, -12.805], [28.22, -12.80]],
		)

		response = self.client.get(reverse('route_list'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'id="show-my-location"')
		self.assertContains(response, 'id="stop-location-sharing"')
		self.assertContains(response, 'navigator.geolocation.watchPosition')
		self.assertContains(response, 'Your location is only displayed on this map and is not saved.')
		self.assertEqual(
			response.context['map_data']['distributionLegs'][0]['coordinates'],
			[[dealer.longitude, dealer.latitude], [supplier.longitude, supplier.latitude]],
		)
		self.assertEqual(
			response.context['map_data']['distributionLegs'][0]['geometry'],
			[[28.23, -12.81], [28.225, -12.805], [28.22, -12.80]],
		)
		page_script = response.content.decode()
		self.assertLess(
			page_script.index("const map = new mapboxgl.Map("),
			page_script.index('distributionLegs.forEach((leg, index) => {'),
		)

	def test_agro_dealer_portal_shows_assigned_route_and_delivery_list(self):
		user = self.make_user('dealer-portal', ROLE_DEALER)
		supplier = Supplier.objects.create(
			name='Ndola Supplier', district='Ndola', latitude=-12.97,
			longitude=28.64, current_stock_kg=5000, stock_fertilizer_d_kg=5000,
			is_active=True,
		)
		dealer = AgroDealer.objects.create(
			name='Ndola Agro Dealer', district='Ndola', latitude=-12.99,
			longitude=28.65, stock_quantity_kg=2000, user=user,
		)
		route = RoutePlan.objects.create(name='Ndola dealer route')
		SupplierDealerRoute.objects.create(
			route=route, supplier=supplier, agro_dealer=dealer, sequence=1,
		)
		self.client.force_login(user)

		response = self.client.get(reverse('dealer_portal'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'My delivery assignments')
		self.assertContains(response, 'Ndola Agro Dealer')
		self.assertContains(response, 'Ndola Supplier')

	def test_agro_dealer_can_confirm_route_stop_delivery(self):
		user = self.make_user('dealer-confirm', ROLE_DEALER)
		supplier = Supplier.objects.create(
			name='Ndola Confirm Supplier', district='Ndola', latitude=-12.97,
			longitude=28.64, current_stock_kg=5000,
			stock_fertilizer_d_kg=5000, is_active=True,
		)
		dealer = AgroDealer.objects.create(
			name='Ndola Confirm Dealer', district='Ndola', latitude=-12.99,
			longitude=28.65, stock_quantity_kg=2000, user=user,
		)
		farmer = Farmer.objects.create(
			first_name='Delivery', last_name='Farmer', national_id='DEALER-CONFIRM-001',
			district='Ndola', farm_size_hectares=3,
			latitude=-12.98, longitude=28.66,
		)
		route = RoutePlan.objects.create(name='Ndola confirm route')
		stop = RouteStop.objects.create(route=route, farmer=farmer, sequence=1, allocated_quantity_kg=50)
		SupplierDealerRoute.objects.create(route=route, supplier=supplier, agro_dealer=dealer, sequence=1)
		self.client.force_login(user)

		response = self.client.post(
			reverse('dealer_confirm_delivery', args=[stop.id]),
			{'status': 'delivered', 'message': 'Delivered successfully'},
			follow=True,
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Delivery recorded')
		self.assertTrue(stop.farmer_confirmation is not None)

	def test_agro_dealer_portal_shows_latest_route_stops_once(self):
		user = self.make_user('dealer-latest-route', ROLE_DEALER)
		supplier = Supplier.objects.create(
			name='Ndola Latest Supplier', district='Ndola', latitude=-12.97,
			longitude=28.64, current_stock_kg=5000,
			stock_fertilizer_d_kg=5000, is_active=True,
		)
		second_supplier = Supplier.objects.create(
			name='Ndola Second Supplier', district='Ndola', latitude=-12.96,
			longitude=28.63, current_stock_kg=5000,
			stock_fertilizer_d_kg=5000, is_active=True,
		)
		dealer = AgroDealer.objects.create(
			name='Ndola Latest Dealer', district='Ndola', latitude=-12.99,
			longitude=28.65, stock_quantity_kg=2000, user=user,
		)
		old_route = RoutePlan.objects.create(name='Old Ndola route')
		SupplierDealerRoute.objects.create(route=old_route, supplier=supplier, agro_dealer=dealer, sequence=1)
		latest_route = RoutePlan.objects.create(name='Latest Ndola route')
		SupplierDealerRoute.objects.create(route=latest_route, supplier=supplier, agro_dealer=dealer, sequence=1)
		SupplierDealerRoute.objects.create(route=latest_route, supplier=second_supplier, agro_dealer=dealer, sequence=2)
		self.client.force_login(user)

		response = self.client.get(reverse('dealer_portal'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Latest Ndola route')
		self.assertNotContains(response, 'Old Ndola route')

	def test_unassigned_dealer_account_redirects_cleanly_with_message(self):
		user = self.make_user('dealer-unassigned', ROLE_DEALER)
		self.client.force_login(user)

		response = self.client.get(reverse('dealer_portal'), follow=True)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'not linked to a dealer profile yet')

	def test_unassigned_account_cannot_access_operational_pages(self):
		user = User.objects.create_user(username='unassigned', password='test-pass-123')
		self.client.force_login(user)

		self.assertEqual(self.client.get(reverse('dashboard_home')).status_code, 403)

	def test_login_page_shows_stakeholder_role_links(self):
		response = self.client.get(reverse('login'))

		self.assertContains(response, 'Ministry of Agriculture')
		self.assertContains(response, 'District Agricultural Officer')
		self.assertContains(response, 'Supplier')
		self.assertContains(response, 'Agro-Dealer')
		self.assertNotContains(response, 'Smallholder Farmer')
		self.assertNotContains(response, '?role=farmer')

	def test_unauthorized_stakeholder_sees_access_denied_page(self):
		self.client.force_login(self.make_user('dealer-denied', ROLE_DEALER))

		response = self.client.get(reverse('allocation_list'))

		self.assertEqual(response.status_code, 403)
		self.assertContains(response, 'Access denied', status_code=403)
		self.assertNotContains(response, '403 Forbidden', status_code=403)

	def test_district_officer_sees_only_assigned_district_data(self):
		user = self.make_user('ndola-officer', ROLE_DISTRICT)
		UserProfile.objects.create(user=user, district='Ndola')
		ndola_farmer = Farmer.objects.create(
			first_name='Ndola', last_name='Farmer', national_id='NDOLA-TEST',
			district='Ndola', farm_size_hectares=2,
		)
		kitwe_farmer = Farmer.objects.create(
			first_name='Kitwe', last_name='Farmer', national_id='KITWE-TEST',
			district='Kitwe', farm_size_hectares=2,
		)
		ndola_forecast = Forecast.objects.create(
			district='Ndola', input_type='seed_maize', forecast_season='2025/2026',
			predicted_quantity_kg=100, seasons_used=8,
		)
		Forecast.objects.create(
			district='Kitwe', input_type='seed_maize', forecast_season='2025/2026',
			predicted_quantity_kg=200, seasons_used=8,
		)
		InventoryAllocation.objects.create(
			district='Ndola', input_type='seed_maize', forecast=ndola_forecast,
			allocated_quantity_kg=90, allocation_run='ndola-run',
		)
		ndola_supplier = Supplier.objects.create(
			name='Ndola District Supplier', district='Ndola', latitude=-12.97,
			longitude=28.64, is_active=True,
		)
		ndola_dealer = AgroDealer.objects.create(
			name='Ndola District Dealer', district='Ndola', latitude=-12.99,
			longitude=28.65,
		)
		kitwe_supplier = Supplier.objects.create(
			name='Kitwe District Supplier', district='Kitwe', latitude=-12.8,
			longitude=28.2, is_active=True,
		)
		kitwe_dealer = AgroDealer.objects.create(
			name='Kitwe District Dealer', district='Kitwe', latitude=-12.82,
			longitude=28.22,
		)
		ndola_route = RoutePlan.objects.create(name='District test route')
		other_route = RoutePlan.objects.create(name='Other district route')
		SupplierDealerRoute.objects.create(
			route=ndola_route, supplier=ndola_supplier, agro_dealer=ndola_dealer, sequence=1,
		)
		SupplierDealerRoute.objects.create(
			route=other_route, supplier=kitwe_supplier, agro_dealer=kitwe_dealer, sequence=1,
		)
		RouteStop.objects.create(
			route=ndola_route,
			farmer=ndola_farmer, sequence=1,
		)
		RouteStop.objects.create(
			route=other_route,
			farmer=kitwe_farmer, sequence=1,
		)
		self.client.force_login(user)

		farmer_response = self.client.get(reverse('farmer_list'))
		forecast_response = self.client.get(reverse('forecast_list'))
		inventory_response = self.client.get(reverse('allocation_list'))
		route_response = self.client.get(reverse('route_list'))

		self.assertContains(farmer_response, 'Ndola Farmer')
		self.assertNotContains(farmer_response, 'Kitwe Farmer')
		# The page also carries the national seasonal rainfall map, which names
		# every district, so check the scoped demand forecasts themselves.
		self.assertEqual(
			{row['forecast'].district for row in forecast_response.context['forecast_rows']},
			{'Ndola'},
		)
		self.assertContains(inventory_response, 'Ndola')
		self.assertNotContains(inventory_response, 'Kitwe')
		self.assertContains(route_response, 'District test route')
		self.assertNotContains(route_response, 'Other district route')
