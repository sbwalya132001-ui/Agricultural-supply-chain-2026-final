from django.contrib import messages
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.db.models import Prefetch, Sum
from django.db.models import Q
from django import forms

from farmers.forms import DeliveryConfirmationForm
from farmers.models import DeliveryConfirmation
from inventory.models import DealerInputAllocation, DealerStockReceipt, FarmerAllocation, SupplierDispatch
from inventory.services import INPUT_STOCK_FIELDS
from .models import AgroDealer, RoutePlan, RouteStop, Supplier, SupplierDealerRoute
from .services import build_delivery_route


class RouteGenerationForm(forms.Form):
	planned_delivery_date = forms.DateField(
		required=True,
		widget=forms.DateInput(attrs={'type': 'date'}),
	)
	vehicle_identifier = forms.CharField(max_length=80, required=False)


class DealerStockReceiptForm(forms.Form):
	quantity_kg = forms.DecimalField(
		max_digits=12,
		decimal_places=2,
		min_value=0.01,
		widget=forms.NumberInput(attrs={
			'class': 'form-control form-control-sm',
			'min': '0.01',
			'step': '0.01',
			'required': True,
		}),
	)
from accounts.decorators import (
	ROLE_DEALER,
	ROLE_DISTRICT,
	ROLE_MINISTRY,
	ROLE_SUPPLIER,
	get_user_district,
	get_user_role,
	role_required,
)


@role_required(ROLE_MINISTRY, ROLE_DISTRICT, ROLE_SUPPLIER, ROLE_DEALER)
def route_list(request):
	district = get_user_district(request.user)
	route_queryset = RoutePlan.objects.all()
	stop_queryset = RouteStop.objects.select_related('farmer')
	leg_queryset = SupplierDealerRoute.objects.select_related('supplier', 'agro_dealer')
	supplier_queryset = Supplier.objects.filter(is_active=True)
	dealer_queryset = AgroDealer.objects.all()
	if get_user_role(request.user) == ROLE_DEALER:
		dealer = getattr(request.user, 'agrodealer_profile', None)
		if dealer:
			dealer_queryset = dealer_queryset.filter(pk=dealer.pk)
			route_queryset = route_queryset.filter(distribution_legs__agro_dealer=dealer).distinct()
			stop_queryset = stop_queryset.filter(agro_dealer=dealer).distinct()
			leg_queryset = leg_queryset.filter(agro_dealer=dealer)
	if district:
		supplier_queryset = supplier_queryset.filter(district__iexact=district)
		dealer_queryset = dealer_queryset.filter(district__iexact=district)
		route_queryset = route_queryset.filter(distribution_legs__supplier__district__iexact=district).distinct()
		stop_queryset = stop_queryset.filter(farmer__district__iexact=district)
		leg_queryset = leg_queryset.filter(supplier__district__iexact=district)
	routes = route_queryset.prefetch_related(
		Prefetch('stops', queryset=stop_queryset.prefetch_related('input_items'), to_attr='scoped_stops'),
		Prefetch('distribution_legs', queryset=leg_queryset, to_attr='scoped_distribution_legs'),
	)
	latest_route = routes.first()
	map_data = {'routeStops': [], 'inputSuppliers': [], 'agroDealers': [], 'distributionLegs': []}
	route_legs = []
	if latest_route:
		map_data['routeStops'] = [
			{
				'sequence': stop.sequence,
				'name': f'{stop.farmer.first_name} {stop.farmer.last_name}',
				'district': stop.farmer.district,
				'coordinates': [stop.farmer.longitude, stop.farmer.latitude],
				'geometry': stop.road_geometry,
			}
			for stop in latest_route.scoped_stops
		]
		route_legs = latest_route.scoped_distribution_legs
		map_data['distributionLegs'] = [
			{
				'supplier': leg.supplier.name,
				'dealer': leg.agro_dealer.name,
				'coordinates': [
					[leg.agro_dealer.longitude, leg.agro_dealer.latitude],
					[leg.supplier.longitude, leg.supplier.latitude],
				],
				'geometry': leg.road_geometry or [],
			}
			for leg in route_legs
		]
	map_data['inputSuppliers'] = [
		{
			'name': supplier.name,
			'district': supplier.district,
			'coordinates': [supplier.longitude, supplier.latitude],
		}
		for supplier in supplier_queryset.order_by('district', 'id')
	]
	for leg in route_legs:
		if not any(supplier['coordinates'] == [leg.supplier.longitude, leg.supplier.latitude] for supplier in map_data['inputSuppliers']):
			map_data['inputSuppliers'].append({
				'name': leg.supplier.name,
				'district': leg.supplier.district,
				'coordinates': [leg.supplier.longitude, leg.supplier.latitude],
			})
	map_data['agroDealers'] = [
		{
			'name': dealer.name,
			'district': dealer.district,
			'stock': f'{dealer.stock_quantity_kg:.2f}',
			'coordinates': [dealer.longitude, dealer.latitude],
		}
		for dealer in dealer_queryset.order_by('district', 'id')
	]
	for leg in route_legs:
		if not any(item['name'] == leg.agro_dealer.name and item['district'] == leg.agro_dealer.district for item in map_data['agroDealers']):
			map_data['agroDealers'].append({
				'name': leg.agro_dealer.name,
				'district': leg.agro_dealer.district,
				'stock': f'{leg.agro_dealer.stock_quantity_kg:.2f}',
				'coordinates': [leg.agro_dealer.longitude, leg.agro_dealer.latitude],
			})
	return render(request, 'logistics/route_list.html', {
		'routes': routes,
		'latest_route': latest_route,
		'suppliers': Supplier.objects.filter(district__iexact=district) if district else Supplier.objects.all(),
		'agro_dealers': dealer_queryset,
		'mapbox_token': settings.MAPBOX_ACCESS_TOKEN,
		'map_data': map_data,
	})


