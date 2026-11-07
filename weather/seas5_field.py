"""Smooth ECMWF SEAS5 season-rainfall field for the seasonal map, rendered like ZEWCO.

The district choropleth steps at every boundary; rainfall does not. So, following
ZEWCO's zambia_seasonal._render_grid, SEAS5 is fetched on a regular grid, its
October-March departure from the model normal is interpolated to a 1/30 degree
grid, smoothed inside the country, refined four times, masked to Zambia and
pre-rendered to map tiles through the same colour ramp the legend shows.
"""
import json
import time
from datetime import date, datetime

import numpy as np
from django.conf import settings
from scipy.interpolate import RegularGridInterpolator
from scipy.ndimage import distance_transform_edt, gaussian_filter

from forecasting.climate import SEAS5_MAP_COLORS, season_slug, target_rainfall_season

from . import rasters
from .services import (
    COUNTRY_GEOJSON_PATH,
    ECMWF_SEASONAL_MODEL,
    LOCAL_TIMEZONE,
    OPEN_METEO_SEASONAL_URL,
    SEASONAL_BATCH_SIZE,
    WeatherServiceError,
    _request_json,
)

# Domain, resolution and smoothing are ZEWCO's (zambia_seasonal.py).
LON_MIN, LON_MAX, LAT_MIN, LAT_MAX = 21.5, 34.2, -18.6, -7.8
BOUNDS = (LON_MIN, LAT_MIN, LON_MAX, LAT_MAX)
RES = 1 / 30.0
UPSAMPLE = 4
FILL_SIGMA = 6
# SEAS5 sample spacing; finer than this adds requests without adding detail.
GRID_STEP = 0.5
# Open-Meteo counts each grid point as a call and limits calls per minute, so a
# rejected batch is retried after a pause.
BATCH_ATTEMPTS = 4
RETRY_PAUSE_SECONDS = 20

# One tileset per season: static/tiles/seas5/<2026_27>/, with field.json beside it.
SEAS5_TILES_ROOT = settings.BASE_DIR / 'static' / 'tiles' / 'seas5'


def seas5_tiles_dir(season):
    return SEAS5_TILES_ROOT / season_slug(season)


def _meta_path(season):
    return SEAS5_TILES_ROOT / f'{season_slug(season)}.json'

# Colour stops sit at the centre of each category (thresholds -15/-5/+5/+15%),
# so a district's map colour and its category agree.
SEAS5_RAMP = rasters.Ramp((
    rasters.Stop(-20.0, SEAS5_MAP_COLORS['below'], '-20%'),
    rasters.Stop(-10.0, SEAS5_MAP_COLORS['normal_below'], '-10%'),
    rasters.Stop(0.0, SEAS5_MAP_COLORS['normal'], '0%'),
    rasters.Stop(10.0, SEAS5_MAP_COLORS['normal_above'], '+10%'),
    rasters.Stop(20.0, SEAS5_MAP_COLORS['above'], '+20%'),
))


def _season_months(forecast_season):
    start_year = int(forecast_season.split('/')[0])
    return date(start_year, 10, 1), date(start_year + 1, 3, 1)


def _location_departure(location, first_month, last_month, current_month):
    """Oct-Mar rainfall departure (%) from the SEAS5 model normal at one grid point."""
    monthly = location.get('monthly', {})
    forecast_total = normal_total = 0.0
    for month, mean, anomaly in zip(
        monthly.get('time', []),
        monthly.get('precipitation_mean', []),
        monthly.get('precipitation_anomaly', []),
    ):
        valid_month = date.fromisoformat(month).replace(day=1)
        if mean is None or anomaly is None or not first_month <= valid_month <= last_month:
            continue
        if valid_month < current_month:
            continue
        forecast_total += mean
        normal_total += mean - anomaly
    if normal_total <= 0:
        return np.nan
    return (forecast_total - normal_total) / normal_total * 100.0


def fetch_seas5_grid(forecast_season):
    """Return (lat, lon, departure grid) of SEAS5 season departures over the map domain."""
    lat = np.arange(LAT_MIN + 0.1, LAT_MAX, GRID_STEP)
    lon = np.arange(LON_MIN, LON_MAX, GRID_STEP)
    lon_grid, lat_grid = np.meshgrid(lon, lat)
    points = list(zip(lat_grid.ravel().round(2), lon_grid.ravel().round(2)))
    first_month, last_month = _season_months(forecast_season)
    today = datetime.now(LOCAL_TIMEZONE).date()
    current_month = date(today.year, today.month, 1)

    departures = []
    for start in range(0, len(points), SEASONAL_BATCH_SIZE):
        batch = points[start:start + SEASONAL_BATCH_SIZE]
        payload = _request_with_retry({
            'latitude': ','.join(str(point[0]) for point in batch),
            'longitude': ','.join(str(point[1]) for point in batch),
            'monthly': 'precipitation_mean,precipitation_anomaly',
            'models': ECMWF_SEASONAL_MODEL,
            'timezone': 'Africa/Lusaka',
        })
        locations = payload if isinstance(payload, list) else [payload]
        if len(locations) != len(batch):
            raise WeatherServiceError('The seasonal weather service returned an unexpected number of locations.')
        departures.extend(
            _location_departure(location, first_month, last_month, current_month)
            for location in locations
        )
    grid = np.array(departures, dtype=float).reshape(lat_grid.shape)
    if not np.isfinite(grid).any():
        raise WeatherServiceError('The seasonal weather service returned no usable SEAS5 rainfall for the map.')
    return lat, lon, grid


