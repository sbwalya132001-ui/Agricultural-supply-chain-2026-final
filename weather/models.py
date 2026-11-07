from django.db import models

from .conditions import weather_condition


class DailyWeather(models.Model):
    RECORD_TYPE_CHOICES = [
        ('historical', 'Historical / reanalysis'),
        ('forecast', 'Forecast'),
    ]

    district = models.CharField(max_length=100)
    record_type = models.CharField(max_length=12, choices=RECORD_TYPE_CHOICES)
    date = models.DateField()
    rainfall_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    temperature_min_c = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    temperature_max_c = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    humidity_mean_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    precipitation_probability_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    source = models.CharField(max_length=80, default='Open-Meteo')
    # Number of global models averaged into temperature_min_c / temperature_max_c.
    temperature_model_count = models.PositiveSmallIntegerField(default=0)
    # ECMWF IFS daily WMO weather code (0 clear ... 95 thunderstorm), shown as an icon.
    weather_code = models.PositiveSmallIntegerField(null=True, blank=True)
    fetched_at = models.DateTimeField(auto_now=True)

    @property
    def condition(self):
        return weather_condition(self.weather_code)

    class Meta:
        ordering = ['-date', 'district', 'record_type']
        constraints = [
            models.UniqueConstraint(
                fields=('district', 'record_type', 'date'),
                name='unique_daily_weather_district_type_date',
            ),
        ]

    def __str__(self):
        return f'{self.district} - {self.date} ({self.get_record_type_display()})'


class GlobalModelTemperature(models.Model):
    """Daily min/max temperature from one global NWP model (ECMWF IFS, GFS, ICON)."""

    district = models.CharField(max_length=100)
    date = models.DateField()
    model = models.CharField(max_length=40)
    temperature_min_c = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    temperature_max_c = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['district', 'date', 'model']
        constraints = [
            models.UniqueConstraint(
                fields=('district', 'date', 'model'),
                name='unique_global_model_temperature',
            ),
        ]

    def __str__(self):
        return f'{self.district} - {self.date} ({self.model})'


class MonthlySeasonalOutlook(models.Model):
    """A retrievable ECMWF SEAS5 monthly rainfall outlook snapshot."""

    district = models.CharField(max_length=100)
    model = models.CharField(max_length=40, default='ecmwf_seas5')
    source = models.CharField(max_length=80, default='Open-Meteo Seasonal Forecast API')
    retrieved_date = models.DateField()
    valid_month = models.DateField()
    precipitation_mean_mm = models.DecimalField(
        max_digits=9,
        decimal_places=2,
        null=True,
        blank=True,
    )
    precipitation_anomaly_mm = models.DecimalField(
        max_digits=9,
        decimal_places=2,
        null=True,
        blank=True,
    )
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['district', '-retrieved_date', 'valid_month']
        constraints = [
            models.UniqueConstraint(
                fields=('district', 'model', 'retrieved_date', 'valid_month'),
                name='unique_seasonal_weather_snapshot',
            ),
        ]

    def __str__(self):
        return f'{self.district} - {self.valid_month:%Y-%m} ({self.model})'