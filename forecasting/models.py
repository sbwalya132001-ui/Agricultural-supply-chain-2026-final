from django.db import models
from farmers.models import FarmerInputUsage


class Forecast(models.Model):
    """
    A stored ARIMA baseline for a district/input/season, plus separate
    explanatory weather-scenario fields. Inventory allocation uses the
    baseline quantity, not the scenario amount.
    """

    district = models.CharField(max_length=100)
    input_type = models.CharField(max_length=20, choices=FarmerInputUsage.INPUT_TYPE_CHOICES)

    # The season this forecast is predicting FOR (i.e. one season ahead
    # of the last season in the training data)
    forecast_season = models.CharField(max_length=20)

    predicted_quantity_kg = models.DecimalField(max_digits=10, decimal_places=2)
    baseline_predicted_quantity_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='ARIMA baseline demand; this is the quantity used for inventory allocation.',
    )
    weather_adjustment_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text='Provisional demand adjustment based on the ZMD seasonal rainfall outlook.',
    )
    weather_summary = models.CharField(max_length=180, blank=True)
    weather_scenario_quantity_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Illustrative ZMD-adjusted planning scenario; not used for inventory allocation.',
    )
    # The ECMWF SEAS5 scenario is stored alongside the ZMD one so users can
    # compare and switch between them; neither replaces the other.
    seas5_adjustment_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Provisional demand adjustment based on the ECMWF SEAS5 rainfall outlook.',
    )
    seas5_summary = models.CharField(max_length=180, blank=True)
    seas5_scenario_quantity_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Illustrative SEAS5-adjusted planning scenario; baseline remains the default allocation quantity.',
    )
    seasonal_weather_summary = models.CharField(max_length=500, blank=True)
    seasonal_weather_retrieved_date = models.DateField(null=True, blank=True)

    @property
    def allocation_quantity_kg(self):
        """Return baseline demand for inventory, falling back for legacy rows."""
        if self.baseline_predicted_quantity_kg is not None:
            return self.baseline_predicted_quantity_kg
        return self.predicted_quantity_kg

    # How many historical seasons of data went into this prediction —
    # useful context to show alongside the number, and to explain in
    # your report why some forecasts are more reliable than others.
    seasons_used = models.PositiveIntegerField()

    model_used = models.CharField(max_length=80, default='ARIMA')
    date_generated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['district', 'input_type']
        unique_together = ('district', 'input_type', 'forecast_season')

    def __str__(self):
        return f"{self.district} - {self.get_input_type_display()} - {self.forecast_season}: {self.predicted_quantity_kg}kg"

class NationalInputSeries(models.Model):
    """
    One season of a published national series (FAOSTAT) for an input type.

    Districts with only one season of real farmer records (e.g. the 2021/2022
    FISP survey) are forecast by fitting ARIMA to this long national series and
    scaling their real season by the predicted national change.
    """

    input_type = models.CharField(max_length=20, choices=FarmerInputUsage.INPUT_TYPE_CHOICES)
    season = models.CharField(max_length=20, help_text='e.g. 2021/2022')
    value = models.DecimalField(max_digits=14, decimal_places=2)
    # The series is a demand indicator, not kg: tonnes of nutrient or hectares of maize.
    unit = models.CharField(max_length=10)
    source = models.CharField(max_length=120)
    flag = models.CharField(max_length=2, blank=True, help_text='FAOSTAT data flag, e.g. A = official.')

    class Meta:
        ordering = ['input_type', 'season']
        unique_together = ('input_type', 'season')

    def __str__(self):
        return f"{self.get_input_type_display()} - {self.season}: {self.value} {self.unit}"


class NationalBacktest(models.Model):
    """
    Back-test of the national forecast for one input type and target season.

    Stored when forecasts are generated (and reused while the national series
    is unchanged) so the forecast page can show how accurate the model is.
    Errors are mean absolute percentage errors (MAPE) over the test origins.
    """

    METHOD_CHOICES = [
        ('fixed', 'ARIMA(1,1,1)'),
        ('auto', 'Auto log-ARIMA'),
    ]

    input_type = models.CharField(max_length=20, choices=FarmerInputUsage.INPUT_TYPE_CHOICES)
    forecast_season = models.CharField(max_length=20)
    steps = models.PositiveSmallIntegerField(help_text='Seasons ahead, as in the real forecast.')
    chosen_method = models.CharField(max_length=10, choices=METHOD_CHOICES)
    validation_mape_fixed = models.FloatField()
    validation_mape_auto = models.FloatField()
    test_mape_fixed = models.FloatField()
    test_mape_auto = models.FloatField()
    test_mape_naive = models.FloatField()
    test_mape_drift = models.FloatField()
    first_test_season = models.CharField(max_length=20)
    last_test_season = models.CharField(max_length=20)
    data_fingerprint = models.CharField(max_length=64)
    evaluated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['input_type']
        unique_together = ('input_type', 'forecast_season')

    @property
    def test_mape_chosen(self):
        return self.test_mape_auto if self.chosen_method == 'auto' else self.test_mape_fixed

    def __str__(self):
        return f"{self.get_input_type_display()} - {self.forecast_season}: {self.get_chosen_method_display()}"