@role_required(ROLE_DEALER)
def dealer_portal(request):
	dealer = getattr(request.user, 'agrodealer_profile', None)
	if dealer is None:
		messages.warning(
			request,
			'This agro-dealer account is not linked to a dealer profile yet. Please contact the system admin to assign the correct dealer record.',
		)
		return redirect('route_list')
	latest_route = (
		RoutePlan.objects.filter(
			distribution_legs__agro_dealer=dealer,
		)
		.order_by('-created_at', '-pk')
		.first()
	)
	dealer_routes = []
	farmer_allocations = FarmerAllocation.objects.none()
	if latest_route:
		legs = (
			latest_route.distribution_legs.filter(agro_dealer=dealer)
			.select_related('route', 'supplier', 'agro_dealer')
			.order_by('sequence')
		)
		for leg in legs:
			dealer_routes.append({
				'leg': leg,
				'route': latest_route,
				'supplier': leg.supplier,
			})
		farmer_allocations = (
			FarmerAllocation.objects.filter(
				agro_dealer=dealer,
				allocation_run=latest_route.allocation_run,
			)
			.select_related('farmer', 'forecast')
			.order_by('farmer__last_name', 'farmer__first_name', 'input_type')
		)
	dealer_allocations = (
		DealerInputAllocation.objects.filter(agro_dealer=dealer)
		.select_related('supplier', 'forecast')
		.order_by('-created_at', 'input_type')
	)
	pending_receipts = list(
		SupplierDispatch.objects.filter(agro_dealer=dealer, received_at__isnull=True)
		.select_related('supplier')
		.annotate(received_quantity=Sum('receipts__quantity_kg'))
		.order_by('dispatched_at', 'pk')
	)
	for dispatch in pending_receipts:
		dispatch.received_quantity = dispatch.received_quantity or 0
		dispatch.remaining_quantity = dispatch.quantity_kg - dispatch.received_quantity
	return render(request, 'logistics/dealer_portal.html', {
		'dealer': dealer,
		'dealer_routes': dealer_routes,
		'farmer_allocations': farmer_allocations,
		'dealer_allocations': dealer_allocations,
		'pending_receipts': pending_receipts,
	})


@role_required(ROLE_DEALER)
@require_POST
def dealer_confirm_stock_receipt(request, dispatch_id):
	dealer = getattr(request.user, 'agrodealer_profile', None)
	if dealer is None:
		messages.warning(request, 'This agro-dealer account is not linked to a dealer profile yet.')
		return redirect('dealer_portal')

	form = DealerStockReceiptForm(request.POST)
	if not form.is_valid():
		messages.error(request, 'Enter a collected quantity greater than zero, using up to two decimal places.')
		return redirect('dealer_portal')

	with transaction.atomic():
		dispatch = get_object_or_404(
			SupplierDispatch.objects.select_for_update(),
			pk=dispatch_id,
			agro_dealer=dealer,
			received_at__isnull=True,
		)
		received_quantity = dispatch.receipts.aggregate(total=Sum('quantity_kg'))['total'] or 0
		remaining_quantity = dispatch.quantity_kg - received_quantity
		quantity = form.cleaned_data['quantity_kg']
		if quantity > remaining_quantity:
			messages.error(
				request,
				f'Received quantity cannot exceed the remaining dispatched quantity ({remaining_quantity:.2f} kg).',
			)
			return redirect('dealer_portal')

		locked_dealer = AgroDealer.objects.select_for_update().get(pk=dealer.pk)
		stock_field = INPUT_STOCK_FIELDS[dispatch.input_type]
		setattr(locked_dealer, stock_field, getattr(locked_dealer, stock_field) + quantity)
		locked_dealer.stock_quantity_kg += quantity
		locked_dealer.save(update_fields=['stock_quantity_kg', stock_field])
		DealerStockReceipt.objects.create(
			dispatch=dispatch,
			quantity_kg=quantity,
			received_by=request.user,
		)
		if quantity == remaining_quantity:
			dispatch.received_by = request.user
			dispatch.received_at = timezone.now()
			dispatch.save(update_fields=['received_by', 'received_at'])

	messages.success(
		request,
		f'Receipt recorded: {quantity:.2f} kg of {dispatch.get_input_type_display()} added to your stock.',
	)
	return redirect('dealer_portal')


