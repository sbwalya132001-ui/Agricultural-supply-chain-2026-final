"""Simple, transparent ZMD seasonal outlook adjustments for demand forecasts."""
import json
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.utils import timezone


OUTLOOK_PERIODS = ('OND', 'NDJ', 'DJF', 'JFM')
# Planning moves to the next October-March rainy season from July, when the
# seasonal outlooks for it start being issued. settings.FORECAST_SEASON
# ("YYYY/YYYY") pins a season instead.
SEASON_ROLLOVER_MONTH = 7

# Each district's majority ZMD consensus-zone category per outlook period, one
# file per season (zmd_2026_27_districts.json for 2026/2027), built by the
# build_zmd_district_outlook management command. Categories are relative to the
# 1991-2020 rainfall normal, not exact rainfall totals or probability values.
ZMD_DATA_DIR = Path(__file__).resolve().parent / 'data'


def target_rainfall_season(today=None):
    """The rainy season ("YYYY/YYYY") that forecasts and weather scenarios plan for."""
    pinned = getattr(settings, 'FORECAST_SEASON', '')
    if pinned:
        return pinned
    today = today or timezone.localdate()
    start = today.year if today.month >= SEASON_ROLLOVER_MONTH else today.year - 1
    return f'{start}/{start + 1}'


def season_slug(season):
    """'2026/2027' -> '2026_27', used in data file and tile folder names."""
    start, end = season.split('/')
    return f'{start}_{end[-2:]}'


def zmd_outlook_path(season):
    return ZMD_DATA_DIR / f'zmd_{season_slug(season)}_districts.json'


@lru_cache(maxsize=4)
def load_zmd_district_outlooks(season):
    """Return {district: {period: {'category', 'confidence', 'share'}}} for a season, or {}."""
    try:
        data = json.loads(zmd_outlook_path(season).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    return {name: district['outlook'] for name, district in data['districts'].items()}

RAINFALL_CATEGORY_LABELS = {
    'below': 'Below Normal',
    'normal_below': 'Normal to Below Normal',
    'normal': 'Normal',
    'normal_above': 'Normal to Above Normal',
    'above': 'Above Normal',
}

# Map colours. ZMD categories use the colours of the official ZMD forecast
# maps (as reproduced in ZEWCO for 2026/27); the JFM map was issued with its own
# slightly different palette. SEAS5 uses ZEWCO's seasonal-model scheme: an
# orange-brown dry family, grey normal and a blue wet family.
ZMD_MAP_COLORS = {
    'below': '#C47A39',
    'normal_below': '#FFF066',
    'normal_above': '#00E0E0',
    'above': '#1A4DFF',
}
ZMD_PERIOD_MAP_COLORS = {
    'OND': ZMD_MAP_COLORS,
    'NDJ': ZMD_MAP_COLORS,
    'DJF': ZMD_MAP_COLORS,
    'JFM': {
        'below': '#C9A24D',
        'normal_below': '#F5E800',
        'normal_above': '#23E8E7',
        'above': '#0000FF',
    },
}
SEAS5_MAP_COLORS = {
    'below': '#CC4C02',
    'normal_below': '#FE9929',
    'normal': '#D0D0D0',
    'normal_above': '#74A9CF',
    'above': '#0570B0',
}

# Upper bounds (exclusive) of each category for the SEAS5 October-March
# rainfall departure, in % of the model's own normal: below -15% is Below
# Normal, -15% to -5% Normal to Below, -5% to +5% Normal, and so on.
SEAS5_CATEGORY_THRESHOLDS = (
    (Decimal('-15'), 'below'),
    (Decimal('-5'), 'normal_below'),
    (Decimal('5'), 'normal'),
    (Decimal('15'), 'normal_above'),
)

# Provisional per-input sensitivity to the rainfall adjustment. Top-dressing
# urea is often skipped in dry spells, while drought-tolerant sunflower and
# soybean demand moves less. Pending agronomist calibration, like the
# adjustments below.
INPUT_RAINFALL_SENSITIVITY = {
    'fertilizer_d': Decimal('1.0'),
    'fertilizer_urea': Decimal('1.2'),
    'seed_maize': Decimal('1.0'),
    'seed_other': Decimal('1.0'),
    'seed_soybeans': Decimal('0.8'),
    'seed_sunflower': Decimal('0.5'),
    'seed_popcorn': Decimal('1.0'),
}

# Conservative, provisional scenario assumptions: each seasonal window nudges
# demand by at most five percent. This is not a ZMD probability or an agronomic
# elasticity; it is explicitly shown as a planning adjustment pending local
# agronomist calibration. Positive rainfall outlooks modestly support planned
# planting/input use; dry outlooks modestly reduce aggregate planned demand.
RAINFALL_DEMAND_ADJUSTMENTS = {
    'below': Decimal('-5.00'),
    'normal_below': Decimal('-2.50'),
    'normal': Decimal('0.00'),
    'normal_above': Decimal('2.50'),
    'above': Decimal('5.00'),
}


def get_weather_demand_adjustment(district, season):
    """Return the season's equal-period average ZMD adjustment and its source categories."""
    outlook = next(
        (value for name, value in load_zmd_district_outlooks(season).items()
         if name.casefold() == district.strip().casefold()),
        None,
    )
    if outlook is None or any(period not in outlook for period in OUTLOOK_PERIODS):
        return None

    adjustment = sum(
        (RAINFALL_DEMAND_ADJUSTMENTS[outlook[period]['category']] for period in OUTLOOK_PERIODS),
        Decimal('0'),
    ) / Decimal(len(OUTLOOK_PERIODS))
    adjustment = adjustment.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    summary = '; '.join(
        f'{period}: {RAINFALL_CATEGORY_LABELS[outlook[period]["category"]]}'
        for period in OUTLOOK_PERIODS
    )
    return {'adjustment_percent': adjustment, 'summary': summary, 'source': 'ZMD outlook'}


def seas5_rainfall_category(anomaly_percent):
    """Map a SEAS5 season rainfall departure (%) to a ZMD-style category."""
    for upper_bound, category in SEAS5_CATEGORY_THRESHOLDS:
        if anomaly_percent < upper_bound:
            return category
    return 'above'


def get_seas5_demand_adjustment(seasonal_outlook):
    """Return the demand adjustment implied by a cached SEAS5 season outlook."""
    if not seasonal_outlook or seasonal_outlook.get('rainfall_anomaly_percent') is None:
        return None
    anomaly = seasonal_outlook['rainfall_anomaly_percent']
    category = seas5_rainfall_category(anomaly)
    sign = '+' if anomaly > 0 else ''
    return {
        'adjustment_percent': RAINFALL_DEMAND_ADJUSTMENTS[category],
        'summary': (
            f'SEAS5 Oct-Mar rainfall {sign}{anomaly}% vs model normal '
            f'({seasonal_outlook["months_with_rainfall"]} months): {RAINFALL_CATEGORY_LABELS[category]}'
        ),
        'source': 'ECMWF SEAS5',
    }


def scale_adjustment_for_input(adjustment, input_type):
    """Apply the input's rainfall sensitivity to a district-level adjustment."""
    sensitivity = INPUT_RAINFALL_SENSITIVITY.get(input_type, Decimal('1.0'))
    scaled = (adjustment['adjustment_percent'] * sensitivity).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP,
    )
    summary = adjustment['summary']
    if sensitivity != Decimal('1.0'):
        summary = f'{summary}; input sensitivity x{sensitivity}'
    return {**adjustment, 'adjustment_percent': scaled, 'summary': summary[:180]}