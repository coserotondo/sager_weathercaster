"""Sager Weathercaster Constants."""

from math import inf

# Domain
DOMAIN = "sager_weathercaster"

# Component Information
NAME = "Sager Weathercaster"
VERSION = "3.0.0"
MANUFACTURER = "Sager Weather"
MODEL = "Weathercaster Algorithm"

# Configuration Keys
CONF_PRESSURE_ENTITY = "pressure_entity"
CONF_WIND_DIR_ENTITY = "wind_dir_entity"
CONF_WIND_SPEED_ENTITY = "wind_speed_entity"
CONF_WIND_HISTORIC_ENTITY = "wind_historic_entity"
CONF_PRESSURE_CHANGE_ENTITY = "pressure_change_entity"
CONF_CLOUD_COVER_ENTITY = "cloud_cover_entity"
CONF_RAINING_ENTITY = "raining_entity"
CONF_TEMPERATURE_ENTITY = "temperature_entity"
CONF_HUMIDITY_ENTITY = "humidity_entity"

# Default Values
DEFAULT_NAME = "Sager Weather"
UPDATE_INTERVAL_MINUTES = 10  # Integration-determined update interval

# Cache Settings
CACHE_DURATION_MINUTES = 5

# Rain Rate Thresholds (mm/h)
RAIN_THRESHOLD_LIGHT = 0.1  # Minimum rain rate to be considered "rainy"
RAIN_THRESHOLD_HEAVY = 7.5  # Rain rate threshold for "pouring"

# Temperature threshold for showers vs flurries (Celsius)
TEMP_THRESHOLD_FLURRIES = 2.0

# Algorithm observation window (hours)
ALGORITHM_WINDOW_HOURS = 6

# Latitude Zone Thresholds
LATITUDE_NORTHERN_POLAR = 66.6
LATITUDE_NORTHERN_TROPIC = 23.5
LATITUDE_SOUTHERN_TROPIC = -23.5
LATITUDE_SOUTHERN_POLAR = -66.6

# Zone-aware wind direction index arrays
# Each maps cardinal directions to algorithm indices based on latitude zone
# Northern Temperate (23.5N - 66.6N): Standard Sager mapping
ZONE_DIRECTIONS_NT = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
# Northern Polar (>66.6N) and Northern Tropical (0 - 23.5N)
ZONE_DIRECTIONS_NP = ["S", "SW", "W", "NW", "N", "NE", "E", "SE"]
# Southern Temperate (23.5S - 66.6S)
ZONE_DIRECTIONS_ST = ["S", "SE", "E", "NE", "N", "NW", "W", "SW"]
# Southern Polar (<66.6S) and Southern Tropical (0 - 23.5S)
ZONE_DIRECTIONS_SP = ["N", "NW", "W", "SW", "S", "SE", "E", "NE"]

# Attribute Keys
ATTR_SAGER_FORECAST = "sager_forecast"
ATTR_PRESSURE_LEVEL = "pressure_level"
ATTR_WIND_DIR = "wind_dir"
ATTR_WIND_TREND = "wind_trend"
ATTR_PRESSURE_TREND = "pressure_trend"
ATTR_CLOUD_LEVEL = "cloud_level"
ATTR_CONFIDENCE = "confidence"
ATTR_RAW_DATA = "raw_data"
ATTR_CALCULATION_TIME = "calculation_time_ms"
ATTR_CACHE_HIT_RATE = "cache_hit_rate"
ATTR_LAST_UPDATE = "last_update"
ATTR_ATTRIBUTION = "attribution"

# Attribution
ATTRIBUTION = "Sager Weathercaster Algorithm"

# Wind Trends
WIND_TREND_STEADY = "STEADY"
WIND_TREND_VEERING = "VEERING"
WIND_TREND_BACKING = "BACKING"

# Pressure Trends
PRESSURE_TREND_RISING_RAPIDLY = "Rising Rapidly"
PRESSURE_TREND_RISING_SLOWLY = "Rising Slowly"
PRESSURE_TREND_NORMAL = "Normal"
PRESSURE_TREND_DECREASING_SLOWLY = "Decreasing Slowly"
PRESSURE_TREND_DECREASING_RAPIDLY = "Decreasing Rapidly"

