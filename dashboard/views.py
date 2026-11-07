from decimal import Decimal
from django.db.models import Case, DecimalField, F, Sum, When
from django.shortcuts import render
import json

from farmers.models import Farmer
from forecasting.models import Forecast
from inventory.models import InventoryAllocation
from logistics.models import AgroDealer, RoutePlan, Supplier
from accounts.decorators import (
    ROLE_DEALER,
    ROLE_DISTRICT,
    ROLE_MINISTRY,
    ROLE_SUPPLIER,
    get_user_district,
    role_required,
)


@role_required(ROLE_MINISTRY, ROLE_DISTRICT, ROLE_SUPPLIER, ROLE_DEALER)
def home(request):
    district = get_user_district(request.user)
    allocation_queryset = InventoryAllocation.objects
    if district:
        allocation_queryset = allocation_queryset.filter(district__iexact=district)
    latest_allocation_run = (
        allocation_queryset
        .order_by('-allocation_run')
        .values_list('allocation_run', flat=True)
        .first()
    )
    latest_allocations = InventoryAllocation.objects.filter(
        allocation_run=latest_allocation_run,
    ) if latest_allocation_run else InventoryAllocation.objects.none()
    if district:
        latest_allocations = latest_allocations.filter(district__iexact=district)
    active_suppliers = Supplier.objects.filter(is_active=True)
    if district:
        active_suppliers = active_suppliers.filter(district__iexact=district)
    available_dealers = AgroDealer.objects.all()
    if district:
        available_dealers = available_dealers.filter(district__iexact=district)

    verified_stock_dealers = available_dealers.filter(
        supplier_dispatches__receipts__isnull=False,
    ).distinct()
    total_available_stock = verified_stock_dealers.aggregate(
        total=Sum('stock_quantity_kg'),
    )['total'] or Decimal('0')
    latest_route = RoutePlan.objects.filter(distribution_legs__supplier__district__iexact=district).distinct().first() if district else RoutePlan.objects.first()
    distribution_legs = latest_route.distribution_legs.filter(supplier__district__iexact=district) if latest_route and district else latest_route.distribution_legs.all() if latest_route else []
    district_allocations = list(
        latest_allocations.values('district')
        .annotate(total=Sum('allocated_quantity_kg'))
        .order_by('district')
    )
    forecast_queryset = Forecast.objects.filter(district__iexact=district) if district else Forecast.objects
    forecast_baseline_total = forecast_queryset.aggregate(
        total=Sum(Case(
            When(
                baseline_predicted_quantity_kg__isnull=False,
                then=F('baseline_predicted_quantity_kg'),
            ),
            default=F('predicted_quantity_kg'),
            output_field=DecimalField(max_digits=10, decimal_places=2),
        )),
    )['total'] or Decimal('0')

    context = {
        'kpis': {
            'registered_farmers': Farmer.objects.filter(district__iexact=district).count() if district else Farmer.objects.count(),
            'forecast_demand_kg': forecast_baseline_total,
            'allocated_inputs_kg': latest_allocations.aggregate(
                total=Sum('allocated_quantity_kg'),
            )['total'] or 0,
            'total_available_stock_kg': total_available_stock,
            'active_suppliers': active_suppliers.count(),
            'agro_dealers': AgroDealer.objects.filter(district__iexact=district).count() if district else AgroDealer.objects.count(),
            'route_legs': distribution_legs.count() if latest_route else 0,
            'distribution_legs': distribution_legs.count() if latest_route else 0,
        },
        'district_allocation_labels': json.dumps(
            [item['district'] for item in district_allocations],
        ),
        'district_allocation_values': json.dumps(
            [float(item['total']) for item in district_allocations],
        ),
    }
    return render(request, 'dashboard/home.html', context)
