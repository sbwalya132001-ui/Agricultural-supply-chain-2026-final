"""Register the FISP Southern Province survey farmers and their 2021/2022 input use."""
from decimal import Decimal
from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from farmers.models import Farmer, FarmerInputUsage


# Iyioku, G. (2024) "Farmer Input Support Programme - Southern Province Data",
# Mendeley Data, V1, doi:10.17632/fspbympxky.1 (CC BY 4.0). Collected July to
# September 2022 about the last farming season, i.e. 2021/2022.
DEFAULT_PATH = Path(__file__).resolve().parents[2] / 'data' / 'fisp_southern_province_2021_22.xlsx'
SURVEY_SEASON = '2021/2022'
DISTRICT_CODES = {1: 'Choma', 2: 'Kalomo', 3: 'Monze', 4: 'Pemba'}
# Survey questions are matched on their number, e.g. "57a) Quantity of maize seeds (in kg) ?".
COLUMNS = {
    'number': 'No.',
    'district': '2)',
    'total_ha': '13)',
    'seed_kg': '57a)',
    'fertilizer_kg': '58a)',
}
# The survey records total fertilizer on maize. The standard FISP pack holds
# equal amounts of D Compound (basal) and urea (top dressing), so it is split 50/50.
FERTILIZER_SPLIT = {'fertilizer_d': Decimal('0.5'), 'fertilizer_urea': Decimal('0.5')}


class Command(BaseCommand):
    help = 'Import the 340 FISP Southern Province survey farmers and their 2021/2022 maize seed and fertilizer use.'

    def add_arguments(self, parser):
        parser.add_argument('--path', default=str(DEFAULT_PATH), help='Survey workbook (Sheet1).')

    def handle(self, *args, **options):
        try:
            frame = pd.read_excel(options['path'], sheet_name='Sheet1')
        except (OSError, ValueError) as exc:
            raise CommandError(f'Cannot read the survey workbook: {exc}') from exc

        columns = {}
        for key, prefix in COLUMNS.items():
            matches = [column for column in frame.columns if str(column).strip().startswith(prefix)]
            if len(matches) != 1:
                raise CommandError(f'Expected one survey column starting with "{prefix}", found {len(matches)}.')
            columns[key] = matches[0]

        farmers = 0
        usages = 0
        with transaction.atomic():
            for values in frame.to_dict('records'):
                number = int(values[columns['number']])
                district = DISTRICT_CODES.get(int(values[columns['district']]))
                if district is None:
                    raise CommandError(f'Respondent {number} has an unknown district code.')
                national_id = f'FISP-SP-{number:04d}'
                farmer, _ = Farmer.objects.update_or_create(
                    national_id=national_id,
                    defaults={
                        'first_name': 'Survey respondent',
                        'last_name': f'{number:04d}',
                        'district': district,
                        'farm_size_hectares': Decimal(str(values[columns['total_ha']])),
                        'primary_crop': 'maize',
                    },
                )
                farmers += 1

                fertilizer = Decimal(str(values[columns['fertilizer_kg']]))
                quantities = {'seed_maize': Decimal(str(values[columns['seed_kg']]))}
                quantities.update({
                    input_type: fertilizer * share for input_type, share in FERTILIZER_SPLIT.items()
                })
                for input_type, quantity in quantities.items():
                    FarmerInputUsage.objects.update_or_create(
                        source_event_id=f'{national_id}-{SURVEY_SEASON}-{input_type}',
                        defaults={
                            'farmer': farmer,
                            'season': SURVEY_SEASON,
                            'input_type': input_type,
                            'quantity_kg': quantity.quantize(Decimal('0.01')),
                        },
                    )
                    usages += 1

        self.stdout.write(self.style.SUCCESS(
            f'Imported {farmers} survey farmers and {usages} {SURVEY_SEASON} input-usage records.'
        ))