# Cloud Levels
CLOUD_LEVEL_CLEAR = "Clear"
CLOUD_LEVEL_PARTLY_CLOUDY = "Partly Cloudy"
CLOUD_LEVEL_MOSTLY_CLOUDY = "Mostly Cloudy"
CLOUD_LEVEL_OVERCAST = "Overcast"
CLOUD_LEVEL_RAINING = "Raining"

# Validation Ranges
PRESSURE_MIN = 900
PRESSURE_MAX = 1100
WIND_DIR_MIN = 0
WIND_DIR_MAX = 360
WIND_SPEED_MIN = 0
WIND_SPEED_MAX = 300
PRESSURE_CHANGE_MIN = -50
PRESSURE_CHANGE_MAX = 50
CLOUD_COVER_MIN = 0
CLOUD_COVER_MAX = 100

# Forecast letter codes (matching OpenHAB Sager classification)
# Each index maps to a semantic letter code used as translation key
FORECAST_CODES = [
    "a",  # 0: Fair
    "b",  # 1: Fair and warmer
    "c",  # 2: Fair and cooler
    "d",  # 3: Unsettled
    "e",  # 4: Unsettled and warmer
    "f",  # 5: Unsettled and cooler
    "g",  # 6: Increasing cloudiness → precipitation/showers
    "h",  # 7: Increasing cloudiness → precipitation/showers + warmer
    "j",  # 8: Showers
    "k",  # 9: Showers + warmer
    "l",  # 10: Showers + cooler
    "m",  # 11: Precipitation
    "n",  # 12: Precipitation + warmer
    "p",  # 13: Precipitation + turning cooler, improvement 24h
    "r",  # 14: Precipitation/showers → improvement 12h
    "s",  # 15: Precipitation/showers → improvement 12h + cooler
    "t",  # 16: Precipitation/showers → improvement 6h
    "u",  # 17: Precipitation/showers → improvement 6h + cooler
    "w",  # 18: Precipitation/showers → fair 6h + cooler
    "x",  # 19: Unsettled → fair
    "y",  # 20: Unsettled → fair 6h + cooler
]

# Shower-type codes that get "1" (showers) or "2" (flurries) suffix based on temperature
SHOWER_FORECAST_CODES = {"g", "j", "k", "l", "r", "s", "t", "u", "w"}

# Direct forecast code → HA weather condition mapping
FORECAST_CONDITIONS: dict[str, str] = {
    "a": "sunny",
    "b": "sunny",
    "c": "sunny",
    "d": "partlycloudy",
    "e": "partlycloudy",
    "f": "partlycloudy",
    "g": "cloudy",
    "g1": "cloudy",
    "g2": "snowy",
    "h": "cloudy",
    "j": "rainy",
    "j1": "rainy",
    "j2": "snowy",
    "k": "rainy",
    "k1": "rainy",
    "k2": "snowy",
    "l": "rainy",
    "l1": "rainy",
    "l2": "snowy",
    "m": "rainy",
    "n": "rainy",
    "p": "rainy",
    "r": "rainy",
    "r1": "rainy",
    "r2": "snowy",
    "s": "rainy",
    "s1": "rainy",
    "s2": "snowy",
    "t": "rainy",
    "t1": "rainy",
    "t2": "snowy",
    "u": "rainy",
    "u1": "rainy",
    "u2": "snowy",
    "w": "rainy",
    "w1": "rainy",
    "w2": "snowy",
    "x": "partlycloudy",
    "y": "partlycloudy",
}

# Forecast codes indicating warmer temperatures
FORECAST_CODES_WARMER = {"b", "e", "h", "k", "k1", "k2", "n"}
# Forecast codes indicating cooler temperatures
FORECAST_CODES_COOLER = {
    "c", "f", "l", "l1", "l2", "p", "s", "s1", "s2",
    "u", "u1", "u2", "w", "w1", "w2", "y",
}

