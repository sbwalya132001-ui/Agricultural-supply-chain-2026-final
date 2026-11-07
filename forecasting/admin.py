from django.contrib import admin
from .models import Forecast, NationalInputSeries


@admin.register(Forecast)
class ForecastAdmin(admin.ModelAdmin):
    list_display = ('district', 'input_type', 'forecast_season', 'predicted_quantity_kg', 'seasons_used', 'date_generated')
    list_filter = ('district', 'input_type')


@admin.register(NationalInputSeries)
class NationalInputSeriesAdmin(admin.ModelAdmin):
    list_display = ('input_type', 'season', 'value', 'unit', 'flag', 'source')
    list_filter = ('input_type',)
