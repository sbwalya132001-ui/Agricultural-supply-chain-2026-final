"""Load Zambia's FAOSTAT national series as the long-run trend for each input type."""
import csv
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from forecasting.models import NationalInputSeries


DEFAULT_PATH = Path(__file__).resolve().parents[2] / 'data' / 'faostat_zambia_inputs.csv'

# (FAOSTAT domain, item code) -> input type it stands in for, and how a
# FAOSTAT year maps to a rainy season.
#  - Fertilizer use (RFN) is per calendar year; inputs for the Y/Y+1 season are
#    bought and applied from October to January, mostly in year Y.
#  - Maize area harvested (QCL) in year Y is the crop planted in season Y-1/Y,
#    and seed demand follows the area planted.
# D Compound (10-20-10) is the main phosphate fertilizer in FISP and urea
# (46% N) the main nitrogen one, so P2O5 tracks D Compound and N tracks urea.
SERIES = {
    ('RFN', '3102'): ('fertilizer_urea', 0),
    ('RFN', '3103'): ('fertilizer_d', 0),
    ('QCL', '56'): ('seed_maize', -1),
}
SOURCE_NAMES = {
    'RFN': 'FAOSTAT Fertilizers by Nutrient, agricultural use',
    'QCL': 'FAOSTAT Crops and livestock products, maize area harvested',
}


class Command(BaseCommand):
    help = 'Import the FAOSTAT Zambia fertilizer-use and maize-area series used as national demand trends.'

    def add_arguments(self, parser):
        parser.add_argument('--path', default=str(DEFAULT_PATH), help='Extracted FAOSTAT Zambia CSV.')

    def handle(self, *args, **options):
        path = Path(options['path'])
        try:
            with path.open(encoding='utf-8', newline='') as handle:
                rows = list(csv.DictReader(handle))
        except OSError as exc:
            raise CommandError(f'Cannot read {path}: {exc}') from exc

        counts = {}
        with transaction.atomic():
            for row in rows:
                mapping = SERIES.get((row['faostat_domain'], row['item_code']))
                if mapping is None or not row['value']:
                    continue
                input_type, year_offset = mapping
                start = int(row['year']) + year_offset
                NationalInputSeries.objects.update_or_create(
                    input_type=input_type,
                    season=f'{start}/{start + 1}',
                    defaults={
                        'value': Decimal(row['value']).quantize(Decimal('0.01')),
                        'unit': row['unit'],
                        'source': f"{SOURCE_NAMES[row['faostat_domain']]} ({row['item']})",
                        'flag': row['flag'],
                    },
                )
                counts[input_type] = counts.get(input_type, 0) + 1

        for input_type, count in sorted(counts.items()):
            self.stdout.write(f'{input_type}: {count} seasons')
        self.stdout.write(self.style.SUCCESS(f'Imported {sum(counts.values())} FAOSTAT national values.'))
