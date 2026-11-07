from django.contrib import admin
from .models import DealerInputAllocation, FarmerAllocation, InventoryAllocation, SupplierDispatch


@admin.register(SupplierDispatch)
class SupplierDispatchAdmin(admin.ModelAdmin):
    list_display = ('supplier', 'agro_dealer', 'input_type', 'quantity_kg', 'dispatched_by', 'dispatched_at', 'received_at')
    list_filter = ('input_type', 'supplier__district', 'received_at')
    readonly_fields = ('dispatched_at', 'received_at')


@admin.register(InventoryAllocation)
class InventoryAllocationAdmin(admin.ModelAdmin):
    list_display = ('district', 'input_type', 'allocated_quantity_kg', 'total_cost', 'allocation_run', 'date_allocated')
    list_filter = ('allocation_run', 'input_type', 'district')
    search_fields = ('district', 'input_type')
    readonly_fields = ('date_allocated', 'allocation_run')
    
    fieldsets = (
        ('Allocation Details', {
            'fields': ('district', 'input_type', 'forecast', 'allocated_quantity_kg')
        }),
        ('Costing', {
            'fields': ('cost_per_unit', 'total_cost')
        }),
        ('Run Information', {
            'fields': ('allocation_run', 'date_allocated'),
            'classes': ('collapse',)
        }),
    )


@admin.register(DealerInputAllocation)
class DealerInputAllocationAdmin(admin.ModelAdmin):
    list_display = ('agro_dealer', 'supplier', 'forecast', 'input_type', 'quantity_kg', 'allocation_run')
    list_filter = ('agro_dealer__district', 'supplier__district', 'input_type', 'allocation_run')


@admin.register(FarmerAllocation)
class FarmerAllocationAdmin(admin.ModelAdmin):
    list_display = ('farmer', 'input_type', 'quantity_kg', 'allocation_run', 'created_at')
    list_filter = ('farmer__district', 'input_type', 'allocation_run')
