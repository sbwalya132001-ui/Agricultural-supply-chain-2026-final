import random
from decimal import Decimal

from django.core.management.base import BaseCommand
from farmers.models import Farmer, FarmerInputUsage

# Seasons in chronological order. ARIMA needs several ordered data points
# per district/input_type combo to detect a trend, so we generate 8 seasons.
SEASONS = [
    '2017/2018', '2018/2019', '2019/2020', '2020/2021',
    '2021/2022', '2022/2023', '2023/2024', '2024/2025',
]

INPUT_TYPES = [input_type for input_type, _ in FarmerInputUsage.INPUT_TYPE_CHOICES]


class Command(BaseCommand):
    help = (
        "Seeds simulated historical FarmerInputUsage records across 8 seasons "
        "for existing farmers, so the forecasting app has enough time-series "
        "data to run ARIMA on. Safe to re-run — it skips farmers who already "
        "have seeded data for a given season/input combo."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Delete all existing FarmerInputUsage records before seeding fresh data.',
        )

    def handle(self, *args, **options):
        farmers = list(Farmer.objects.all())

        if not farmers:
            self.stdout.write(self.style.ERROR(
                'No farmers found. Add some farmers first (via /farmers/add/ or /admin/) '
                'before running this command.'
            ))
            return

        if options['clear']:
            deleted_count, _ = FarmerInputUsage.objects.all().delete()
            self.stdout.write(f'Cleared {deleted_count} existing usage records.')

        created_count = 0

        for farmer in farmers:
            # Each farmer gets a slightly different "baseline" usage so the
            # data isn't perfectly uniform, plus a gentle upward trend across
            # seasons (simulating gradually increasing input demand) with
            # some random noise on top — realistic enough for a final-year
            # project without needing real government data.
            base_qty = Decimal(random.uniform(80, 150)).quantize(Decimal('0.01'))

            for season_index, season in enumerate(SEASONS):
                for input_type in INPUT_TYPES:
                    trend_growth = Decimal(season_index * random.uniform(2, 6))
                    noise = Decimal(random.uniform(-10, 10))
                    quantity = base_qty + trend_growth + noise

                    if quantity <= 0:
                        quantity = Decimal('5.00')

                    obj, created = FarmerInputUsage.objects.get_or_create(
                        farmer=farmer,
                        season=season,
                        input_type=input_type,
                        defaults={'quantity_kg': quantity.quantize(Decimal('0.01'))},
                    )
                    if created:
                        created_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'Done. Created {created_count} new usage records across '
            f'{len(farmers)} farmers and {len(SEASONS)} seasons.'
        ))