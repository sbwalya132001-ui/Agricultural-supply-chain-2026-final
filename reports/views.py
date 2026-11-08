import csv

from django.http import HttpResponse
from django.shortcuts import render

from accounts.decorators import (
    ROLE_DEALER,
    ROLE_DISTRICT,
    ROLE_MINISTRY,
    ROLE_SUPPLIER,
    get_user_district,
    role_required,
)
from farmers.models import Farmer
from forecasting.models import Forecast
from inventory.models import InventoryAllocation
from logistics.models import RoutePlan


REPORT_ROLES = (ROLE_MINISTRY, ROLE_DISTRICT, ROLE_SUPPLIER, ROLE_DEALER)


@role_required(*REPORT_ROLES)
def report_export(request):
    district = get_user_district(request.user)
    return render(
        request,
        'reports/report_export.html',
        {'district': district},
    )


def csv_response(filename, headings, rows):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(headings)
    writer.writerows(rows)
    return response


def district_filter(queryset, district, field='district'):
    return queryset.filter(**{f'{field}__iexact': district}) if district else queryset


@role_required(*REPORT_ROLES)
def export_farmers(request):
    district = get_user_district(request.user)
    farmers = district_filter(Farmer.objects.all(), district)
    rows = (
        (
            farmer.national_id,
            farmer.first_name,
            farmer.last_name,
            farmer.phone_number,
            farmer.district,
            farmer.ward,
            farmer.farm_size_hectares,
            farmer.get_primary_crop_display(),
            farmer.date_registered,
        )
        for farmer in farmers
    )
    return csv_response(
        'farmers.csv',
        ('National ID', 'First name', 'Last name', 'Phone number', 'District', 'Ward', 'Farm size (ha)', 'Primary crop', 'Date registered'),
        rows,
    )


@role_required(*REPORT_ROLES)
def export_forecasts(request):
    district = get_user_district(request.user)
    forecasts = district_filter(Forecast.objects.all(), district)
    rows = (
        (
            forecast.district,
            forecast.get_input_type_display(),
            forecast.forecast_season,
            forecast.allocation_quantity_kg,
            forecast.seasons_used,
            forecast.model_used,
            forecast.date_generated,
        )
        for forecast in forecasts
    )
    return csv_response(
        'forecasts.csv',
        ('District', 'Input type', 'Forecast season', 'Allocation demand (kg)', 'Seasons used', 'Model', 'Date generated'),
        rows,
    )


@role_required(*REPORT_ROLES)
def export_allocations(request):
    district = get_user_district(request.user)
    allocations = district_filter(InventoryAllocation.objects.select_related('forecast'), district)
    rows = (
        (
            allocation.allocation_run,
            allocation.district,
            allocation.get_input_type_display(),
            allocation.allocated_quantity_kg,
            allocation.cost_per_unit,
            allocation.total_cost,
            allocation.date_allocated,
        )
        for allocation in allocations
    )
    return csv_response(
        'inventory_allocations.csv',
        ('Allocation run', 'District', 'Input type', 'Allocated quantity (kg)', 'Cost per unit', 'Total cost', 'Date allocated'),
        rows,
    )


@role_required(*REPORT_ROLES)
def export_routes(request):
    district = get_user_district(request.user)
    routes = RoutePlan.objects.all()
    if district:
        routes = routes.filter(
            distribution_legs__supplier__district__iexact=district,
        ).distinct()
    rows = (
        (
            route.name,
            route.status,
            route.planned_delivery_date,
            route.vehicle_identifier,
            route.allocation_run,
            route.total_distance_km,
            route.created_at,
        )
        for route in routes
    )
    return csv_response(
        'logistics_routes.csv',
        ('Route name', 'Status', 'Planned delivery date', 'Vehicle', 'Allocation run', 'Total distance (km)', 'Created at'),
        rows,
    )