# Forecast evolution: what happens in the NEXT period (12-24h)
# Based on the temporal meaning encoded in each forecast code.
# Format: code -> (next_period_condition, precipitation_probability)
# Codes not listed here maintain the same condition in period 2.
FORECAST_EVOLUTION: dict[str, tuple[str, float]] = {
    # g/h: "increasing cloudiness FOLLOWED BY precipitation" → period 2 is the rain
    "g": ("rainy", 70.0),
    "g1": ("rainy", 70.0),
    "g2": ("snowy", 70.0),
    "h": ("rainy", 70.0),
    # p: "precipitation and turning cooler, improvement likely in 24h"
    "p": ("partlycloudy", 20.0),
    # r/s: "precipitation followed by improvement within 12h"
    "r": ("partlycloudy", 15.0),
    "r1": ("partlycloudy", 15.0),
    "r2": ("partlycloudy", 15.0),
    "s": ("partlycloudy", 15.0),
    "s1": ("partlycloudy", 15.0),
    "s2": ("partlycloudy", 15.0),
    # t/u: "precipitation followed by improvement within 6h" → clears fast
    "t": ("sunny", 5.0),
    "t1": ("sunny", 5.0),
    "t2": ("sunny", 5.0),
    "u": ("sunny", 5.0),
    "u1": ("sunny", 5.0),
    "u2": ("sunny", 5.0),
    # w: "precipitation followed by FAIR within 6h" → clears to fair
    "w": ("sunny", 5.0),
    "w1": ("sunny", 5.0),
    "w2": ("sunny", 5.0),
    # x: "unsettled followed by fair"
    "x": ("sunny", 5.0),
    # y: "unsettled followed by fair within 6h"
    "y": ("sunny", 5.0),
}

# Precipitation probability for period 1 by condition
PRECIPITATION_PROBABILITY: dict[str, float] = {
    "sunny": 0.0,
    "clear-night": 0.0,
    "partlycloudy": 15.0,
    "cloudy": 25.0,
    "rainy": 80.0,
    "snowy": 80.0,
    "pouring": 95.0,
}

# Zambretti algorithm constants
# Formulas: falling=127-0.12*P, steady=144-0.13*P, rising=185-0.16*P
ZAMBRETTI_FALLING_CONSTANT = 127
ZAMBRETTI_FALLING_FACTOR = 0.12
ZAMBRETTI_STEADY_CONSTANT = 144
ZAMBRETTI_STEADY_FACTOR = 0.13
ZAMBRETTI_RISING_CONSTANT = 185
ZAMBRETTI_RISING_FACTOR = 0.16
# Pressure change threshold for trend detection (hPa over 3h)
ZAMBRETTI_TREND_THRESHOLD = 1.6

# Zambretti forecast lookup table
# Maps (trend, index) to (description_key, ha_condition)
ZAMBRETTI_FORECASTS: dict[str, dict[int, tuple[str, str]]] = {
    "falling": {
        1: ("settled_fine", "sunny"),
        2: ("fine_weather", "sunny"),
        3: ("fine_less_settled", "partlycloudy"),
        4: ("fairly_fine_showery_later", "partlycloudy"),
        5: ("showery_more_unsettled", "rainy"),
        6: ("unsettled_rain_later", "rainy"),
        7: ("rain_at_times_worse_later", "rainy"),
        8: ("rain_very_unsettled", "rainy"),
        9: ("very_unsettled_rain", "pouring"),
    },
    "steady": {
        10: ("settled_fine", "sunny"),
        11: ("fine_weather", "sunny"),
        12: ("fine_possibly_showers", "partlycloudy"),
        13: ("fairly_fine_showers_likely", "partlycloudy"),
        14: ("showery_bright_intervals", "rainy"),
        15: ("changeable_some_rain", "rainy"),
        16: ("unsettled_rain_at_times", "rainy"),
        17: ("rain_frequent_intervals", "rainy"),
        18: ("very_unsettled_rain", "pouring"),
        19: ("stormy_much_rain", "pouring"),
    },
    "rising": {
        20: ("settled_fine", "sunny"),
        21: ("fine_weather", "sunny"),
        22: ("becoming_fine", "sunny"),
        23: ("fairly_fine_improving", "partlycloudy"),
        24: ("fairly_fine_showers_early", "partlycloudy"),
        25: ("showery_early_improving", "rainy"),
        26: ("changeable_mending", "partlycloudy"),
        27: ("rather_unsettled_clearing", "partlycloudy"),
        28: ("unsettled_probably_improving", "rainy"),
        29: ("unsettled_short_fine", "rainy"),
        30: ("very_unsettled_finer_at_times", "rainy"),
        31: ("stormy_possibly_improving", "pouring"),
        32: ("stormy_much_rain", "pouring"),
    },
}

