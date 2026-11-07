#!/usr/bin/env python
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fisp_system.settings')
django.setup()

from forecasting.services import run_all_forecasts

# Run all forecasts
result = run_all_forecasts()

print(f"\n=== Forecasting Results ===")
print(f"Succeeded: {len(result['succeeded'])}")
for forecast in result['succeeded']:
    print(f"  - {forecast.district} / {forecast.get_input_type_display()}: {forecast.predicted_quantity_kg}kg")

if result['skipped']:
    print(f"\nSkipped (insufficient data): {len(result['skipped'])}")
    for district, input_type in result['skipped']:
        print(f"  - {district} / {input_type}")

print(f"\nForecasts generated successfully!")
