"""Gridded field -> static XYZ PNG tiles for the seasonal rainfall map.

Ported from ZEWCO's data-pipeline/src/rasters.py so this map draws forecasts the
same way ZEWCO does: a continuous field is pre-rendered to Web Mercator tiles,
transparent outside the country, and the browser shows it as a plain tile layer
with district outlines drawn over it.
"""
import math
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

TILE_SIZE = 256

# Web Mercator cannot represent the poles; the standard cut-off.
MAX_LATITUDE = 85.0511287798066


def _hex_to_rgb(value):
    value = value.lstrip('#')
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


@dataclass(frozen=True)
class Stop:
    """One anchor of a colour ramp: a data value, its colour, and its legend label."""

    value: float
    color: str
    label: str


@dataclass(frozen=True)
class Ramp:
    """A continuous colour ramp, interpolated in RGB between its stops."""

    stops: tuple

    def colors(self, values):
        anchors = np.array([stop.value for stop in self.stops], dtype=float)
        rgb = np.array([_hex_to_rgb(stop.color) for stop in self.stops], dtype=float)
        clipped = np.clip(np.nan_to_num(values, nan=anchors[0]), anchors[0], anchors[-1])
        out = np.empty(clipped.shape + (3,), dtype=np.uint8)
        for channel in range(3):
            out[..., channel] = np.round(np.interp(clipped, anchors, rgb[:, channel])).astype(np.uint8)
        return out


def _lonlat_to_tile(lon, lat, zoom):
    lat = max(-MAX_LATITUDE, min(MAX_LATITUDE, lat))
    n = 2.0 ** zoom
    x = (lon + 180.0) / 360.0 * n
    sin_lat = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)) * n
    return x, y


def _tile_pixel_lonlat(zoom, x, y):
    """Longitude and latitude of every pixel centre in one tile."""
    n = 2.0 ** zoom
    px = (x + (np.arange(TILE_SIZE) + 0.5) / TILE_SIZE) / n
    py = (y + (np.arange(TILE_SIZE) + 0.5) / TILE_SIZE) / n
    lon = px * 360.0 - 180.0
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * py))))
    return lon, lat


def _tile_range(bounds, zoom):
    west, south, east, north = bounds
    x0, y0 = _lonlat_to_tile(west, north, zoom)
    x1, y1 = _lonlat_to_tile(east, south, zoom)
    return (
        range(int(math.floor(x0)), int(math.floor(x1)) + 1),
        range(int(math.floor(y0)), int(math.floor(y1)) + 1),
    )


def tile_grid(values, bounds, *, ramp, tiles_dir, zooms=range(4, 9)):
    """Render a continuous field (row zero at the north edge; NaN = transparent).

    Sampling is nearest-neighbour: the source grid is finer than the tile pixels
    at every zoom we publish, so resampling would only blur it. Tiles are built in
    a sibling folder and swapped in at the end, so the map never sees a half-written set.
    """
    tiles_dir = Path(tiles_dir)
    staging = tiles_dir.with_name(f'{tiles_dir.name}.building')
    if staging.exists():
        shutil.rmtree(staging)

    west, south, east, north = bounds
    rows_n, cols_n = values.shape
    written = 0
    for zoom in zooms:
        xs, ys = _tile_range(bounds, zoom)
        for x in xs:
            for y in ys:
                lon, lat = _tile_pixel_lonlat(zoom, x, y)
                col = ((lon - west) / (east - west) * cols_n).astype(int)
                row = ((north - lat) / (north - south) * rows_n).astype(int)
                col_grid, row_grid = np.meshgrid(col, row)
                inside = (
                    (col_grid >= 0) & (col_grid < cols_n)
                    & (row_grid >= 0) & (row_grid < rows_n)
                )
                sampled = values[np.clip(row_grid, 0, rows_n - 1), np.clip(col_grid, 0, cols_n - 1)]
                shown = np.isfinite(sampled) & inside
                # Fully transparent tiles are written, not skipped, so panning
                # inside the bounds never requests a tile that 404s.
                alpha = np.where(shown, 255, 0).astype(np.uint8)
                rgba = np.dstack([ramp.colors(sampled), alpha])
                out = staging / str(zoom) / str(x)
                out.mkdir(parents=True, exist_ok=True)
                Image.fromarray(rgba, mode='RGBA').save(out / f'{y}.png', optimize=True)
                written += 1

    if tiles_dir.exists():
        shutil.rmtree(tiles_dir)
    staging.rename(tiles_dir)
    return written
