"""Data for the interactive Zambia seasonal rainfall map (SEAS5 and ZMD layers)."""
from django.conf import settings

from forecasting.climate import (
    OUTLOOK_PERIODS,
    RAINFALL_CATEGORY_LABELS,
    SEAS5_MAP_COLORS,
    ZMD_PERIOD_MAP_COLORS,
    load_zmd_district_outlooks,
    season_slug,
    seas5_rainfall_category,
    target_rainfall_season,
)

from .seas5_field import BOUNDS, load_seas5_field_meta
from .services import get_national_seasonal_outlooks, season_rainfall_departure

TILE_PATTERN = '{z}/{x}/{y}.png'
ZMD_TILES_ROOT = settings.BASE_DIR / 'static' / 'tiles' / 'zmd'


def zmd_tiles_dir(season):
    """static/tiles/zmd/<2026_27>/, holding one tileset per outlook period."""
    return ZMD_TILES_ROOT / season_slug(season)


def seasonal_map_data():
    """SEAS5 and ZMD outlooks per district, serialised for the interactive map."""
    season = target_rainfall_season()
    seas5 = {}
    for district, months in get_national_seasonal_outlooks(season).items():
        departure, months_used = season_rainfall_departure(months)
        seas5[district] = {
            'retrieved': months[0].retrieved_date.isoformat(),
            'departure_percent': float(departure) if departure is not None else None,
            'category': seas5_rainfall_category(departure) if departure is not None else None,
            'months_used': months_used,
            'months': [
                {
                    'month': f'{outlook.valid_month:%b %Y}',
                    'forecast_mm': _float_or_none(outlook.precipitation_mean_mm),
                    'normal_mm': (
                        float(outlook.precipitation_mean_mm - outlook.precipitation_anomaly_mm)
                        if outlook.precipitation_mean_mm is not None
                        and outlook.precipitation_anomaly_mm is not None
                        else None
                    ),
                    'anomaly_mm': _float_or_none(outlook.precipitation_anomaly_mm),
                }
                for outlook in months
            ],
        }
    return {
        'season': season,
        'periods': list(OUTLOOK_PERIODS),
        'labels': RAINFALL_CATEGORY_LABELS,
        'colors': {'seas5': SEAS5_MAP_COLORS, 'zmd': ZMD_PERIOD_MAP_COLORS},
        'fields': _field_tiles(season),
        'seas5': seas5,
        'zmd': load_zmd_district_outlooks(season),
    }


def _field_tiles(season):
    """Tile URL templates for the season's smooth forecast fields that exist on disk."""
    slug = season_slug(season)
    tiles_url = f'{settings.STATIC_URL}tiles/'
    seas5_meta = load_seas5_field_meta(season)
    seas5 = None
    if seas5_meta:
        # The retrieval date busts browser caches when the field is rebuilt.
        seas5 = {
            'url': f"{tiles_url}seas5/{slug}/{TILE_PATTERN}?v={seas5_meta['retrieved']}",
            'retrieved': seas5_meta['retrieved'],
        }
    return {
        'bounds': BOUNDS,
        'min_zoom': 4,
        'max_zoom': 8,
        'seas5': seas5,
        'zmd': {
            period: f'{tiles_url}zmd/{slug}/{period}/{TILE_PATTERN}'
            for period in OUTLOOK_PERIODS
            if (zmd_tiles_dir(season) / period).is_dir()
        },
    }


def _float_or_none(value):
    return float(value) if value is not None else None
