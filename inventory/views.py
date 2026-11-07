from django.contrib import messages
from django.db import transaction
from django.shortcuts import render, redirect
from django.shortcuts import get_object_or_404
from django.db.models import Sum

from .forms import InventoryAllocationForm, SupplierDispatchForm
from .models import DealerInputAllocation, InventoryAllocation, SupplierDispatch
from .services import (
    INPUT_STOCK_FIELDS,
    latest_forecast_demand_totals,
    run_inventory_allocation,
)
from logistics.models import AgroDealer, Supplier
from accounts.decorators import (
    ROLE_DISTRICT,
    ROLE_MINISTRY,
    ROLE_SUPPLIER,
    get_user_district,
    role_required,
)


@role_required(ROLE_MINISTRY, ROLE_DISTRICT, ROLE_SUPPLIER)
def allocation_list(request):
    """
    List all allocations, grouped by most recent run.
    """
    allocations = InventoryAllocation.objects.all()
    district = get_user_district(request.user)
    if district:
        allocations = allocations.filter(district__iexact=district)
    
    # Get unique runs (allocation_run timestamps)
    scoped_allocations = InventoryAllocation.objects.all()
    if district:
        scoped_allocations = scoped_allocations.filter(district__iexact=district)
    runs = scoped_allocations.values_list('allocation_run', flat=True).distinct().order_by('-allocation_run')
    
    # Summary stats
    total_allocated = scoped_allocations.aggregate(Sum('allocated_quantity_kg'))['allocated_quantity_kg__sum'] or 0
    total_cost = scoped_allocations.aggregate(Sum('total_cost'))['total_cost__sum'] or 0
    
    return render(request, 'inventory/allocation_list.html', {
        'allocations': allocations,
        'runs': runs,
        'total_allocated': total_allocated,
        'total_cost': total_cost,
    })


@role_required(ROLE_MINISTRY)
def run_allocation(request):
    """
    Trigger a new inventory allocation optimization run.
    Uses forecasts as demand input.
    """
    supply_totals = latest_forecast_demand_totals()

    def build_context(form):
        quantity_source = form.data.get('allocation_quantity_source', form.initial.get('allocation_quantity_source', 'baseline'))
        selected_totals = latest_forecast_demand_totals(quantity_source=quantity_source)
        totals_by_source = {
            source: latest_forecast_demand_totals(quantity_source=source)
            for source, _ in InventoryAllocationForm.QUANTITY_SOURCE_CHOICES
        }
        source_totals = {
            input_type: {source: totals[input_type] for source, totals in totals_by_source.items()}
            for input_type in InventoryAllocationForm.INPUT_TYPES
        }
        allocation_items = []
        for input_type in InventoryAllocationForm.INPUT_TYPES:
            allocation_items.append({
                'label': InventoryAllocationForm.INPUT_LABELS[input_type],
                'quantity': selected_totals[input_type],
                'quantity_by_source': source_totals[input_type],
                'supply': form[f'supply_{input_type}'],
                'cost': form[f'cost_{input_type}'],
            })
        return {
            'form': form,
            'allocation_items': allocation_items,
            'total_forecast_quantity': sum(selected_totals.values()),
            'has_forecasts': any(selected_totals.values()),
        }

    if request.method == 'POST':
        quantity_source = request.POST.get('allocation_quantity_source') or 'baseline'
        supply_totals = latest_forecast_demand_totals(quantity_source=quantity_source)
        form = InventoryAllocationForm(request.POST, supply_totals=supply_totals)
        if not form.is_valid():
            return render(request, 'inventory/run_allocation.html', build_context(form))
        quantity_source = form.cleaned_data.get('allocation_quantity_source') or 'baseline'
        supply_dict = {
            input_type: latest_forecast_demand_totals(quantity_source=quantity_source)[input_type]
            for input_type in form.INPUT_TYPES
        }
        cost_dict = {
            input_type: form.cleaned_data[f'cost_{input_type}']
            for input_type in form.INPUT_TYPES
        }
        results = run_inventory_allocation(supply_dict, cost_dict, quantity_source=quantity_source)
        
        if results['error']:
            messages.error(request, f"Allocation failed: {results['error']}")
        else:
            messages.success(
                request,
                f"Allocation run complete: {len(results['succeeded'])} allocations generated."
            )
            if results['skipped']:
                skipped_desc = ', '.join(f"{d}/{i}" for d, i in results['skipped'])
                messages.warning(
                    request,
                    f"Skipped (no solution): {skipped_desc}"
                )
        
        return redirect('allocation_list')
    
    # GET: show a confirmation page
    form = InventoryAllocationForm(supply_totals=supply_totals)
    return render(request, 'inventory/run_allocation.html', build_context(form))


