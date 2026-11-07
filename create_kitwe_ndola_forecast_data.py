"""Register 16 Kitwe/Ndola farmers and export 100 sample usage records."""
import csv
import os
from decimal import Decimal
from pathlib import Path

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fisp_system.settings')
django.setup()

from farmers.models import Farmer, FarmerInputUsage  # noqa: E402
from django.db import transaction  # noqa: E402

SEASONS = [
    '2017/2018', '2018/2019', '2019/2020', '2020/2021',
    '2021/2022', '2022/2023', '2023/2024', '2024/2025',
]
DISTRICTS = {
    'Kitwe': {
        'prefix': 'KITWE',
        'latitude': -12.80,
        'longitude': 28.22,
        'farmers': [
            ('Chanda', 'Banda'), ('Mwila', 'Phiri'), ('Mulenga', 'Tembo'),
            ('Bwalya', 'Mwanza'), ('Mwamba', 'Zulu'), ('Lombe', 'Mumba'),
            ('Chileshe', 'Nkole'), ('Mwelwa', 'Sakala'),
        ],
    },
    'Ndola': {
        'prefix': 'NDOLA',
        'latitude': -12.97,
        'longitude': 28.64,
        'farmers': [
            ('Lusungu', 'Chanda'), ('Tapiwa', 'Phiri'), ('Chisanga', 'Mwansa'),
            ('Natasha', 'Banda'), ('Misozi', 'Zulu'), ('Bupe', 'Mumba'),
            ('Chola', 'Nkole'), ('Mwaka', 'Sakala'),
        ],
    },
}
INPUT_TYPES = [input_type for input_type, _ in FarmerInputUsage.INPUT_TYPE_CHOICES]
OUTPUT_FILE = Path(__file__).resolve().parent / 'kitwe_ndola_farmer_usage_100.csv'

farmers = []
for district, config in DISTRICTS.items():
    for index, (first_name, last_name) in enumerate(config['farmers'], start=1):
        national_id = f"FISP-{config['prefix']}-{index:03d}"
        farmer, created = Farmer.objects.get_or_create(
            national_id=national_id,
            defaults={
                'first_name': first_name,
                'last_name': last_name,
                'district': district,
                'ward': f'{district} Ward {((index - 1) % 4) + 1}',
                'latitude': config['latitude'] + ((index - 1) * 0.004),
                'longitude': config['longitude'] + ((index - 1) * 0.004),
                'farm_size_hectares': Decimal(f'{1.5 + ((index - 1) % 4) * 0.5:.2f}'),
                'primary_crop': 'maize',
            },
        )
        if farmer.district != district:
            raise ValueError(f'{national_id} already exists in {farmer.district}, not {district}.')
        farmers.append((farmer, created))

rows = []
with transaction.atomic():
    FarmerInputUsage.objects.filter(farmer__in=[farmer for farmer, _ in farmers]).delete()
    for district_index, (district, config) in enumerate(DISTRICTS.items()):
        district_farmers = [farmer for farmer, _ in farmers if farmer.district == district]
        selected_combinations = set()
        for season_index in range(len(SEASONS)):
            omitted_input = (season_index + district_index) % len(INPUT_TYPES)
            for input_index, input_type in enumerate(INPUT_TYPES):
                if input_index != omitted_input:
                    selected_combinations.add((season_index, input_index))
        # Add two of the omitted district/season/input combinations per district.
        for season_index in (0, 1):
            selected_combinations.add((season_index, (season_index + district_index) % len(INPUT_TYPES)))

        for season_index, input_index in sorted(selected_combinations):
            farmer_index = (season_index * 3 + input_index * 5 + district_index) % len(district_farmers)
            farmer = district_farmers[farmer_index]
            farmer_number = int(farmer.national_id.rsplit('-', 1)[1])
            input_type = INPUT_TYPES[input_index]
            quantity = Decimal(
                45 + (farmer_number * 3) + (district_index * 5)
                + (season_index * 4) + (input_index * 6)
            ).quantize(Decimal('0.01'))
            usage = FarmerInputUsage.objects.create(
                farmer=farmer,
                season=SEASONS[season_index],
                input_type=input_type,
                quantity_kg=quantity,
            )
            rows.append({
                'farmer_id': farmer.pk,
                'national_id': farmer.national_id,
                'district': farmer.district,
                'season': usage.season,
                'input_type': input_type,
                'quantity_kg': f'{usage.quantity_kg:.2f}',
            })

with OUTPUT_FILE.open('w', newline='', encoding='utf-8') as csv_file:
    writer = csv.DictWriter(
        csv_file,
        fieldnames=['farmer_id', 'national_id', 'district', 'season', 'input_type', 'quantity_kg'],
    )
    writer.writeheader()
    writer.writerows(rows)

created_count = sum(created for _, created in farmers)
print(f'Farmers registered: {len(farmers)} total ({created_count} newly created).')
print(f'Sample input-usage rows exported: {len(rows)}.')
print(f'CSV: {OUTPUT_FILE}')
