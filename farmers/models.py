from django.db import models
from django.contrib.auth.models import User


class Farmer(models.Model):
    """
    Core farmer profile. This is the foundation the forecasting,
    inventory, and logistics apps will all read from later.
    """

    CROP_CHOICES = [
        ('maize', 'Maize'),
        ('groundnuts', 'Groundnuts'),
        ('soya_beans', 'Soya Beans'),
        ('rice', 'Rice'),
        ('cassava', 'Cassava'),
        ('other', 'Other'),
    ]

    # Personal details
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='farmer_profile',
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    national_id = models.CharField(max_length=30, unique=True)
    phone_number = models.CharField(max_length=20, blank=True)

    # Location — district-level is what forecasting/allocation groups by
    district = models.CharField(max_length=100)
    ward = models.CharField(max_length=100, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    # Farm details
    farm_size_hectares = models.DecimalField(max_digits=6, decimal_places=2)
    primary_crop = models.CharField(max_length=20, choices=CROP_CHOICES, default='maize')

    date_registered = models.DateField(auto_now_add=True)

    class Meta:
        ordering = ['district', 'last_name']

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.district})"


class DeliveryConfirmation(models.Model):
    """A stakeholder confirmation or issue report for a route assignment."""

    STATUS_CHOICES = [
        ('received', 'Received'),
        ('delivered', 'Delivered'),
        ('issue', 'Report an issue'),
    ]

    SOURCE_CHOICES = [
        ('farmer', 'Farmer'),
        ('dealer', 'Agro-Dealer'),
    ]

    route_stop = models.OneToOneField(
        'logistics.RouteStop',
        on_delete=models.CASCADE,
        related_name='farmer_confirmation',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='farmer')
    message = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-submitted_at']

    def __str__(self):
        return f'{self.route_stop.farmer} - {self.get_status_display()}'


class FarmerInputUsage(models.Model):
    """
    Historical input usage per farmer, per season. This is the raw
    data your forecasting app (ARIMA) will aggregate by district
    later — so get the season/input_type/quantity fields right now.
    """

    INPUT_TYPE_CHOICES = [
        ('fertilizer_d', 'Fertilizer (D Compound)'),
        ('fertilizer_urea', 'Fertilizer (Urea)'),
        ('seed_maize', 'Seed (Maize)'),
        ('seed_other', 'Seed (Other)'),
        ('seed_soybeans', 'Soybean seed'),
        ('seed_sunflower', 'Sunflower seed'),
        ('seed_popcorn', 'Popcorn seed'),
    ]

    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE, related_name='input_usages')
    season = models.CharField(max_length=20, help_text="e.g. 2024/2025")
    input_type = models.CharField(max_length=20, choices=INPUT_TYPE_CHOICES)
    quantity_kg = models.DecimalField(max_digits=8, decimal_places=2)
    source_event_id = models.CharField(
        max_length=80,
        unique=True,
        null=True,
        blank=True,
        help_text='Optional unique ID from an imported usage-event dataset; prevents duplicate imports.',
    )
    date_recorded = models.DateField(auto_now_add=True)

    class Meta:
        ordering = ['-season']

    def __str__(self):
        return f"{self.farmer} - {self.season} - {self.get_input_type_display()}"