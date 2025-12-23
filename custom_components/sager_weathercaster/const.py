"""Sager Weathercaster Constants."""

# Domain
DOMAIN = "sager_weathercaster"

# Component Information
NAME = "Sager Weathercaster"
VERSION = "2.0.2"
MANUFACTURER = "Sager Weather"
MODEL = "Weathercaster Algorithm"

# Configuration Keys
CONF_UPDATE_INTERVAL = "update_interval"
CONF_PRESSURE_ENTITY = "pressure_entity"
CONF_WIND_DIR_ENTITY = "wind_dir_entity"
CONF_WIND_SPEED_ENTITY = "wind_speed_entity"
CONF_WIND_HISTORIC_ENTITY = "wind_historic_entity"
CONF_PRESSURE_CHANGE_ENTITY = "pressure_change_entity"
CONF_CLOUD_COVER_ENTITY = "cloud_cover_entity"
CONF_RAINING_ENTITY = "raining_entity"
CONF_TEMPERATURE_ENTITY = "temperature_entity"
CONF_HUMIDITY_ENTITY = "humidity_entity"
CONF_CONDITION_ENTITY = "condition_entity"

# Default Values
DEFAULT_UPDATE_INTERVAL = 600  # seconds (10 minutes)
DEFAULT_NAME = "Sager Weather"

# Cache Settings
CACHE_DURATION_MINUTES = 5

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

# Forecast Texts (Italian)
FORECASTS = [
    "Sereno.",
    "Sereno con temperature in aumento.",
    "Sereno con temperature in calo.",
    "Tempo instabile.",
    "Tempo instabile con temperature in aumento.",
    "Tempo instabile con temperature in calo.",
    "Molto nuvoloso o coperto seguito da pioggia o rovesci.",
    "Molto nuvoloso o coperto seguito da pioggia o rovesci e temperature in aumento.",
    "Rovesci.",
    "Rovesci con temperature in aumento.",
    "Rovesci con temperature in calo.",
    "Pioggia.",
    "Pioggia con temperature in aumento.",
    "Pioggia con temperature in calo; probabile miglioramento entro 24 ore.",
    "Pioggia o rovesci con miglioramento entro 12 ore.",
    "Pioggia o rovesci con miglioramento entro 12 ore; temperature in calo.",
    "Pioggia o rovesci seguiti da rapido miglioramento (entro 6 ore).",
    "Pioggia o rovesci seguiti da rapido miglioramento (entro 6 ore); temperature in calo.",
    "Pioggia o rovesci seguiti da rapido rasserenamento (entro 6 ore); temperature in calo.",
    "Tempo instabile ma in miglioramento.",
    "Tempo instabile ma in rapido miglioramento (entro 6 ore) con temperature in calo.",
    "Tempo eccezionale.",
]

# Wind Velocities (Italian)
WIND_VELOCITIES = [
    "in probabile aumento.",
    "da moderato a teso (20-39 km/h)",
    "da fresco a forte (40-62 km/h) (Il vento forte può anticipare le tempeste in mare aperto)",
    "burrasca (63-87 km/h)",
    "da tempesta a fortunale (80-117 km/h)",
    "uragano (oltre i 117 km/h)",
    "in attenuazione o moderato se il vento attuale è di velocità da fresca a forte.",
    "nessun cambiamento di rilievo. Tendenza a leggero aumento del vento nel corso della giornata, in attenuazione dalla serata.",
]

# Wind Directions (Italian)
WIND_DIRS = [
    "Vento da Nord o Nord-est, ",
    "Vento da Nord-est o Est, ",
    "Vento da Est o Sud-est, ",
    "Vento da Sud-est o Sud, ",
    "Vento da Sud o Sud-ovest, ",
    "Vento da Sud-ovest o Ovest, ",
    "Vento da Ovest o Nord-ovest, ",
    "Vento da Nord-ovest o Nord, ",
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
    (float("inf"), 1029.46, 1),  # Very High
    (1029.46, 1019.30, 2),  # High
    (1019.30, 1012.53, 3),  # Above Normal
    (1012.53, 1005.76, 4),  # Normal
    (1005.76, 999.00, 5),  # Below Normal
    (999.00, 988.80, 6),  # Low
    (988.80, 975.28, 7),  # Very Low
    (975.28, float("-inf"), 8),  # Extremely Low
]

# Services
SERVICE_RECALCULATE = "recalculate_forecast"
SERVICE_GET_DETAILED_ANALYSIS = "get_detailed_analysis"
