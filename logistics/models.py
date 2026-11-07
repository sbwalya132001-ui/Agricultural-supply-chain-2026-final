from django.db import models
from django.contrib.auth.models import User
from farmers.models import Farmer


class Supplier(models.Model):
	name = models.CharField(max_length=120)
	district = models.CharField(max_length=100)
	latitude = models.FloatField()
	longitude = models.FloatField()
	current_stock_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)
	stock_fertilizer_d_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)
	stock_fertilizer_urea_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)
	stock_seed_maize_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)
	stock_seed_other_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)
	stock_seed_soybeans_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)
	stock_seed_sunflower_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)
	stock_seed_popcorn_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)
	is_active = models.BooleanField(default=False)

	class Meta:
		ordering = ['district', 'name']

	def __str__(self):
		return f'{self.name} ({self.district})'


class AgroDealer(models.Model):
	user = models.OneToOneField(
		User,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name='agrodealer_profile',
	)
	name = models.CharField(max_length=120)
	district = models.CharField(max_length=100)
	latitude = models.FloatField()
	longitude = models.FloatField()
	stock_quantity_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)
	stock_fertilizer_d_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)
	stock_fertilizer_urea_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)
	stock_seed_maize_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)
	stock_seed_other_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)
	stock_seed_soybeans_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)
	stock_seed_sunflower_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)
	stock_seed_popcorn_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)

	class Meta:
		ordering = ['district', 'name']

	def __str__(self):
		return f'{self.name} ({self.district})'


class RoutePlan(models.Model):
	"""A generated set of supplier-to-dealer collection routes."""
	STATUS_CHOICES = [
		('planned', 'Planned'),
		('in_progress', 'In progress'),
		('completed', 'Completed'),
		('cancelled', 'Cancelled'),
	]

	name = models.CharField(max_length=100, default='FISP delivery route')
	start_latitude = models.FloatField(null=True, blank=True)
	start_longitude = models.FloatField(null=True, blank=True)
	total_distance_km = models.DecimalField(max_digits=10, decimal_places=2, default=0)
	planned_delivery_date = models.DateField(null=True, blank=True)
	vehicle_identifier = models.CharField(max_length=80, blank=True)
	allocation_run = models.CharField(max_length=50, blank=True)
	status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='planned')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-created_at']

	def __str__(self):
		return f'{self.name} ({self.created_at:%Y-%m-%d %H:%M})'


class RouteStop(models.Model):
	STATUS_CHOICES = [
		('pending', 'Pending'),
		('delivered', 'Delivered'),
		('issue', 'Issue reported'),
	]

	route = models.ForeignKey(RoutePlan, on_delete=models.CASCADE, related_name='stops')
	farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE, related_name='route_stops')
	agro_dealer = models.ForeignKey('AgroDealer', on_delete=models.PROTECT, null=True, blank=True, related_name='delivery_stops')
	sequence = models.PositiveIntegerField()
	distance_from_previous_km = models.DecimalField(max_digits=10, decimal_places=2, default=0)
	allocated_quantity_kg = models.DecimalField(max_digits=10, decimal_places=2, default=0)
	road_geometry = models.JSONField(default=list, blank=True)
	status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

	class Meta:
		ordering = ['sequence']
		unique_together = ('route', 'sequence')

	def __str__(self):
		return f'{self.route} - stop {self.sequence}: {self.farmer}'


class RouteStopInput(models.Model):
	INPUT_TYPE_CHOICES = [
		('fertilizer_d', 'Fertilizer (D Compound)'),
		('fertilizer_urea', 'Fertilizer (Urea)'),
		('seed_maize', 'Seed (Maize)'),
		('seed_other', 'Seed (Other)'),
		('seed_soybeans', 'Soybean seed'),
		('seed_sunflower', 'Sunflower seed'),
		('seed_popcorn', 'Popcorn seed'),
	]

	route_stop = models.ForeignKey(RouteStop, on_delete=models.CASCADE, related_name='input_items')
	input_type = models.CharField(max_length=20, choices=INPUT_TYPE_CHOICES)
	quantity_kg = models.DecimalField(max_digits=10, decimal_places=2)

	class Meta:
		unique_together = ('route_stop', 'input_type')


class SupplierDealerRoute(models.Model):
	route = models.ForeignKey(RoutePlan, on_delete=models.CASCADE, related_name='distribution_legs')
	supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='route_legs')
	agro_dealer = models.ForeignKey(AgroDealer, on_delete=models.PROTECT, related_name='route_legs')
	sequence = models.PositiveIntegerField()
	allocated_quantity_kg = models.DecimalField(max_digits=10, decimal_places=2, default=0)
	distance_from_previous_km = models.DecimalField(max_digits=10, decimal_places=2, default=0)
	road_geometry = models.JSONField(default=list, blank=True)

	class Meta:
		ordering = ['supplier__district', 'sequence']
		unique_together = ('route', 'supplier', 'agro_dealer')

	def __str__(self):
		return f'{self.route} - {self.agro_dealer} to {self.supplier}'