def _request_with_retry(params):
    for attempt in range(BATCH_ATTEMPTS):
        try:
            return _request_json(OPEN_METEO_SEASONAL_URL, params)
        except WeatherServiceError:
            if attempt == BATCH_ATTEMPTS - 1:
                raise
            time.sleep(RETRY_PAUSE_SECONDS * (attempt + 1))


def _country_geometry():
    import shapely
    from shapely.geometry import shape

    collection = json.loads(COUNTRY_GEOJSON_PATH.read_text(encoding='utf-8'))
    geometry = shapely.union_all([shape(feature['geometry']) for feature in collection['features']])
    shapely.prepare(geometry)
    return geometry


def _fill_gaps(values):
    """Give missing grid points their nearest valid neighbour's value."""
    missing = ~np.isfinite(values)
    if not missing.any():
        return values
    _, indices = distance_transform_edt(missing, return_indices=True)
    return values[tuple(indices)]


def _interpolate(field, lat, lon, target_lon, target_lat):
    """ZEWCO's interpolation, with its one-cell edge pad."""
    dlat, dlon = lat[1] - lat[0], lon[1] - lon[0]
    padded_lat = np.concatenate([[lat[0] - dlat], lat, [lat[-1] + dlat]])
    padded_lon = np.concatenate([[lon[0] - dlon], lon, [lon[-1] + dlon]])
    interpolator = RegularGridInterpolator(
        (padded_lat, padded_lon), np.pad(field, 1, mode='edge'), bounds_error=False, fill_value=None,
    )
    points = np.stack([target_lat.ravel(), target_lon.ravel()], axis=-1)
    return interpolator(points).reshape(target_lon.shape)


def _smooth_inside(values, inside):
    """ZEWCO's normalised Gaussian smoothing, restricted to the country."""
    clipped = np.where(inside, values, np.nan)
    valid = np.isfinite(clipped)
    numerator = gaussian_filter(np.nan_to_num(clipped, nan=0.0), sigma=FILL_SIGMA)
    denominator = gaussian_filter(valid.astype(float), sigma=FILL_SIGMA)
    return numerator / (denominator + 1e-8)


def render_seas5_field(lat, lon, departures):
    """Turn sampled departures into the masked, smoothed fine grid (row zero = north)."""
    import shapely

    country = _country_geometry()
    fine_lat = np.arange(LAT_MIN, LAT_MAX + RES / 2, RES)
    fine_lon = np.arange(LON_MIN, LON_MAX + RES / 2, RES)
    lon_grid, lat_grid = np.meshgrid(fine_lon, fine_lat)
    inside = shapely.contains_xy(country, lon_grid, lat_grid)

    field = _interpolate(_fill_gaps(departures), lat, lon, lon_grid, lat_grid)
    smoothed = _smooth_inside(field, inside)

    upsampled_lat = np.linspace(fine_lat[0], fine_lat[-1], len(fine_lat) * UPSAMPLE)
    upsampled_lon = np.linspace(fine_lon[0], fine_lon[-1], len(fine_lon) * UPSAMPLE)
    up_lon_grid, up_lat_grid = np.meshgrid(upsampled_lon, upsampled_lat)
    interpolator = RegularGridInterpolator(
        (fine_lat, fine_lon), smoothed, bounds_error=False, fill_value=None,
    )
    points = np.stack([up_lat_grid.ravel(), up_lon_grid.ravel()], axis=-1)
    fine = interpolator(points).reshape(up_lon_grid.shape)
    up_inside = shapely.contains_xy(country, up_lon_grid, up_lat_grid)
    return np.flipud(np.where(up_inside, fine, np.nan))


def build_seas5_field(forecast_season=None):
    """Fetch SEAS5 on the grid and rebuild the season's smooth map tiles. Returns the field metadata."""
    forecast_season = forecast_season or target_rainfall_season()
    lat, lon, departures = fetch_seas5_grid(forecast_season)
    field = render_seas5_field(lat, lon, departures)
    tile_count = rasters.tile_grid(
        field, BOUNDS, ramp=SEAS5_RAMP, tiles_dir=seas5_tiles_dir(forecast_season),
    )
    meta = {
        'season': forecast_season,
        'retrieved': datetime.now(LOCAL_TIMEZONE).date().isoformat(),
        'grid_step_degrees': GRID_STEP,
        'grid_points': int(departures.size),
        'tiles': tile_count,
        'bounds': list(BOUNDS),
        'min_zoom': 4,
        'max_zoom': 8,
        'departure_range_percent': [
            round(float(np.nanmin(field)), 1), round(float(np.nanmax(field)), 1),
        ],
    }
    _meta_path(forecast_season).write_text(json.dumps(meta, indent=2), encoding='utf-8')
    return meta


def load_seas5_field_meta(season):
    if not seas5_tiles_dir(season).is_dir():
        return None
    try:
        return json.loads(_meta_path(season).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
