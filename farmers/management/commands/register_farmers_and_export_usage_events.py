"""Register 20 sample farmers and export 5,600 synthetic usage events to CSV.

This command deliberately does not create FarmerInputUsage rows. The generated
CSV can be imported later through the demand-data upload workflow.
"""
import csv
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from farmers.models import Farmer, FarmerInputUsage


SEASONS = (
    '2017/2018', '2018/2019', '2019/2020', '2020/2021',
    '2021/2022', '2022/2023', '2023/2024', '2024/2025',
)
DISTRICT_CONFIG = {
    'Kitwe': {
        'prefix': 'KITWE',
        'latitude': -12.80243,
        'longitude': 28.21323,
    },
    'Ndola': {
        'prefix': 'NDOLA',
        'latitude': -12.95867,
        'longitude': 28.63659,
    },
}
FARMER_NAMES = (
    ('Chanda', 'Banda'), ('Mwila', 'Phiri'), ('Mulenga', 'Tembo'),
    ('Bwalya', 'Mwanza'), ('Mwamba', 'Zulu'), ('Lombe', 'Mumba'),
    ('Chileshe', 'Nkole'), ('Mwelwa', 'Sakala'), ('Lusungu', 'Chanda'),
    ('Tapiwa', 'Mwansa'), ('Chisanga', 'Banda'), ('Natasha', 'Zulu'),
    ('Misozi', 'Mumba'), ('Bupe', 'Nkole'), ('Chola', 'Sakala'),
    ('Mwaka', 'Phiri'), ('Nasilele', 'Tembo'), ('Kelvin', 'Mwanza'),
    ('Ruth', 'Sakala'), ('Peter', 'Banda'),
)
PRIMARY_CROPS = (
    'maize', 'groundnuts', 'soya_beans', 'rice', 'cassava', 'other',
    'maize', 'groundnuts', 'soya_beans', 'rice', 'cassava', 'other',
    'maize', 'groundnuts', 'soya_beans', 'rice', 'cassava', 'other',
    'maize', 'groundnuts',
)
INPUT_TYPES = tuple(input_type for input_type, _ in FarmerInputUsage.INPUT_TYPE_CHOICES)
INPUT_BASE_KG = {
    'fertilizer_d': 16,
    'fertilizer_urea': 12,
    'seed_maize': 5,
    'seed_other': 4,
    'seed_soybeans': 4,
    'seed_sunflower': 3,
    'seed_popcorn': 3,
}
EVENTS_PER_COMBINATION = 5
EXPECTED_EVENT_COUNT = 20 * len(SEASONS) * len(INPUT_TYPES) * EVENTS_PER_COMBINATION
CSV_FIELDS = (
    'usage_event_id',
    'farmer_id',
    'national_id',
    'district',
    'season',
    'input_type',
    'quantity_kg',
)


class Command(BaseCommand):
    help = (
        'Register 20 crop-diverse Kitwe/Ndola farmers and create a 5,600-row '
        'synthetic input-usage events CSV without inserting usage records into the database.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            default='farmer_input_usage_20_farmers_8_seasons_5600_events.csv',
            help='CSV path relative to the project root unless an absolute path is supplied.',
        )

    def handle(self, *args, **options):
        output_path = Path(options['output'])
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path

        farmers = []
        created_count = 0
        with transaction.atomic():
            for index, ((first_name, last_name), crop) in enumerate(
                zip(FARMER_NAMES, PRIMARY_CROPS),
                start=1,
            ):
                district = 'Kitwe' if index <= 10 else 'Ndola'
                config = DISTRICT_CONFIG[district]
                national_id = f"FISP-{config['prefix']}-EVENT-{index if index <= 10 else index - 10:03d}"
                defaults = {
                    'first_name': first_name,
                    'last_name': last_name,
                    'district': district,
                    'ward': f'{district} Ward {((index - 1) % 5) + 1}',
                    'latitude': config['latitude'] + (((index - 1) % 10) * 0.001),
                    'longitude': config['longitude'] + (((index - 1) % 10) * 0.001),
                    'phone_number': f'097{index:07d}',
                    'farm_size_hectares': Decimal(f'{1.50 + ((index - 1) % 5) * 0.50:.2f}'),
                    'primary_crop': crop,
                }
                farmer, created = Farmer.objects.get_or_create(
                    national_id=national_id,
                    defaults=defaults,
                )
                if not created and (
                    farmer.district != district or farmer.primary_crop != crop
                ):
                    raise CommandError(
                        f'{national_id} already exists with a different district or primary crop; '
                        'no farmer data was changed.'
                    )
                farmers.append((index, farmer))
                created_count += int(created)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open('w', newline='', encoding='utf-8-sig') as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for farmer_index, farmer in farmers:
                district_index = 0 if farmer.district == 'Kitwe' else 1
                for season_index, season in enumerate(SEASONS):
                    for input_index, input_type in enumerate(INPUT_TYPES):
                        base_quantity = INPUT_BASE_KG[input_type]
                        for event_index in range(1, EVENTS_PER_COMBINATION + 1):
                            event_id = (
                                f'SYN20-{farmer.national_id}-{season_index + 1:02d}-'
                                f'{input_type}-{event_index:02d}'
                            )
                            quantity = Decimal(
                                base_quantity
                                + ((farmer_index * 7 + input_index * 3 + district_index * 5) % 13)
                                + (season_index * 2)
                            ) + (Decimal(event_index) * Decimal('0.75'))
                            quantity = quantity.quantize(Decimal('0.01'))
                            writer.writerow({
                                'usage_event_id': event_id,
                                'farmer_id': farmer.pk,
                                'national_id': farmer.national_id,
                                'district': farmer.district,
                                'season': season,
                                'input_type': input_type,
                                'quantity_kg': f'{quantity:.2f}',
                            })

        self.stdout.write(self.style.SUCCESS(
            f'Registered or verified 20 farmers ({created_count} newly created), '
            f'covering {len({farmer.primary_crop for _, farmer in farmers})} primary crop types. '
            f'Wrote {EXPECTED_EVENT_COUNT:,} synthetic usage-event rows to {output_path}. '
            'No FarmerInputUsage records were inserted.'
        ))