@role_required(ROLE_DEALER)
@require_POST
def dealer_confirm_farmer_collection(request, allocation_id):
	dealer = getattr(request.user, 'agrodealer_profile', None)
	if dealer is None:
		messages.warning(request, 'This agro-dealer account is not linked to a dealer profile yet.')
		return redirect('dealer_portal')

	with transaction.atomic():
		allocation = get_object_or_404(
			FarmerAllocation.objects.select_for_update(),
			pk=allocation_id,
			agro_dealer=dealer,
			collection_status='awaiting_collection',
		)
		locked_dealer = AgroDealer.objects.select_for_update().get(pk=dealer.pk)
		stock_field = INPUT_STOCK_FIELDS[allocation.input_type]
		available_input_stock = getattr(locked_dealer, stock_field)
		if allocation.quantity_kg > available_input_stock:
			messages.error(
				request,
				f'Collection cannot be confirmed: only {available_input_stock:.2f} kg of {allocation.get_input_type_display()} is available.',
			)
			return redirect('dealer_portal')

		setattr(locked_dealer, stock_field, available_input_stock - allocation.quantity_kg)
		locked_dealer.stock_quantity_kg -= allocation.quantity_kg
		locked_dealer.save(update_fields=['stock_quantity_kg', stock_field])
		allocation.collection_status = 'collected'
		allocation.collected_at = timezone.now()
		allocation.confirmed_by = request.user
		allocation.save(update_fields=['collection_status', 'collected_at', 'confirmed_by'])

	messages.success(
		request,
		f'Collection confirmed for {allocation.farmer}: {allocation.quantity_kg:.2f} kg deducted from stock.',
	)
	return redirect('dealer_portal')


@role_required(ROLE_DEALER)
def dealer_confirm_delivery(request, stop_id):
	dealer = getattr(request.user, 'agrodealer_profile', None)
	if dealer is None:
		messages.warning(request, 'This agro-dealer account is not linked to a dealer profile yet.')
		return redirect('route_list')
	route_stop = get_object_or_404(
		RouteStop.objects.filter(
			Q(agro_dealer=dealer)
			| Q(agro_dealer__isnull=True, route__distribution_legs__agro_dealer=dealer)
		)
		.select_related('route', 'farmer')
		.distinct(),
		pk=stop_id,
	)
	confirmation = DeliveryConfirmation.objects.filter(route_stop=route_stop).first()
	if request.method == 'POST':
		form = DeliveryConfirmationForm(
			request.POST,
			instance=confirmation,
			confirmation_source='dealer',
		)
		if form.is_valid():
			form.instance.route_stop = route_stop
			form.instance.source = 'dealer'
			form.save()
			route_stop.status = 'delivered' if form.cleaned_data['status'] == 'delivered' else 'issue'
			route_stop.save(update_fields=['status'])
			if not route_stop.route.stops.exclude(status='delivered').exists():
				route_stop.route.status = 'completed'
				route_stop.route.save(update_fields=['status'])
			elif route_stop.route.status == 'planned':
				route_stop.route.status = 'in_progress'
				route_stop.route.save(update_fields=['status'])
			messages.success(request, 'Delivery recorded successfully.')
			return redirect('dealer_portal')
	else:
		form = DeliveryConfirmationForm(
			instance=confirmation,
			confirmation_source='dealer',
		)
	return render(request, 'logistics/dealer_confirm_delivery.html', {
		'dealer': dealer,
		'route_stop': route_stop,
		'form': form,
	})


@role_required(ROLE_MINISTRY, ROLE_DISTRICT)
def run_route(request):
	district = get_user_district(request.user)
	if request.method == 'POST':
		supplier_exists = Supplier.objects.filter(is_active=True, district__iexact=district).exists() if district else Supplier.objects.filter(is_active=True).exists()
		dealer_exists = AgroDealer.objects.filter(district__iexact=district).exists() if district else AgroDealer.objects.exists()
		if not supplier_exists or not dealer_exists:
			messages.error(request, 'The selected district needs an active supplier and at least one agro-dealer before route generation.')
			return redirect('route_list')
		form = RouteGenerationForm(request.POST)
		if not form.is_valid():
			return render(request, 'logistics/run_route.html', {'form': form})
		result = build_delivery_route(
			district=district,
			planned_delivery_date=form.cleaned_data['planned_delivery_date'],
			vehicle_identifier=form.cleaned_data['vehicle_identifier'],
		)
		if result['error']:
			messages.error(request, result['error'])
		else:
			messages.success(
				request,
				f"Route generated with {result['distribution_leg_count']} agro-dealer-to-input-supplier legs and "
				f"{result['distance_km']:.2f} km total distance.",
			)
		return redirect('route_list')

	return render(request, 'logistics/run_route.html', {'form': RouteGenerationForm()})
