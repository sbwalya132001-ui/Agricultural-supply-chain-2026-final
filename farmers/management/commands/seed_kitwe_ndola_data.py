import csv
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand

from farmers.models import Farmer, FarmerInputUsage


SEASONS = [
    '2017/2018', '2018/2019', '2019/2020', '2020/2021',
    '2021/2022', '2022/2023', '2023/2024', '2024/2025',
]
INPUT_TYPES = ['fertilizer_d', 'fertilizer_urea', 'seed_maize', 'seed_other']
DISTRICTS = {
    'Kitwe': (-12.80, 28.22),
    'Ndola': (-12.97, 28.64),
}


class Command(BaseCommand):
    help = 'Create 8 Kitwe farmers, 8 Ndola farmers, 8 seasons of usage, and a 500-row CSV.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            default='sample_input_usage_500.csv',
            help='CSV path relative to the project root unless an absolute path is supplied.',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing Kitwe/Ndola farmers and their usage before seeding.',
        )

    def handle(self, *args, **options):
        if options['clear']:
            Farmer.objects.filter(district__in=DISTRICTS).delete()

        farmers = []
        for district, (base_latitude, base_longitude) in DISTRICTS.items():
            for index in range(8):
                national_id = f'{district.upper()}-DEMO-{index + 1:03d}'
                farmer, _ = Farmer.objects.get_or_create(
                    national_id=national_id,
                    defaults={
                        'first_name': district,
                        'last_name': f'Farmer {index + 1}',
                        'district': district,
                        'ward': f'{district} Ward {(index % 4) + 1}',
                        'latitude': base_latitude + (index * 0.006),
                        'longitude': base_longitude + (index * 0.006),
                        'farm_size_hectares': Decimal(str(1.5 + (index % 4) * 0.5)),
                        'primary_crop': 'maize',
                    },
                )
                farmers.append(farmer)

        rows = []
        for farmer_index, farmer in enumerate(farmers):
            for season_index, season in enumerate(SEASONS):
                for input_index, input_type in enumerate(INPUT_TYPES):
                    # Twelve optional rows are omitted so the export is exactly 500 rows.
                    if input_type == 'seed_other' and farmer_index < 3 and season_index >= 4:
                        continue
                    quantity = Decimal(
                        35 + (farmer_index % 8) * 4 + season_index * 2 + input_index * 7
                    ).quantize(Decimal('0.01'))
                    usage, _ = FarmerInputUsage.objects.update_or_create(
                        farmer=farmer,
                        season=season,
                        input_type=input_type,
                        defaults={'quantity_kg': quantity},
                    )
                    rows.append({
                        'national_id': farmer.national_id,
                        'district': farmer.district,
                        'season': season,
                        'input_type': input_type,
                        'quantity_kg': f'{usage.quantity_kg:.2f}',
                    })

        output_path = Path(options['output'])
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path
        with output_path.open('w', newline='', encoding='utf-8') as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

        self.stdout.write(self.style.SUCCESS(
            f'Created/updated {len(farmers)} farmers and {len(rows)} usage rows. '
            f'CSV written to {output_path}.'
        ))