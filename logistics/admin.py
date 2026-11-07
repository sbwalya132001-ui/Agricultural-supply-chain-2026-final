from django.contrib import admin
from .models import AgroDealer, RoutePlan, RouteStop, RouteStopInput, Supplier, SupplierDealerRoute


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
	list_display = ('name', 'district', 'current_stock_kg', 'is_active')
	list_filter = ('district',)
	readonly_fields = (
		'current_stock_kg', 'stock_fertilizer_d_kg', 'stock_fertilizer_urea_kg',
		'stock_seed_maize_kg', 'stock_seed_other_kg', 'stock_seed_soybeans_kg',
		'stock_seed_sunflower_kg', 'stock_seed_popcorn_kg',
	)


@admin.register(AgroDealer)
class AgroDealerAdmin(admin.ModelAdmin):
	list_display = ('name', 'district', 'stock_quantity_kg')
	list_filter = ('district',)
	readonly_fields = (
		'stock_quantity_kg', 'stock_fertilizer_d_kg', 'stock_fertilizer_urea_kg',
		'stock_seed_maize_kg', 'stock_seed_other_kg', 'stock_seed_soybeans_kg',
		'stock_seed_sunflower_kg', 'stock_seed_popcorn_kg',
	)


class RouteStopInline(admin.TabularInline):
	model = RouteStop
	extra = 0


class SupplierDealerRouteInline(admin.TabularInline):
	model = SupplierDealerRoute
	extra = 0


@admin.register(RoutePlan)
class RoutePlanAdmin(admin.ModelAdmin):
	list_display = ('name', 'planned_delivery_date', 'status', 'vehicle_identifier', 'total_distance_km', 'created_at')
	inlines = [RouteStopInline, SupplierDealerRouteInline]


@admin.register(RouteStopInput)
class RouteStopInputAdmin(admin.ModelAdmin):
	list_display = ('route_stop', 'input_type', 'quantity_kg')
	list_filter = ('input_type',)
