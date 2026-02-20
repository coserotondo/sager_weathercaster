"""Named wind database for Sager Weathercaster.

Maps geographic regions and wind directions to traditional local wind names.
Regions are listed most-specific first; the first bounding-box match wins,
allowing smaller regions (e.g. Adriatic) to override larger ones (Mediterranean).
"""

from __future__ import annotations

# 8-point compass order used throughout this module
_CARDINAL_ORDER = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

# Fallback names when a region matches but the direction has no specific name,
# or when the location is outside all known regions.
_CARDINAL_FALLBACK = [
    "North wind",
    "Northeast wind",
    "East wind",
    "Southeast wind",
    "South wind",
    "Southwest wind",
    "West wind",
    "Northwest wind",
]

# fmt: off
# Each entry: (label, lat_min, lat_max, lon_min, lon_max, {cardinal: wind_name})
# Sparse dict — only directions with a traditional name are listed;
# unlisted directions fall back to "<Direction> wind".
_WIND_REGIONS: list[tuple[str, float, float, float, float, dict[str, str]]] = [

    # --- Most specific sub-regions first ---

    # Adriatic Sea: NE Bora overrides Mediterranean Greco
    ("Adriatic", 40.0, 46.5, 12.0, 20.0, {
        "N": "Tramontana", "NE": "Bora",    "E": "Levante",
        "SE": "Jugo",      "S": "Ostro",    "SW": "Libeccio",
        "W": "Ponente",    "NW": "Maestrale",
    }),

    # Southern California (Santa Ana)
    ("Southern California", 32.0, 37.0, -122.0, -114.0, {
        "NE": "Santa Ana", "E": "Santa Ana",
    }),

    # Northern California / Bay Area (Diablo)
    ("Northern California", 37.0, 42.0, -124.0, -119.0, {
        "NE": "Diablo", "E": "Diablo",
    }),

    # Pacific Northwest — US and Canada
    ("Pacific Northwest", 42.0, 55.0, -126.0, -115.0, {
        "E": "Chinook", "SE": "Chinook", "NE": "Williwaw",
    }),

    # Rocky Mountain / Great Plains chinook belt
    ("Rocky Mountain Chinook", 45.0, 55.0, -116.0, -100.0, {
        "W": "Chinook", "SW": "Chinook",
    }),

    # Texas / Southern Great Plains (Blue Norther)
    ("Southern Great Plains", 25.0, 40.0, -105.0, -90.0, {
        "N": "Blue Norther", "NW": "Blue Norther",
    }),

    # Cape of Good Hope region
    ("Cape of Good Hope", -36.0, -25.0, 14.0, 36.0, {
        "SE": "Cape Doctor", "NE": "Berg wind", "N": "Berg wind",
    }),

    # Southern Cone of South America
    ("Southern Cone", -55.0, -25.0, -75.0, -35.0, {
        "S": "Minuano", "SW": "Pampero", "W": "Zonda",
    }),

    # Southwest Australia (Fremantle Doctor)
    ("Southwest Australia", -38.0, -28.0, 113.0, 130.0, {
        "SW": "Fremantle Doctor", "S": "Fremantle Doctor",
    }),

    # New Zealand
    ("New Zealand", -47.0, -34.0, 166.0, 178.0, {
        "NW": "Nor'wester", "S": "Southerly Buster",
    }),

    # Japan
    ("Japan", 30.0, 46.0, 128.0, 146.0, {
        "NW": "Karakkaze", "N": "Karakkaze", "E": "Yamase",
    }),

    # West Africa — Harmattan belt
    ("West Africa", 5.0, 20.0, -18.0, 15.0, {
        "NE": "Harmattan", "N": "Harmattan",
    }),

    # Arabian Peninsula
    ("Arabian Peninsula", 12.0, 35.0, 33.0, 63.0, {
        "N": "Shamal", "NW": "Shamal",
        "SE": "Khamsin", "S": "Khamsin",
        "SW": "Kaus",
    }),

    # --- Broader regions last ---

    # Full Mediterranean basin (all 8 directions named)
    ("Mediterranean", 30.0, 47.0, -6.0, 42.0, {
        "N": "Tramontana", "NE": "Greco",    "E": "Levante",
        "SE": "Scirocco",  "S": "Ostro",     "SW": "Libeccio",
        "W": "Ponente",    "NW": "Maestrale",
    }),
]
# fmt: on


def _degrees_to_cardinal(degrees: float) -> str:
    """Convert a wind bearing in degrees to an 8-point cardinal string."""
    idx = int((degrees + 22.5) / 45) % 8
    return _CARDINAL_ORDER[idx]


def get_named_wind(lat: float, lon: float, cardinal: str) -> str:
    """Return the traditional name for a wind from cardinal direction at lat/lon.

    Checks regions from most specific to most general; returns the first match.
    Falls back to '<Direction> wind' when the location has no named wind for
    this direction.
    """
    for _label, lat_min, lat_max, lon_min, lon_max, names in _WIND_REGIONS:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            if cardinal in names:
                return names[cardinal]
            # Region matched but this direction has no specific name — stop here
            # rather than falling through to a broader region's name.
            break
    if cardinal in _CARDINAL_ORDER:
        return _CARDINAL_FALLBACK[_CARDINAL_ORDER.index(cardinal)]
    return "Unknown wind"


def get_named_wind_from_degrees(lat: float, lon: float, degrees: float) -> str:
    """Return the traditional wind name for a bearing in degrees at lat/lon."""
    return get_named_wind(lat, lon, _degrees_to_cardinal(degrees))
