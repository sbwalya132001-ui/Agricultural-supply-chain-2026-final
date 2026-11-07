"""Convert the OCHA/HDX Zambia boundary shapefiles into light GeoJSON for the web map."""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from weather.services import COUNTRY_GEOJSON_PATH, DISTRICT_GEOJSON_PATH, PROVINCE_GEOJSON_PATH


DEFAULT_SHAPEFILE = settings.BASE_DIR / 'zmb_admin_boundaries.shp' / 'zmb_admin2.shp'


class Command(BaseCommand):
    help = (
        'Simplify the Zambia admin-2 (district) shapefile into static/geo/zambia_districts.geojson, '
        'plus province (admin-1) and country outlines drawn over the seasonal map. '
        'Requires pyshp and shapely; run once whenever the boundary data changes.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--shapefile', default=str(DEFAULT_SHAPEFILE))
        parser.add_argument(
            '--tolerance',
            type=float,
            default=0.005,
            help='Simplification tolerance in degrees (0.005 is roughly 500 m).',
        )

    def handle(self, *args, **options):
        try:
            import shapefile
            from shapely.geometry import mapping, shape
            from shapely.ops import unary_union
        except ImportError as exc:
            raise CommandError('Install pyshp and shapely to build the district GeoJSON.') from exc

        shapefile_path = Path(options['shapefile'])
        if not shapefile_path.exists():
            raise CommandError(f'Shapefile not found: {shapefile_path}')

        features = []
        district_shapes = []
        with shapefile.Reader(str(shapefile_path)) as reader:
            for record in reader.iterShapeRecords():
                attributes = record.record.as_dict()
                full_geometry = shape(record.shape.__geo_interface__)
                district_shapes.append(full_geometry)
                geometry = full_geometry.simplify(options['tolerance'], preserve_topology=True)
                features.append({
                    'type': 'Feature',
                    'properties': {
                        'name': attributes['adm2_name'],
                        'province': attributes['adm1_name'],
                        'pcode': attributes['adm2_pcode'],
                        'center_lat': round(attributes['center_lat'], 5),
                        'center_lon': round(attributes['center_lon'], 5),
                    },
                    'geometry': _round_coordinates(mapping(geometry)),
                })

        _write_collection(DISTRICT_GEOJSON_PATH, features)

        # Provinces come from the admin-1 file beside the districts; the country
        # outline is the union of the districts so it matches them exactly.
        province_features = []
        with shapefile.Reader(str(shapefile_path.with_name('zmb_admin1.shp'))) as reader:
            for record in reader.iterShapeRecords():
                geometry = shape(record.shape.__geo_interface__).simplify(
                    options['tolerance'], preserve_topology=True,
                )
                province_features.append({
                    'type': 'Feature',
                    'properties': {'name': record.record.as_dict()['adm1_name']},
                    'geometry': _round_coordinates(mapping(geometry)),
                })
        _write_collection(PROVINCE_GEOJSON_PATH, province_features)

        country = unary_union(district_shapes).simplify(options['tolerance'], preserve_topology=True)
        _write_collection(COUNTRY_GEOJSON_PATH, [{
            'type': 'Feature',
            'properties': {'name': 'Zambia'},
            'geometry': _round_coordinates(mapping(country)),
        }])

        for path, count in (
            (DISTRICT_GEOJSON_PATH, len(features)),
            (PROVINCE_GEOJSON_PATH, len(province_features)),
            (COUNTRY_GEOJSON_PATH, 1),
        ):
            self.stdout.write(self.style.SUCCESS(
                f'Wrote {count} feature(s) to {path} ({path.stat().st_size / 1024:.0f} KB).'
            ))


def _write_collection(path, features):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({'type': 'FeatureCollection', 'features': features}, separators=(',', ':')),
        encoding='utf-8',
    )


def _round_coordinates(geometry, places=4):
    """Round coordinates to ~11 m to keep the file small."""
    def round_nested(value):
        if isinstance(value, (list, tuple)) and value and isinstance(value[0], (int, float)):
            return [round(coordinate, places) for coordinate in value]
        return [round_nested(item) for item in value]

    return {'type': geometry['type'], 'coordinates': round_nested(geometry['coordinates'])}
