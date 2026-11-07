from django.db import models
from forecasting.models import Forecast
from logistics.models import AgroDealer, Supplier
from farmers.models import Farmer
from django.contrib.auth.models import User


class InventoryAllocation(models.Model):
    """
    Result of a PuLP-based inventory allocation optimization run.
    Stores how much of each input to allocate to each district,
    derived from forecasts and any supply/cost constraints.
    """

    district = models.CharField(max_length=100)
    input_type = models.CharField(
        max_length=20,
        choices=[
            ('fertilizer_d', 'Fertilizer (D Compound)'),
            ('fertilizer_urea', 'Fertilizer (Urea)'),
            ('seed_maize', 'Seed (Maize)'),
            ('seed_other', 'Seed (Other)'),
            ('seed_soybeans', 'Soybean seed'),
            ('seed_sunflower', 'Sunflower seed'),
            ('seed_popcorn', 'Popcorn seed'),
        ]
    )

    # The forecast this allocation is based on
    forecast = models.ForeignKey(Forecast, on_delete=models.CASCADE, related_name='allocations')

    # The result of the optimization: how much to send to this district
    allocated_quantity_kg = models.DecimalField(max_digits=10, decimal_places=2)

    # Cost per unit (e.g., $/kg) and total cost for this allocation
    cost_per_unit = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    total_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Timestamps
    date_allocated = models.DateTimeField(auto_now_add=True)
    allocation_run = models.CharField(max_length=50, default='manual')  # timestamp or run ID

    class Meta:
        ordering = ['allocation_run', 'district', 'input_type']
        unique_together = ('district', 'input_type', 'allocation_run')

    def __str__(self):
        return f"{self.district} - {self.get_input_type_display()}: {self.allocated_quantity_kg}kg"


class FarmerAllocation(models.Model):
    """The farmer-level share of a district/input allocation."""

    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE, related_name='input_allocations')
    agro_dealer = models.ForeignKey(
        AgroDealer,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='farmer_allocations',
    )
    forecast = models.ForeignKey(Forecast, on_delete=models.CASCADE, related_name='farmer_allocations')
    input_type = models.CharField(max_length=20, choices=InventoryAllocation._meta.get_field('input_type').choices)
    quantity_kg = models.DecimalField(max_digits=10, decimal_places=2)
    allocation_run = models.CharField(max_length=50)
    collection_status = models.CharField(
        max_length=20,
        choices=[
            ('awaiting_collection', 'Awaiting collection'),
            ('collected', 'Collected'),
        ],
        default='awaiting_collection',
    )
    collected_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='confirmed_farmer_collections',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['allocation_run', 'farmer__district', 'farmer__last_name']
        unique_together = ('farmer', 'forecast', 'allocation_run')


class DealerInputAllocation(models.Model):
    """Direct input allocation to a dealer, with its assigned collection supplier."""

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='dealer_allocations')
    forecast = models.ForeignKey(Forecast, on_delete=models.PROTECT, related_name='dealer_allocations')
    input_type = models.CharField(max_length=20, choices=InventoryAllocation._meta.get_field('input_type').choices)
    agro_dealer = models.ForeignKey(AgroDealer, on_delete=models.PROTECT, related_name='input_allocations')
    quantity_kg = models.DecimalField(max_digits=10, decimal_places=2)
    allocation_run = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['allocation_run', 'agro_dealer__district', 'agro_dealer__name']
        constraints = [
            models.UniqueConstraint(
                fields=('supplier', 'forecast', 'agro_dealer', 'allocation_run'),
                name='unique_direct_dealer_supplier_allocation',
            ),
        ]

    def __str__(self):
        return f'{self.agro_dealer} - {self.get_input_type_display()}: {self.quantity_kg}kg from {self.supplier}'


class SupplierDispatch(models.Model):
    """Auditable issue of allocated inputs from a supplier to an agro-dealer."""

    INPUT_TYPE_CHOICES = InventoryAllocation._meta.get_field('input_type').choices
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='dispatches')
    agro_dealer = models.ForeignKey(AgroDealer, on_delete=models.PROTECT, related_name='supplier_dispatches')
    input_type = models.CharField(max_length=20, choices=INPUT_TYPE_CHOICES)
    quantity_kg = models.DecimalField(max_digits=10, decimal_places=2)
    allocation_run = models.CharField(max_length=50, blank=True)
    dispatched_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='supplier_dispatches')
    dispatched_at = models.DateTimeField(auto_now_add=True)
    received_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='dealer_stock_receipts',
    )
    received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-dispatched_at']

    def __str__(self):
        return f'{self.supplier} to {self.agro_dealer}: {self.quantity_kg}kg'


class DealerStockReceipt(models.Model):
    """A dealer-confirmed quantity collected against a supplier issue."""

    dispatch = models.ForeignKey(
        SupplierDispatch,
        on_delete=models.PROTECT,
        related_name='receipts',
    )
    quantity_kg = models.DecimalField(max_digits=12, decimal_places=2)
    received_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='confirmed_stock_receipts',
    )
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-received_at', '-pk']

    def __str__(self):
        return f'{self.dispatch.agro_dealer}: {self.quantity_kg}kg received'
