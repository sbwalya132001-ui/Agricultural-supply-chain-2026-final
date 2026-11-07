"""Copy ZEWCO's pre-rendered ZMD seasonal forecast tiles into the map's static files."""
import shutil
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from forecasting.climate import OUTLOOK_PERIODS, target_rainfall_season
from weather.seasonal_map import zmd_tiles_dir


class Command(BaseCommand):
    help = (
        'Copy ZEWCO\'s zambia_expert_rainfall tiles (one tileset per outlook period, '
        'e.g. OND-2026/) into static/tiles/zmd/<season>/<period>/. The fields are ZEWCO\'s '
        'expert-anchored rendering of the official ZMD forecast maps.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'raster_dir',
            help='ZEWCO data-pipeline/output/rasters/zambia_expert_rainfall folder.',
        )
        parser.add_argument('--season', default='', help='e.g. 2026/2027; defaults to the current planning season.')

    def handle(self, *args, **options):
        raster_dir = Path(options['raster_dir'])
        if not raster_dir.is_dir():
            raise CommandError(f'Folder not found: {raster_dir}')

        season = options['season'] or target_rainfall_season()
        start_year = int(season[:4])
        for period in OUTLOOK_PERIODS:
            # ZEWCO names each tileset by its period and the year it starts in.
            step = f'{period}-{start_year + 1 if period == "JFM" else start_year}'
            source = raster_dir / step
            if not source.is_dir():
                raise CommandError(f'No {step} tileset in {raster_dir} for the {season} season.')
            target = zmd_tiles_dir(season) / period
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
            count = sum(1 for _ in target.rglob('*.png'))
            self.stdout.write(self.style.SUCCESS(f'{season} {period}: copied {count} tiles from {step}.'))
