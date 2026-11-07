#!/usr/bin/env python
import csv
import os
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fisp_system.settings')

import django

django.setup()

from farmers.models import Farmer, FarmerInputUsage
from forecasting.services import run_all_forecasts

DISTRICTS = [
    'Kitwe',
    'Ndola',
    'Mufulira',
    'Chingola',
]

SEASONS = [
    '2020/2021',
    '2021/2022',
    '2022/2023',
    '2023/2024',
    '2024/2025',
]

INPUT_TYPES = [
    'fertilizer_d',
    'fertilizer_urea',
    'seed_maize',
    'seed_other',
    'seed_soybeans',
    'seed_sunflower',
    'seed_popcorn',
]

CSV_PATH = os.path.join(os.path.dirname(__file__), 'forecast_historical_usage_32farmers.csv')


def generate_quantity(farmer_index: int, district: str, season_index: int, input_type: str) -> Decimal:
    district_offset = {'Kitwe': 0, 'Ndola': 60, 'Mufulira': 120, 'Chingola': 180}[district]
    input_bias = {
        'fertilizer_d': 0,
        'fertilizer_urea': 18,
        'seed_maize': 34,
        'seed_other': 12,
        'seed_soybeans': 20,
        'seed_sunflower': 16,
        'seed_popcorn': 14,
    }[input_type]
    season_trend = season_index * 8
    farmer_variation = (farmer_index * 7) % 25
    base = 70 + district_offset + input_bias + season_trend + farmer_variation
    return Decimal(str(base)).quantize(Decimal('0.01'))


def create_farmers():
    created_farmers = 0
    for district_index, district in enumerate(DISTRICTS):
        for farmer_num in range(8):
            farmer_index = (district_index * 8) + farmer_num + 1
            national_id = f'FARM{farmer_index:04d}'
            farmer, created = Farmer.objects.get_or_create(
                national_id=national_id,
                defaults={
                    'first_name': f'Farmer{farmer_index}',
                    'last_name': f'{district[:3]}{farmer_num + 1}',
                    'phone_number': f'096{(farmer_index * 37) % 10000000:07d}',
                    'district': district,
                    'ward': f'Ward {farmer_num + 1}',
                    'latitude': 0.0,
                    'longitude': 0.0,
                    'farm_size_hectares': Decimal(str(2 + (farmer_index % 5) * 0.8)),
                    'primary_crop': 'maize',
                },
            )
            if created:
                created_farmers += 1
    return created_farmers


def create_usage_records():
    rows = []
    created_usage = 0
    for district in DISTRICTS:
        for farmer_num in range(8):
            farmer_index = (DISTRICTS.index(district) * 8) + farmer_num + 1
            farmer = Farmer.objects.get(national_id=f'FARM{farmer_index:04d}')
            for season_index, season in enumerate(SEASONS):
                for input_type in INPUT_TYPES:
                    qty = generate_quantity(farmer_index, district, season_index, input_type)
                    obj, created = FarmerInputUsage.objects.update_or_create(
                        farmer=farmer,
                        season=season,
                        input_type=input_type,
                        defaults={'quantity_kg': qty},
                    )
                    if created:
                        created_usage += 1
                    rows.append({
                        'national_id': farmer.national_id,
                        'season': season,
                        'input_type': input_type,
                        'quantity_kg': f'{qty:.2f}',
                    })
    return created_usage, rows


def write_csv(rows):
    fieldnames = ['national_id', 'season', 'input_type', 'quantity_kg']
    with open(CSV_PATH, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return CSV_PATH


def main():
    print('Creating farmers...')
    created_farmers = create_farmers()
    print(f'Created {created_farmers} new farmers.')

    print('Creating historical input usage...')
    created_usage, rows = create_usage_records()
    print(f'Created {created_usage} new usage records.')

    csv_path = write_csv(rows)
    print(f'CSV export written to: {csv_path}')

    print('Generating forecasts from the new demand history...')
    forecast_summary = run_all_forecasts()
    print(f"Forecasts succeeded: {len(forecast_summary['succeeded'])}")
    print(f"Forecasts skipped: {len(forecast_summary['skipped'])}")


if __name__ == '__main__':
    main()