@role_required(ROLE_SUPPLIER)
def supplier_dispatch(request):
    district = get_user_district(request.user)
    if request.method == 'POST':
        form = SupplierDispatchForm(request.POST, district_scope=district)
        if form.is_valid():
            supplier_queryset = Supplier.objects.filter(
                pk=form.cleaned_data['supplier'].pk,
                is_active=True,
            )
            if district:
                supplier_queryset = supplier_queryset.filter(district__iexact=district)
            supplier = supplier_queryset.select_for_update().first()

            dealer_queryset = AgroDealer.objects.filter(pk=form.cleaned_data['agro_dealer'].pk)
            if district:
                dealer_queryset = dealer_queryset.filter(district__iexact=district)
            dealer = dealer_queryset.first()

            if supplier is None:
                form.add_error('supplier', 'No active supplier matches the selected supplier record for this account.')
            elif dealer is None:
                form.add_error('agro_dealer', 'The selected agro-dealer is not available in the current supplier district.')
            else:
                quantity = form.cleaned_data['quantity_kg']
                stock_field = INPUT_STOCK_FIELDS[form.cleaned_data['input_type']]
                input_stock = getattr(supplier, stock_field)
                latest_allocation_run = (
                    DealerInputAllocation.objects.filter(
                        supplier=supplier,
                        agro_dealer=dealer,
                        input_type=form.cleaned_data['input_type'],
                    )
                    .order_by('-allocation_run')
                    .values_list('allocation_run', flat=True)
                    .first()
                )
                planned_quantity = DealerInputAllocation.objects.filter(
                    supplier=supplier,
                    agro_dealer=dealer,
                    input_type=form.cleaned_data['input_type'],
                    allocation_run=latest_allocation_run,
                ).aggregate(total=Sum('quantity_kg'))['total'] or 0
                dispatched_quantity = SupplierDispatch.objects.filter(
                    agro_dealer=dealer,
                    supplier=supplier,
                    input_type=form.cleaned_data['input_type'],
                    allocation_run=latest_allocation_run,
                ).aggregate(total=Sum('quantity_kg'))['total'] or 0
                remaining_planned = planned_quantity - dispatched_quantity
                if not planned_quantity:
                    form.add_error('quantity_kg', 'This dealer has no allocation for the selected input from this supplier.')
                elif quantity > remaining_planned:
                    form.add_error(
                        'quantity_kg',
                        f'Dispatch quantity cannot exceed the remaining allocated quantity ({remaining_planned:.2f} kg).',
                    )
                elif quantity > input_stock:
                    form.add_error('quantity_kg', 'Issue quantity cannot exceed this supplier’s stock for the selected input type.')
                else:
                    supplier.current_stock_kg -= quantity
                    setattr(supplier, stock_field, input_stock - quantity)
                    supplier.save(update_fields=['current_stock_kg', stock_field])
                    SupplierDispatch.objects.create(
                        supplier=supplier,
                        agro_dealer=dealer,
                        input_type=form.cleaned_data['input_type'],
                        quantity_kg=quantity,
                        allocation_run=latest_allocation_run,
                        dispatched_by=request.user,
                    )
                    messages.success(
                        request,
                        'Input issue recorded. The agro-dealer must enter the quantity collected before their stock is updated.',
                    )
                    return redirect('supplier_dispatch')
    else:
        form = SupplierDispatchForm(district_scope=district)
    suppliers = Supplier.objects.filter(district__iexact=district, is_active=True)
    if not district:
        suppliers = Supplier.objects.filter(is_active=True)
    return render(request, 'inventory/supplier_dispatch.html', {
        'form': form,
        'suppliers': suppliers,
        'district': district or 'All districts',
    })
