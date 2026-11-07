"""Fetch SEAS5 on a grid over Zambia and pre-render the smooth seasonal-map tiles."""
from django.core.management.base import BaseCommand, CommandError

from forecasting.climate import target_rainfall_season
from weather.seas5_field import build_seas5_field, seas5_tiles_dir
from weather.services import WeatherServiceError


class Command(BaseCommand):
    help = (
        'Fetch ECMWF SEAS5 Oct-Mar rainfall on a 0.5 degree grid and render it to '
        'static/tiles/seas5/<season>/ the way ZEWCO renders its forecast fields.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--season', default='', help='e.g. 2026/2027; defaults to the current planning season.')

    def handle(self, *args, **options):
        season = options['season'] or target_rainfall_season()
        try:
            meta = build_seas5_field(season)
        except WeatherServiceError as exc:
            raise CommandError(str(exc)) from exc
        low, high = meta['departure_range_percent']
        self.stdout.write(self.style.SUCCESS(
            f"Rendered {meta['tiles']} tiles from {meta['grid_points']} SEAS5 grid points to "
            f"{seas5_tiles_dir(season)} (departure {low:+.1f}% to {high:+.1f}%)."
        ))
