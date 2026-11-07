from decimal import Decimal
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from geopy.distance import geodesic

from inventory.models import DealerInputAllocation

from .models import AgroDealer, RoutePlan, Supplier, SupplierDealerRoute


def _mapbox_matrix(coordinates):
    """Return Mapbox driving distances and durations for all coordinates."""
    token = getattr(settings, 'MAPBOX_ACCESS_TOKEN', '')
    if not token:
        return None

    coordinate_string = ';'.join(
        f'{longitude},{latitude}' for latitude, longitude in coordinates
    )
    url = (
        'https://api.mapbox.com/directions-matrix/v1/mapbox/driving/'
        f'{coordinate_string}?annotations=distance,duration&access_token={token}'
    )
    try:
        with urlopen(Request(url, headers={'Accept': 'application/json'}), timeout=15) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError):
        return None

    if payload.get('code') != 'Ok':
        return None
    return payload


def _mapbox_directions(start_coordinates, end_coordinates):
    """Return road-following GeoJSON coordinates for one driving leg."""
    token = getattr(settings, 'MAPBOX_ACCESS_TOKEN', '')
    if not token:
        return None
    coordinate_string = ';'.join(
        f'{longitude},{latitude}'
        for latitude, longitude in (start_coordinates, end_coordinates)
    )
    url = (
        'https://api.mapbox.com/directions/v5/mapbox/driving/'
        f'{coordinate_string}?geometries=geojson&overview=full&access_token={token}'
    )
    try:
        with urlopen(Request(url, headers={'Accept': 'application/json'}), timeout=15) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError):
        return None
    if payload.get('code') != 'Ok' or not payload.get('routes'):
        return None
    geometry = payload['routes'][0].get('geometry', {}).get('coordinates') or None
    if not geometry:
        return None
    return [
        [start_coordinates[1], start_coordinates[0]],
        *geometry[1:-1],
        [end_coordinates[1], end_coordinates[0]],
    ]


def _dealer_to_supplier_leg(dealer, supplier):
    """Calculate one independent agro-dealer-to-supplier route leg."""
    dealer_coordinates = (dealer.latitude, dealer.longitude)
    supplier_coordinates = (supplier.latitude, supplier.longitude)
    matrix = _mapbox_matrix([dealer_coordinates, supplier_coordinates])
    distance_matrix = matrix.get('distances') if matrix else None
    mapbox_distance = (
        distance_matrix[0][1]
        if distance_matrix and distance_matrix[0][1] is not None
        else None
    )
    distance_meters = mapbox_distance if mapbox_distance is not None else geodesic(
        dealer_coordinates,
        supplier_coordinates,
    ).meters
    road_geometry = _mapbox_directions(dealer_coordinates, supplier_coordinates)
    return distance_meters / 1000, road_geometry or [], mapbox_distance is not None


def build_delivery_route(start_coordinates=None, district=None, planned_delivery_date=None, vehicle_identifier=''):
    """Build and save an independent agro-dealer-to-supplier trip per allocation."""
    latest_run = DealerInputAllocation.objects.order_by('-created_at').values_list('allocation_run', flat=True).first()
    if not latest_run:
        return {
            'route': None,
            'stop_count': 0,
            'distribution_leg_count': 0,
            'distance_km': 0,
            'mapbox_used': False,
            'error': 'Run an inventory allocation before generating a distribution route.',
        }

    dealer_allocations = list(
        DealerInputAllocation.objects.filter(
            allocation_run=latest_run,
            quantity_kg__gt=0,
            supplier__is_active=True,
        ).select_related('supplier', 'agro_dealer')
    )
    if district:
        dealer_allocations = [
            allocation for allocation in dealer_allocations
            if allocation.supplier.district.casefold() == district.casefold()
        ]
    if not dealer_allocations:
        return {
            'route': None,
            'stop_count': 0,
            'distribution_leg_count': 0,
            'distance_km': 0,
            'mapbox_used': False,
            'error': 'The latest allocation has no positive dealer quantities assigned to an active supplier for this district.',
        }

    if start_coordinates is None:
        start_coordinates = (dealer_allocations[0].supplier.latitude, dealer_allocations[0].supplier.longitude)

    total_distance = 0
    mapbox_used = False
    route = RoutePlan.objects.create(
        start_latitude=start_coordinates[0],
        start_longitude=start_coordinates[1],
        total_distance_km=Decimal(str(round(total_distance, 2))),
        planned_delivery_date=planned_delivery_date,
        vehicle_identifier=vehicle_identifier,
        allocation_run=latest_run,
    )

    unique_allocations = {}
    for allocation in dealer_allocations:
        key = (allocation.supplier_id, allocation.agro_dealer_id)
        if key not in unique_allocations:
            unique_allocations[key] = {
                'supplier': allocation.supplier,
                'agro_dealer': allocation.agro_dealer,
                'quantity_kg': Decimal('0'),
            }
        unique_allocations[key]['quantity_kg'] += allocation.quantity_kg

    distribution_legs = []
    distribution_distance = 0
    for sequence, allocation in enumerate(unique_allocations.values(), start=1):
        dealer = allocation['agro_dealer']
        supplier = allocation['supplier']
        if dealer.latitude is None or dealer.longitude is None:
            continue
        distance_km, road_geometry, used_mapbox = _dealer_to_supplier_leg(dealer, supplier)
        mapbox_used = mapbox_used or used_mapbox
        distribution_legs.append(SupplierDealerRoute(
            route=route,
            supplier=supplier,
            agro_dealer=dealer,
            sequence=sequence,
            allocated_quantity_kg=allocation['quantity_kg'],
            distance_from_previous_km=Decimal(str(round(distance_km, 2))),
            road_geometry=road_geometry or [],
        ))
        distribution_distance += distance_km
    if not distribution_legs:
        route.delete()
        return {
            'route': None,
            'stop_count': 0,
            'distribution_leg_count': 0,
            'distance_km': 0,
            'mapbox_used': False,
            'error': 'No allocated agro-dealer with valid coordinates is available for a supplier route.',
        }
    SupplierDealerRoute.objects.bulk_create(distribution_legs)
    total_distance += distribution_distance
    route.total_distance_km = Decimal(str(round(total_distance, 2)))
    route.save(update_fields=['total_distance_km'])

    return {
        'route': route,
        'stop_count': 0,
        'distribution_leg_count': len(distribution_legs),
        'distance_km': round(total_distance, 2),
        'mapbox_used': mapbox_used,
        'error': None,
    }
