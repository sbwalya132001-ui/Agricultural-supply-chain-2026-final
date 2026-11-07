from django.contrib import admin
from .models import DeliveryConfirmation, Farmer, FarmerInputUsage


class FarmerInputUsageInline(admin.TabularInline):
    """Lets you add usage history directly from the Farmer edit page."""
    model = FarmerInputUsage
    extra = 1


@admin.register(Farmer)
class FarmerAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'district', 'user', 'primary_crop', 'farm_size_hectares', 'date_registered')
    list_filter = ('district', 'primary_crop')
    search_fields = ('first_name', 'last_name', 'national_id')
    inlines = [FarmerInputUsageInline]


@admin.register(FarmerInputUsage)
class FarmerInputUsageAdmin(admin.ModelAdmin):
    list_display = ('farmer', 'season', 'input_type', 'quantity_kg', 'date_recorded')
    list_filter = ('season', 'input_type')


@admin.register(DeliveryConfirmation)
class DeliveryConfirmationAdmin(admin.ModelAdmin):
    list_display = ('farmer', 'route', 'status', 'submitted_at')
    list_filter = ('status',)
    search_fields = ('route_stop__farmer__first_name', 'route_stop__farmer__last_name')

    @admin.display(description='Farmer')
    def farmer(self, obj):
        return obj.route_stop.farmer

    @admin.display(description='Route')
    def route(self, obj):
        return obj.route_stop.route