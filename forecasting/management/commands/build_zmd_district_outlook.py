"""Assign each Zambian district its majority ZMD seasonal-outlook zone per season."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from forecasting.climate import OUTLOOK_PERIODS, target_rainfall_season, zmd_outlook_path
from weather.management.commands.build_district_geojson import DEFAULT_SHAPEFILE


# ZMD zone files carry a numeric final category per polygon.
ZMD_CATEGORY_CODES = {
    1: 'below',
    2: 'normal_below',
    3: 'normal_above',
    4: 'above',
}


class Command(BaseCommand):
    help = (
        'Overlay a season\'s ZMD consensus zones (one GeoJSON per period, e.g. OND-2026.geojson) '
        'on the district boundaries and save each district\'s majority category and confidence.'
    )

    def add_arguments(self, parser):
        parser.add_argument('zones_dir', help='Folder holding OND-*, NDJ-*, DJF-* and JFM-* zone GeoJSON files.')
        parser.add_argument('--shapefile', default=str(DEFAULT_SHAPEFILE))
        parser.add_argument(
            '--season', default='',
            help='Rainy season the zones are for, e.g. 2026/2027. Defaults to the current planning season.',
        )

    def handle(self, *args, **options):
        try:
            import shapefile
            from shapely.geometry import shape
        except ImportError as exc:
            raise CommandError('Install pyshp and shapely to build the ZMD district outlook.') from exc

        season = options['season'] or target_rainfall_season()
        output_path = zmd_outlook_path(season)
        zones_by_period = {}
        for period in OUTLOOK_PERIODS:
            matches = sorted(Path(options['zones_dir']).glob(f'{period}-*.geojson'))
            if len(matches) != 1:
                raise CommandError(f'Expected one {period}-*.geojson zone file, found {len(matches)}.')
            collection = json.loads(matches[0].read_text(encoding='utf-8'))
            zones_by_period[period] = [_zone(feature, shape) for feature in collection['features']]

        districts = {}
        with shapefile.Reader(options['shapefile']) as reader:
            for record in reader.iterShapeRecords():
                attributes = record.record.as_dict()
                boundary = shape(record.shape.__geo_interface__)
                outlook = {}
                for period, zones in zones_by_period.items():
                    # Majority by overlap area; degrees are fine for comparing
                    # shares of the same district.
                    overlaps = [(boundary.intersection(geometry).area, zone) for geometry, zone in zones]
                    area, zone = max(overlaps, key=lambda item: item[0])
                    if area > 0:
                        outlook[period] = {**zone, 'share': round(area / boundary.area, 3)}
                districts[attributes['adm2_name']] = {
                    'pcode': attributes['adm2_pcode'],
                    'province': attributes['adm1_name'],
                    'outlook': outlook,
                }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps({
                'season': season,
                'source': f'ZMD {season} seasonal rainfall outlook consensus zones',
                'method': 'Majority zone by area within each OCHA admin-2 district',
                'districts': districts,
            }, indent=1, sort_keys=True),
            encoding='utf-8',
        )
        complete = sum(len(district['outlook']) == len(OUTLOOK_PERIODS) for district in districts.values())
        self.stdout.write(self.style.SUCCESS(
            f'Wrote {len(districts)} districts ({complete} with all four periods) to {output_path}.'
        ))


def _zone(feature, shape):
    properties = feature['properties']
    code_key = next(key for key in properties if key.startswith('finalcode_'))
    return shape(feature['geometry']), {
        'category': ZMD_CATEGORY_CODES[int(properties[code_key])],
        'confidence': properties.get('finalconfidence', ''),
    }
