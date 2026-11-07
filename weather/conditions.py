"""WMO weather interpretation codes (as returned by Open-Meteo) -> label and icon.

Icons are solid Bootstrap Icons (https://icons.getbootstrap.com) class names; `tone`
picks the icon colour on the weather page.
"""

# code: (label, Bootstrap Icons class, tone)
WMO_CONDITIONS = {
    0: ('Clear sky', 'bi-sun-fill', 'sun'),
    1: ('Mainly clear', 'bi-cloud-sun-fill', 'sun'),
    2: ('Partly cloudy', 'bi-cloud-sun-fill', 'cloud'),
    3: ('Overcast', 'bi-clouds-fill', 'cloud'),
    45: ('Fog', 'bi-cloud-fog2-fill', 'cloud'),
    48: ('Freezing fog', 'bi-cloud-fog2-fill', 'cloud'),
    51: ('Light drizzle', 'bi-cloud-drizzle-fill', 'rain'),
    53: ('Drizzle', 'bi-cloud-drizzle-fill', 'rain'),
    55: ('Heavy drizzle', 'bi-cloud-drizzle-fill', 'rain'),
    56: ('Freezing drizzle', 'bi-cloud-sleet-fill', 'rain'),
    57: ('Heavy freezing drizzle', 'bi-cloud-sleet-fill', 'rain'),
    61: ('Light rain', 'bi-cloud-rain-fill', 'rain'),
    63: ('Rain', 'bi-cloud-rain-fill', 'rain'),
    65: ('Heavy rain', 'bi-cloud-rain-heavy-fill', 'rain'),
    66: ('Freezing rain', 'bi-cloud-sleet-fill', 'rain'),
    67: ('Heavy freezing rain', 'bi-cloud-sleet-fill', 'rain'),
    71: ('Light snow', 'bi-cloud-snow-fill', 'cloud'),
    73: ('Snow', 'bi-cloud-snow-fill', 'cloud'),
    75: ('Heavy snow', 'bi-cloud-snow-fill', 'cloud'),
    77: ('Snow grains', 'bi-cloud-snow-fill', 'cloud'),
    80: ('Light showers', 'bi-cloud-drizzle-fill', 'rain'),
    81: ('Showers', 'bi-cloud-rain-fill', 'rain'),
    82: ('Heavy showers', 'bi-cloud-rain-heavy-fill', 'rain'),
    85: ('Snow showers', 'bi-cloud-snow-fill', 'cloud'),
    86: ('Heavy snow showers', 'bi-cloud-snow-fill', 'cloud'),
    95: ('Thunderstorm', 'bi-cloud-lightning-rain-fill', 'storm'),
    96: ('Thunderstorm with hail', 'bi-cloud-hail-fill', 'storm'),
    99: ('Severe thunderstorm with hail', 'bi-cloud-hail-fill', 'storm'),
}


def weather_condition(code):
    """Return {'label', 'icon', 'tone'} for a WMO code, or None when unknown."""
    if code is None or code not in WMO_CONDITIONS:
        return None
    label, icon, tone = WMO_CONDITIONS[code]
    return {'label': label, 'icon': icon, 'tone': tone}
