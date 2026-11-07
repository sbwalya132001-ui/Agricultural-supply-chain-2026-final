from datetime import datetime
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from pulp import LpMinimize, LpProblem, LpStatus, LpVariable, PULP_CBC_CMD, lpSum

from farmers.models import FarmerInputUsage
from forecasting.models import Forecast
from logistics.models import AgroDealer, Supplier

from .models import DealerInputAllocation, FarmerAllocation, InventoryAllocation
INPUT_STOCK_FIELDS = {
    'fertilizer_d': 'stock_fertilizer_d_kg',
    'fertilizer_urea': 'stock_fertilizer_urea_kg',
    'seed_maize': 'stock_seed_maize_kg',
    'seed_other': 'stock_seed_other_kg',
    'seed_soybeans': 'stock_seed_soybeans_kg',
    'seed_sunflower': 'stock_seed_sunflower_kg',
    'seed_popcorn': 'stock_seed_popcorn_kg',
}

def latest_forecasts():
    """Return one latest-season forecast for each district/input pair."""
    latest = {}
    for forecast in Forecast.objects.all():
        key = (forecast.district, forecast.input_type)
        current = latest.get(key)
        if current is None or forecast.forecast_season > current.forecast_season:
            latest[key] = forecast
    return list(latest.values())


def forecast_quantity_for_allocation(forecast, quantity_source='baseline'):
    """Return the quantity source selected for the inventory allocation run."""
    if quantity_source == 'zmd_scenario' and forecast.weather_scenario_quantity_kg is not None:
        return forecast.weather_scenario_quantity_kg
    if quantity_source == 'seas5_scenario' and forecast.seas5_scenario_quantity_kg is not None:
        return forecast.seas5_scenario_quantity_kg
    return forecast.allocation_quantity_kg


def latest_forecast_demand_totals(quantity_source='baseline'):
    """Sum the latest district forecasts into one quantity per input type."""
    totals = {input_type: Decimal('0.00') for input_type, _ in FarmerInputUsage.INPUT_TYPE_CHOICES}
    for forecast in latest_forecasts():
        totals[forecast.input_type] += forecast_quantity_for_allocation(forecast, quantity_source)
    return totals

