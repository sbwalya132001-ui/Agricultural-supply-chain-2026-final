import csv
import os
from decimal import Decimal
from pathlib import Path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fisp_system.settings')

import django

django.setup()

from farmers.models import Farmer, FarmerInputUsage

SEASONS = [
    '2017/2018', '2018/2019', '2019/2020', '2020/2021',
    '2021/2022', '2022/2023', '2023/2024', '2024/2025',
]

FARMER_PATTERNS = [
    ['fertilizer_d', 'fertilizer_urea', 'seed_maize', 'seed_other'],
    ['fertilizer_d', 'fertilizer_urea', 'seed_maize', 'seed_other'],
    ['fertilizer_d', 'fertilizer_urea', 'seed_maize', 'seed_other'],
    ['fertilizer_d', 'fertilizer_urea', 'seed_maize'],
    ['fertilizer_d', 'fertilizer_urea', 'seed_maize'],
    ['fertilizer_d', 'fertilizer_urea', 'seed_other'],
    ['fertilizer_d', 'seed_maize'],
    ['fertilizer_urea', 'seed_other'],
]

Farmer.objects.filter(district='Kitwe').delete()

farmers = []
for idx in range(1, 9):
    national_id = f'KITWE-DEMO-{idx:03d}'
    farmer, _ = Farmer.objects.get_or_create(
        national_id=national_id,
        defaults={
            'first_name': 'Kitwe',
            'last_name': f'Farmer {idx}',
            'district': 'Kitwe',
            'ward': f'Ward {idx}',
            'latitude': -12.80 + (idx * 0.004),
            'longitude': 28.22 + (idx * 0.004),
            'farm_size_hectares': Decimal(str(1.5 + (idx % 4) * 0.5)),
            'primary_crop': 'maize',
        },
    )
    farmers.append(farmer)

rows = []
for farmer_index, farmer in enumerate(farmers, start=1):
    pattern = FARMER_PATTERNS[farmer_index - 1]
    for season_index, season in enumerate(SEASONS):
        for input_type in pattern:
            type_weight = {
                'fertilizer_d': 0,
                'fertilizer_urea': 7,
                'seed_maize': 12,
                'seed_other': 19,
            }
            base_quantity = 20 + farmer_index * 4 + season_index * 5 + type_weight[input_type]
            quantity = Decimal(str(base_quantity)).quantize(Decimal('0.01'))
            FarmerInputUsage.objects.update_or_create(
                farmer=farmer,
                season=season,
                input_type=input_type,
                defaults={'quantity_kg': quantity},
            )
            rows.append({
                'farmer_id': farmer.id,
                'national_id': farmer.national_id,
                'district': farmer.district,
                'season': season,
                'input_type': input_type,
                'quantity_kg': f'{quantity:.2f}',
            })

if len(rows) != 200:
    raise RuntimeError(f'Expected 200 rows, generated {len(rows)} rows.')

output_path = Path(__file__).resolve().parent / 'kitwe_farmer_usage_200.csv'
with output_path.open('w', newline='', encoding='utf-8') as csv_file:
    writer = csv.DictWriter(csv_file, fieldnames=['farmer_id', 'national_id', 'district', 'season', 'input_type', 'quantity_kg'])
    writer.writeheader()
    writer.writerows(rows)

print('Created 8 Kitwe farmers:')
for farmer in farmers:
    print(f'  {farmer.id}: {farmer.national_id}')
print(f'Generated {len(rows)} CSV rows.')
print(f'CSV file: {output_path}')