# Wind velocity translation keys (index 0-7)
WIND_VELOCITY_KEYS = [
    "probably_increasing",
    "moderate_to_fresh",
    "fresh_to_strong",
    "gale",
    "storm_to_hurricane",
    "hurricane",
    "decreasing_or_moderate",
    "no_significant_change",
]

# Wind direction translation keys (index 0-7)
WIND_DIRECTION_KEYS = [
    "n_or_ne",
    "ne_or_e",
    "e_or_se",
    "se_or_s",
    "s_or_sw",
    "sw_or_w",
    "w_or_nw",
    "nw_or_n",
]

# Wind Direction Cardinals
WIND_CARDINAL_N = "N"
WIND_CARDINAL_NE = "NE"
WIND_CARDINAL_E = "E"
WIND_CARDINAL_SE = "SE"
WIND_CARDINAL_S = "S"
WIND_CARDINAL_SW = "SW"
WIND_CARDINAL_W = "W"
WIND_CARDINAL_NW = "NW"
WIND_CARDINAL_CALM = "calm"

# HPA Levels - (max, min, level)
HPA_LEVELS = [
    (inf, 1029.46, 1),  # Very High
    (1029.46, 1019.30, 2),  # High
    (1019.30, 1012.53, 3),  # Above Normal
    (1012.53, 1005.76, 4),  # Normal
    (1005.76, 999.00, 5),  # Below Normal
    (999.00, 988.80, 6),  # Low
    (988.80, 975.28, 7),  # Very Low
    (975.28, -inf, 8),  # Extremely Low
]


# Open-Meteo API
OPEN_METEO_API_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_UPDATE_INTERVAL_MINUTES = 30
OPEN_METEO_RETRY_ATTEMPTS = 3
OPEN_METEO_RETRY_BACKOFF = 60  # seconds between retries
OPEN_METEO_FORECAST_DAYS = 7
OPEN_METEO_TIMEOUT = 10  # seconds

# Open-Meteo hourly variables to request
OPEN_METEO_HOURLY_PARAMS = [
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "apparent_temperature",
    "precipitation_probability",
    "precipitation",
    "weather_code",
    "cloud_cover",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "uv_index",
    "is_day",
]

# Open-Meteo daily variables to request
OPEN_METEO_DAILY_PARAMS = [
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "precipitation_probability_max",
    "wind_speed_10m_max",
    "wind_direction_10m_dominant",
    "cloud_cover_mean",
    "uv_index_max",
]

# Lux-to-cloud-cover conversion constants
# Based on Kasten & Czeplak clear-sky illuminance model
LUX_CLEAR_SKY_COEFFICIENT = 172278
LUX_ATMOSPHERIC_A = 0.271
LUX_ATMOSPHERIC_B = 0.706
LUX_ATMOSPHERIC_C = 0.6

# WMO weather code → HA condition mapping (for Open-Meteo data)
WMO_TO_HA_CONDITION: dict[int, str] = {
    0: "sunny",
    1: "sunny",
    2: "partlycloudy",
    3: "cloudy",
    45: "fog",
    48: "fog",
    51: "rainy",
    53: "rainy",
    55: "rainy",
    56: "rainy",
    57: "rainy",
    61: "rainy",
    63: "rainy",
    65: "pouring",
    66: "rainy",
    67: "pouring",
    71: "snowy",
    73: "snowy",
    75: "snowy",
    77: "snowy",
    80: "rainy",
    81: "rainy",
    82: "pouring",
    85: "snowy",
    86: "snowy",
    95: "lightning",
    96: "lightning-rainy",
    99: "lightning-rainy",
}

# Services
SERVICE_RECALCULATE = "recalculate_forecast"
SERVICE_GET_DETAILED_ANALYSIS = "get_detailed_analysis"