def run_inventory_allocation(supply_dict, cost_dict, quantity_source='baseline'):
    """Allocate latest forecasts directly to dealers assigned to each district supplier."""
    forecasts = latest_forecasts()
    if not forecasts:
        return {
            'succeeded': [], 'supplier_allocations': [],
            'dealer_allocations': [], 'farmer_allocations': [],
            'skipped': [], 'error': 'No forecasts available. Run forecasts first.',
        }

    problem = LpProblem('Inventory_Allocation', LpMinimize)
    allocation_vars = {}
    unmet_vars = {}
    for forecast in forecasts:
        demand_quantity = forecast_quantity_for_allocation(forecast, quantity_source)
        key = (forecast.district, forecast.input_type)
        allocation_vars[key] = LpVariable(
            f'alloc_{forecast.district}_{forecast.input_type}',
            lowBound=0,
            upBound=float(demand_quantity),
        )
        unmet_vars[key] = LpVariable(
            f'unmet_{forecast.district}_{forecast.input_type}',
            lowBound=0,
        )

    # Satisfy as much demand as possible, then prefer lower-cost inputs.
    problem += lpSum(
        unmet_vars[key] * 100000 + allocation_vars[key] * float(cost_dict[key[1]])
        for key in allocation_vars
    ), 'Minimize_unmet_demand_then_cost'

    for forecast in forecasts:
        demand_quantity = forecast_quantity_for_allocation(forecast, quantity_source)
        key = (forecast.district, forecast.input_type)
        problem += (
            allocation_vars[key] + unmet_vars[key] == float(demand_quantity),
            f'Demand_{forecast.district}_{forecast.input_type}',
        )

    for input_type, available_qty in supply_dict.items():
        relevant = [
            allocation_vars[key] for key in allocation_vars if key[1] == input_type
        ]
        if relevant:
            problem += lpSum(relevant) <= float(available_qty), f'Supply_{input_type}'

        demand = sum(
            (forecast_quantity_for_allocation(forecast, quantity_source) for forecast in forecasts if forecast.input_type == input_type),
            Decimal('0'),
        )
        if available_qty >= demand * Decimal('0.8'):
            for forecast in forecasts:
                if forecast.input_type == input_type:
                    key = (forecast.district, forecast.input_type)
                    demand_quantity = forecast_quantity_for_allocation(forecast, quantity_source)
                    problem += allocation_vars[key] >= float(demand_quantity * Decimal('0.8'))

    try:
        problem.solve(PULP_CBC_CMD(msg=0))
    except Exception as exc:
        return {
            'succeeded': [], 'supplier_allocations': [],
            'dealer_allocations': [], 'farmer_allocations': [],
            'skipped': [], 'error': f'Optimization failed: {exc}',
        }
    status = LpStatus[problem.status]
    if status != 'Optimal':
        return {
            'succeeded': [], 'supplier_allocations': [],
            'dealer_allocations': [], 'farmer_allocations': [],
            'skipped': [], 'error': f'Optimization did not find an optimal solution: {status}.',
        }

    active_suppliers = {
        supplier.district: supplier
        for supplier in Supplier.objects.filter(is_active=True)
    }
    dealer_groups = {}
    for dealer in AgroDealer.objects.all():
        dealer_groups.setdefault(dealer.district, []).append(dealer)
    missing_distribution = [
        forecast.district for forecast in forecasts
        if forecast.district not in active_suppliers
        or not dealer_groups.get(forecast.district)
    ]
    if missing_distribution:
        districts = ', '.join(sorted(set(missing_distribution)))
        return {
            'succeeded': [], 'supplier_allocations': [],
            'dealer_allocations': [], 'farmer_allocations': [],
            'skipped': [],
            'error': f'Each forecast district needs an active supplier and at least one agro-dealer: {districts}.',
        }

    run_id = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    succeeded = []
    supplier_allocations = []
    dealer_allocations = []
    farmer_allocations = []
    skipped = []

    with transaction.atomic():
        for supplier in Supplier.objects.all():
            supplier.current_stock_kg = 0
            for field in INPUT_STOCK_FIELDS.values():
                setattr(supplier, field, 0)
            supplier.save(update_fields=['current_stock_kg', *INPUT_STOCK_FIELDS.values()])
        for forecast in forecasts:
            key = (forecast.district, forecast.input_type)
            variable = allocation_vars[key]
            if variable.varValue is None or variable.varValue <= 0:
                skipped.append(key)
                continue

            quantity = Decimal(str(variable.varValue)).quantize(Decimal('0.01'))
            cost_per_unit = cost_dict[forecast.input_type]
            allocation = InventoryAllocation.objects.create(
                district=forecast.district,
                input_type=forecast.input_type,
                forecast=forecast,
                allocated_quantity_kg=quantity,
                cost_per_unit=cost_per_unit,
                total_cost=quantity * cost_per_unit,
                allocation_run=run_id,
            )
            succeeded.append(allocation)

            supplier = active_suppliers[forecast.district]
            supplier_allocations.append({
                'supplier': supplier,
                'forecast': forecast,
                'input_type': forecast.input_type,
                'quantity_kg': quantity,
                'allocation_run': run_id,
            })

            farmers = list(
                FarmerInputUsage.objects.filter(
                    farmer__district__iexact=forecast.district,
                    input_type=forecast.input_type,
                ).values('farmer_id').annotate(total=Sum('quantity_kg'))
            )
            total_usage = sum((row['total'] for row in farmers), Decimal('0'))
            remaining = quantity
            dealers = sorted(dealer_groups[forecast.district], key=lambda dealer: dealer.id)
            dealer_totals = {dealer.id: Decimal('0') for dealer in dealers}
            for index, row in enumerate(farmers):
                if index == len(farmers) - 1:
                    farmer_quantity = remaining
                elif total_usage:
                    farmer_quantity = (quantity * row['total'] / total_usage).quantize(Decimal('0.01'))
                    remaining -= farmer_quantity
                else:
                    farmer_quantity = (quantity / len(farmers)).quantize(Decimal('0.01'))
                    remaining -= farmer_quantity
                farmer_allocations.append(FarmerAllocation.objects.create(
                    farmer_id=row['farmer_id'],
                    agro_dealer=dealers[index % len(dealers)],
                    forecast=forecast,
                    input_type=forecast.input_type,
                    quantity_kg=farmer_quantity,
                    allocation_run=run_id,
                ))
                dealer_totals[dealers[index % len(dealers)].id] += farmer_quantity

            if not farmers:
                dealer_quantity = (quantity / len(dealers)).quantize(Decimal('0.01'))
                dealer_totals = {dealer.id: dealer_quantity for dealer in dealers}
                dealer_totals[dealers[0].id] += quantity - sum(dealer_totals.values())
            for dealer in dealers:
                dealer_amount = dealer_totals[dealer.id]
                dealer_allocations.append(DealerInputAllocation.objects.create(
                    supplier=supplier,
                    forecast=forecast,
                    input_type=forecast.input_type,
                    agro_dealer=dealer,
                    quantity_kg=dealer_amount,
                    allocation_run=run_id,
                ))

            supplier.current_stock_kg += quantity
            stock_field = INPUT_STOCK_FIELDS[forecast.input_type]
            setattr(supplier, stock_field, getattr(supplier, stock_field) + quantity)
            supplier.save(update_fields=['current_stock_kg', stock_field])

    return {
        'succeeded': succeeded,
        'supplier_allocations': supplier_allocations,
        'dealer_allocations': dealer_allocations,
        'farmer_allocations': farmer_allocations,
        'skipped': skipped,
        'error': None,
    }


