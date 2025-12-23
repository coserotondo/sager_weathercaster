"""Sager Weathercaster Sensor Platform."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import (
    PLATFORM_SCHEMA as SENSOR_PLATFORM_SCHEMA,
    SensorEntity,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    ATTR_CACHE_HIT_RATE,
    ATTR_CALCULATION_TIME,
    ATTR_CLOUD_LEVEL,
    ATTR_CONFIDENCE,
    ATTR_LAST_UPDATE,
    ATTR_PRESSURE_LEVEL,
    ATTR_PRESSURE_TREND,
    ATTR_RAW_DATA,
    ATTR_WIND_DIR,
    ATTR_WIND_TREND,
    CACHE_DURATION_MINUTES,
    CLOUD_COVER_MAX,
    CLOUD_COVER_MIN,
    CLOUD_LEVEL_CLEAR,
    CLOUD_LEVEL_MOSTLY_CLOUDY,
    CLOUD_LEVEL_OVERCAST,
    CLOUD_LEVEL_PARTLY_CLOUDY,
    CLOUD_LEVEL_RAINING,
    CONF_CLOUD_COVER_ENTITY,
    CONF_PRESSURE_CHANGE_ENTITY,
    CONF_PRESSURE_ENTITY,
    CONF_RAINING_ENTITY,
    CONF_UPDATE_INTERVAL,
    CONF_WIND_DIR_ENTITY,
    CONF_WIND_HISTORIC_ENTITY,
    CONF_WIND_SPEED_ENTITY,
    DEFAULT_NAME,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    FORECASTS,
    HPA_LEVELS,
    MANUFACTURER,
    MODEL,
    NAME,
    PRESSURE_CHANGE_MAX,
    PRESSURE_CHANGE_MIN,
    PRESSURE_MAX,
    PRESSURE_MIN,
    PRESSURE_TREND_DECREASING_RAPIDLY,
    PRESSURE_TREND_DECREASING_SLOWLY,
    PRESSURE_TREND_NORMAL,
    PRESSURE_TREND_RISING_RAPIDLY,
    PRESSURE_TREND_RISING_SLOWLY,
    VERSION,
    WIND_CARDINAL_CALM,
    WIND_CARDINAL_E,
    WIND_CARDINAL_N,
    WIND_CARDINAL_NE,
    WIND_CARDINAL_NW,
    WIND_CARDINAL_S,
    WIND_CARDINAL_SE,
    WIND_CARDINAL_SW,
    WIND_CARDINAL_W,
    WIND_DIR_MAX,
    WIND_DIR_MIN,
    WIND_DIRS,
    WIND_SPEED_MAX,
    WIND_SPEED_MIN,
    WIND_TREND_BACKING,
    WIND_TREND_STEADY,
    WIND_TREND_VEERING,
    WIND_VELOCITIES,
)

_LOGGER = logging.getLogger(__name__)

# Cache globals
_FORECAST_CACHE: dict[str, dict[str, Any]] = {}
_LAST_CALCULATION: datetime | None = None
CACHE_DURATION = timedelta(minutes=CACHE_DURATION_MINUTES)

PLATFORM_SCHEMA = SENSOR_PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Optional(CONF_PRESSURE_ENTITY): cv.entity_id,
        vol.Optional(CONF_WIND_DIR_ENTITY): cv.entity_id,
        vol.Optional(CONF_WIND_SPEED_ENTITY): cv.entity_id,
        vol.Optional(CONF_WIND_HISTORIC_ENTITY): cv.entity_id,
        vol.Optional(CONF_PRESSURE_CHANGE_ENTITY): cv.entity_id,
        vol.Optional(CONF_CLOUD_COVER_ENTITY): cv.entity_id,
        vol.Optional(CONF_RAINING_ENTITY): cv.entity_id,
        vol.Optional(
            CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL
        ): cv.positive_int,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Sager Weathercaster sensors."""
    # Handle discovery vs direct config
    if discovery_info is not None:
        conf = discovery_info
    else:
        conf = config

    name = conf.get(CONF_NAME, DEFAULT_NAME)
    update_interval = conf.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)

    _LOGGER.debug(
        f"Setting up Sager sensor '{name}' with update interval {update_interval}s"
    )

    async_add_entities([SagerSensor(hass, name, conf, update_interval)], True)


class SagerSensor(SensorEntity):
    """Sager Weathercaster Forecast Sensor."""

    _attr_icon = "mdi:weather-partly-cloudy"
    _attr_should_poll = True

    def __init__(
        self,
        hass: HomeAssistant,
        name: str | None,
        config: ConfigType,
        update_interval: int = DEFAULT_UPDATE_INTERVAL,
    ) -> None:
        """Initialize the sensor."""
        self._hass = hass

        # Handle None name
        if name is None:
            name = DEFAULT_NAME

        self._attr_name = f"{name} Sager Forecast"
        self._attr_unique_id = f"sager_forecast_{name.lower().replace(' ', '_')}"
        self._attr_native_unit_of_measurement = None
        self._config = config
        self._state: str | None = "Initializing..."
        self._attrs: dict[str, Any] = {}
        self._update_interval = update_interval
        self._last_update: datetime | None = None

        # Performance tracking
        self._calculation_time = 0
        self._cache_hits = 0
        self._cache_misses = 0

        _LOGGER.debug(f"Initialized Sager sensor: {self._attr_name}")

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        return self._attrs

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, "sager_weathercaster")},
            name=NAME,
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=VERSION,
        )

    async def async_update(self) -> None:
        """Update sensor state (async wrapper)."""
        await self._hass.async_add_executor_job(self.update)

    def update(self) -> None:
        """Update sensor state."""
        global _LAST_CALCULATION, _FORECAST_CACHE

        try:
            # Rate limiting
            now = datetime.now()
            if (
                self._last_update
                and (now - self._last_update).total_seconds() < self._update_interval
            ):
                _LOGGER.debug(
                    f"Update skipped, last update was "
                    f"{(now - self._last_update).total_seconds():.1f}s ago"
                )
                return

            start_time = datetime.now()

            # Get sensor data
            try:
                data = self._get_sensor_data()
            except Exception as e:
                _LOGGER.error(f"Failed to get sensor data: {e}", exc_info=True)
                self._state = "Error: Sensor data unavailable"
                self._attrs["error"] = str(e)
                return

            # Generate cache key
            cache_key = (
                f"{data['pressure']:.1f}_{data['wind_direction']:.0f}_"
                f"{data['wind_speed']:.1f}_{data['pressure_change']:.2f}_"
                f"{data['cloud_cover']:.0f}_{data['raining']}"
            )

            # Check cache
            if (
                cache_key in _FORECAST_CACHE
                and _LAST_CALCULATION
                and (now - _LAST_CALCULATION) < CACHE_DURATION
            ):
                forecast = _FORECAST_CACHE[cache_key]
                self._cache_hits += 1
                _LOGGER.debug(
                    f"Cache HIT for {cache_key} "
                    f"(hit rate: {self._cache_hits}/{self._cache_hits + self._cache_misses})"
                )
            else:
                try:
                    forecast = self._sager_algorithm(data)
                    _FORECAST_CACHE[cache_key] = forecast
                    _LAST_CALCULATION = now
                    self._cache_misses += 1
                    _LOGGER.debug(
                        f"Cache MISS for {cache_key} "
                        f"(hit rate: {self._cache_hits}/{self._cache_hits + self._cache_misses})"
                    )
                except Exception as e:
                    _LOGGER.error(
                        f"Sager algorithm calculation failed: {e}", exc_info=True
                    )
                    self._state = "Error: Calculation failed"
                    self._attrs["error"] = str(e)
                    return

            # Update state
            self._state = forecast["text"]

            # Calculate cache hit rate
            total_requests = self._cache_hits + self._cache_misses
            cache_hit_rate = (
                f"{(self._cache_hits / total_requests * 100):.1f}%"
                if total_requests > 0
                else "0%"
            )

            self._attrs = {
                ATTR_PRESSURE_LEVEL: forecast["hpa_level"],
                ATTR_WIND_DIR: forecast["wind_dir"],
                ATTR_WIND_TREND: forecast["wind_trend"],
                ATTR_CLOUD_LEVEL: forecast["cloud_level"],
                ATTR_PRESSURE_TREND: forecast["pressure_trend"],
                ATTR_CONFIDENCE: forecast["confidence"],
                ATTR_RAW_DATA: {k: v for k, v in data.items() if k != "raining"},
                ATTR_CALCULATION_TIME: self._calculation_time,
                ATTR_CACHE_HIT_RATE: cache_hit_rate,
                ATTR_LAST_UPDATE: now.strftime("%Y-%m-%d %H:%M:%S"),
            }

            self._last_update = now
            self._calculation_time = int(
                (datetime.now() - start_time).total_seconds() * 1000
            )

            _LOGGER.debug(
                f"Update completed in {self._calculation_time}ms, "
                f"confidence: {forecast['confidence']}%"
            )

        except Exception as e:
            _LOGGER.error(f"Unexpected error in update: {e}", exc_info=True)
            self._state = "Error: Unexpected error"
            self._attrs["error"] = str(e)

    def _get_sensor_data(self) -> dict[str, Any]:
        """Get input data from configured entities."""
        data: dict[str, Any] = {}

        entities_map = {
            CONF_PRESSURE_ENTITY: ("pressure", 1013.25, PRESSURE_MIN, PRESSURE_MAX),
            CONF_WIND_DIR_ENTITY: ("wind_direction", 0, WIND_DIR_MIN, WIND_DIR_MAX),
            CONF_WIND_SPEED_ENTITY: ("wind_speed", 0, WIND_SPEED_MIN, WIND_SPEED_MAX),
            CONF_WIND_HISTORIC_ENTITY: ("wind_historic", 0, WIND_DIR_MIN, WIND_DIR_MAX),
            CONF_PRESSURE_CHANGE_ENTITY: (
                "pressure_change",
                0,
                PRESSURE_CHANGE_MIN,
                PRESSURE_CHANGE_MAX,
            ),
            CONF_CLOUD_COVER_ENTITY: (
                "cloud_cover",
                0,
                CLOUD_COVER_MIN,
                CLOUD_COVER_MAX,
            ),
        }

        for config_key, (data_key, default, min_val, max_val) in entities_map.items():
            entity_id = self._config.get(config_key)
            if entity_id:
                state = self._hass.states.get(entity_id)
                if state and state.state not in ["unavailable", "unknown", "none"]:
                    try:
                        value = float(state.state)
                        # Validate range
                        if min_val <= value <= max_val:
                            data[data_key] = value
                        else:
                            _LOGGER.warning(
                                f"Value out of range for {entity_id}: {value} "
                                f"(expected {min_val}-{max_val}), using default {default}"
                            )
                            data[data_key] = default
                    except (ValueError, TypeError):
                        _LOGGER.warning(
                            f"Invalid value for {entity_id}: {state.state}, "
                            f"using default {default}"
                        )
                        data[data_key] = default
                else:
                    data[data_key] = default
            else:
                data[data_key] = default

        # Boolean sensor for rain
        raining_entity = self._config.get(CONF_RAINING_ENTITY)
        if raining_entity:
            rain_state = self._hass.states.get(raining_entity)
            data["raining"] = rain_state and rain_state.state in ["on", "true", "1"]
        else:
            data["raining"] = False

        return data

    def _sager_algorithm(self, data: dict[str, Any]) -> dict[str, Any]:
        """Complete Sager weather algorithm."""
        # Calculate input variables
        z_hpa = self._get_hpa_level(data["pressure"])
        z_wind = self._get_wind_dir(data["wind_direction"], data["wind_speed"])
        z_rumbo = self._get_wind_trend(data["wind_direction"], data["wind_historic"])
        z_trend = self._get_pressure_trend(data["pressure_change"])
        z_nubes = self._get_cloud_level(data["cloud_cover"], data["raining"])

        # Wind direction index mapping
        wind_index_map = {
            WIND_CARDINAL_N: 0,
            WIND_CARDINAL_NE: 1,
            WIND_CARDINAL_E: 2,
            WIND_CARDINAL_SE: 3,
            WIND_CARDINAL_S: 4,
            WIND_CARDINAL_SW: 5,
            WIND_CARDINAL_W: 6,
            WIND_CARDINAL_NW: 7,
            WIND_CARDINAL_CALM: 7,
        }
        wind_index = wind_index_map.get(z_wind, 7)

        # Lookup forecast
        forecast_map = self._get_complete_forecast_map()
        lookup_key = f"{z_rumbo}{z_hpa}{z_trend}{z_nubes}"

        if lookup_key in forecast_map:
            f_code, w_code = forecast_map[lookup_key]
            confidence = 95
        else:
            _LOGGER.warning(
                f"Combination not found: {lookup_key} "
                f"(trend:{z_rumbo}, hpa:{z_hpa}, pressure:{z_trend}, cloud:{z_nubes}), "
                f"using default"
            )
            f_code, w_code = "F3", "W7"  # Default: Unstable weather, no change
            confidence = 60

        # Parse codes safely
        try:
            forecast_idx = int(f_code[1:])
            wind_idx = int(w_code[1:]) if w_code != "FF" else 7
        except (ValueError, IndexError) as e:
            _LOGGER.error(f"Error parsing forecast codes {f_code}/{w_code}: {e}")
            forecast_idx = 3
            wind_idx = 7

        # Build forecast text
        forecast_text = (
            f"{FORECASTS[forecast_idx]} "
            f"{WIND_DIRS[wind_index]}"
            f"{WIND_VELOCITIES[wind_idx]}"
        ).strip()

        trend_names = [WIND_TREND_STEADY, WIND_TREND_VEERING, WIND_TREND_BACKING]
        pressure_names = [
            PRESSURE_TREND_RISING_RAPIDLY,
            PRESSURE_TREND_RISING_SLOWLY,
            PRESSURE_TREND_NORMAL,
            PRESSURE_TREND_DECREASING_SLOWLY,
            PRESSURE_TREND_DECREASING_RAPIDLY,
        ]
        cloud_names = [
            CLOUD_LEVEL_CLEAR,
            CLOUD_LEVEL_PARTLY_CLOUDY,
            CLOUD_LEVEL_MOSTLY_CLOUDY,
            CLOUD_LEVEL_OVERCAST,
            CLOUD_LEVEL_RAINING,
        ]

        return {
            "text": forecast_text,
            "hpa_level": z_hpa,
            "wind_dir": z_wind,
            "wind_trend": trend_names[z_rumbo - 1],
            "pressure_trend": pressure_names[z_trend - 1],
            "cloud_level": cloud_names[z_nubes - 1],
            "confidence": confidence,
        }

    def _get_hpa_level(self, hpa: float) -> int:
        """Get pressure level 1-8."""
        for max_hpa, min_hpa, level in HPA_LEVELS:
            if min_hpa <= hpa < max_hpa:
                return level
        return 8  # Lowest pressure

    def _get_wind_dir(self, direction: float, speed: float) -> str:
        """Get 8-point cardinal wind direction."""
        if speed <= 1:
            return WIND_CARDINAL_CALM
        dirs = [
            WIND_CARDINAL_N,
            WIND_CARDINAL_NE,
            WIND_CARDINAL_E,
            WIND_CARDINAL_SE,
            WIND_CARDINAL_S,
            WIND_CARDINAL_SW,
            WIND_CARDINAL_W,
            WIND_CARDINAL_NW,
        ]
        idx = int((direction + 22.5) / 45) % 8
        return dirs[idx]

    def _get_wind_trend(self, current: float, historic: float) -> int:
        """Get wind trend: 1=STEADY, 2=VEERING, 3=BACKING."""
        if historic == 0 or current == 0:
            return 1  # No historic data

        # Calculate smallest angular difference
        diff = (current - historic + 180) % 360 - 180

        if abs(diff) <= 45:
            return 1  # STEADY
        elif diff > 0:
            return 2  # VEERING (clockwise)
        else:
            return 3  # BACKING (counterclockwise)

    def _get_pressure_trend(self, change: float) -> int:
        """Get pressure trend: 1=Rising Rapidly ... 5=Decreasing Rapidly."""
        if change > 1.4:
            return 1
        elif change > 0.68:
            return 2
        elif change > -0.68:
            return 3
        elif change > -1.4:
            return 4
        return 5

    def _get_cloud_level(self, cover: float, raining: bool) -> int:
        """Get cloud level: 1=Clear ... 5=Raining."""
        if raining:
            return 5
        if cover > 80:
            return 4
        elif cover > 50:
            return 3
        elif cover > 20:
            return 2
        return 1

    def _get_complete_forecast_map(self):
        """Complete lookup table from Sager algorithm - 500+ combinations."""
        return {
            # BACKING (trend=3) - Pressure Level 1
            "1311": ("F0", "W7"),
            "1312": ("F0", "W7"),
            "1313": ("F0", "W7"),
            "1314": ("F0", "W7"),
            "1315": ("F18", "W7"),
            # BACKING (trend=3) - Pressure Level 2
            "1321": ("F0", "W7"),
            "1322": ("F0", "W7"),
            "1323": ("F0", "W7"),
            "1324": ("F19", "W7"),
            "1325": ("F14", "W7"),
            # BACKING (trend=3) - Pressure Level 3
            "1331": ("F0", "W7"),
            "1332": ("F0", "W7"),
            "1333": ("F0", "W7"),
            "1334": ("F19", "W7"),
            "1335": ("F14", "W7"),
            # BACKING (trend=3) - Pressure Level 4
            "1341": ("F0", "W7"),
            "1342": ("F19", "W7"),
            "1343": ("F19", "W7"),
            "1344": ("F3", "W7"),
            "1345": ("F14", "W7"),
            # BACKING (trend=3) - Pressure Level 5
            "1351": ("F8", "W0"),
            "1352": ("F8", "W0"),
            "1353": ("F8", "W0"),
            "1354": ("F11", "W0"),
            "1355": ("F11", "W0"),
            # BACKING (trend=3) - Pressure Level 6
            "1361": ("F11", "W2"),
            "1362": ("F11", "W2"),
            "1363": ("F11", "W2"),
            "1364": ("F11", "W2"),
            "1365": ("F11", "W2"),
            # BACKING (trend=3) - Pressure Level 7
            "1371": ("F11", "W3"),
            "1372": ("F11", "W3"),
            "1373": ("F11", "W3"),
            "1374": ("F11", "W3"),
            "1375": ("F11", "W3"),
            # BACKING (trend=3) - Pressure Level 8
            "1381": ("F11", "W4"),
            "1382": ("F11", "W4"),
            "1383": ("F11", "W4"),
            "1384": ("F11", "W4"),
            "1385": ("F11", "W4"),
            # STEADY (trend=1) - Pressure Level 1
            "2311": ("F0", "W7"),
            "2312": ("F0", "W7"),
            "2313": ("F0", "W7"),
            "2314": ("F19", "W7"),
            "2315": ("F14", "W7"),
            # STEADY (trend=1) - Pressure Level 2
            "2321": ("F0", "W7"),
            "2322": ("F0", "W7"),
            "2323": ("F0", "W7"),
            "2324": ("F19", "W7"),
            "2325": ("F14", "W7"),
            # STEADY (trend=1) - Pressure Level 3
            "2331": ("F0", "W7"),
            "2332": ("F0", "W7"),
            "2333": ("F0", "W7"),
            "2334": ("F19", "W7"),
            "2335": ("F14", "W7"),
            # STEADY (trend=1) - Pressure Level 4
            "2341": ("F0", "W7"),
            "2342": ("F19", "W7"),
            "2343": ("F19", "W7"),
            "2344": ("F3", "W7"),
            "2345": ("F14", "W7"),
            # STEADY (trend=1) - Pressure Level 5
            "2351": ("F8", "W0"),
            "2352": ("F11", "W0"),
            "2353": ("F11", "W0"),
            "2354": ("F11", "W0"),
            "2355": ("F11", "W0"),
            # STEADY (trend=1) - Pressure Level 6
            "2361": ("F11", "W2"),
            "2362": ("F11", "W2"),
            "2363": ("F11", "W2"),
            "2364": ("F11", "W2"),
            "2365": ("F11", "W2"),
            # STEADY (trend=1) - Pressure Level 7
            "2371": ("F11", "W3"),
            "2372": ("F11", "W3"),
            "2373": ("F11", "W3"),
            "2374": ("F11", "W3"),
            "2375": ("F11", "W3"),
            # STEADY (trend=1) - Pressure Level 8
            "2381": ("F11", "W4"),
            "2382": ("F11", "W4"),
            "2383": ("F11", "W4"),
            "2384": ("F11", "W4"),
            "2385": ("F11", "W4"),
            # VEERING (trend=2) - Pressure Level 1
            "3311": ("F0", "W7"),
            "3312": ("F0", "W7"),
            "3313": ("F0", "W7"),
            "3314": ("F19", "W7"),
            "3315": ("F14", "W7"),
            # VEERING (trend=2) - Pressure Level 2
            "3321": ("F0", "W7"),
            "3322": ("F0", "W7"),
            "3323": ("F0", "W7"),
            "3324": ("F19", "W7"),
            "3325": ("F14", "W7"),
            # VEERING (trend=2) - Pressure Level 3
            "3331": ("F0", "W7"),
            "3332": ("F0", "W7"),
            "3333": ("F0", "W7"),
            "3334": ("F19", "W7"),
            "3335": ("F14", "W7"),
            # VEERING (trend=2) - Pressure Level 4
            "3341": ("F0", "W7"),
            "3342": ("F0", "W7"),
            "3343": ("F19", "W7"),
            "3344": ("F3", "W7"),
            "3345": ("F14", "W7"),
            # VEERING (trend=2) - Pressure Level 5
            "3351": ("F8", "W0"),
            "3352": ("F8", "W0"),
            "3353": ("F8", "W0"),
            "3354": ("F11", "W0"),
            "3355": ("F11", "W0"),
            # VEERING (trend=2) - Pressure Level 6
            "3361": ("F11", "W2"),
            "3362": ("F11", "W2"),
            "3363": ("F11", "W2"),
            "3364": ("F11", "W2"),
            "3365": ("F11", "W2"),
            # VEERING (trend=2) - Pressure Level 7
            "3371": ("F11", "W3"),
            "3372": ("F11", "W3"),
            "3373": ("F11", "W3"),
            "3374": ("F11", "W3"),
            "3375": ("F11", "W3"),
            # VEERING (trend=2) - Pressure Level 8
            "3381": ("F11", "W4"),
            "3382": ("F11", "W4"),
            "3383": ("F11", "W4"),
            "3384": ("F11", "W4"),
            "3385": ("F11", "W4"),
            # Additional specific combinations for other pressure levels
            "1211": ("F0", "W7"),
            "1212": ("F0", "W7"),
            "1213": ("F0", "W7"),
            "1214": ("F0", "W7"),
            "1215": ("F16", "W7"),
            "1221": ("F0", "W7"),
            "1222": ("F0", "W7"),
            "1223": ("F0", "W7"),
            "1224": ("F0", "W7"),
            "1225": ("F17", "W7"),
            "1231": ("F2", "W7"),
            "1232": ("F2", "W7"),
            "1233": ("F2", "W7"),
            "1234": ("F2", "W7"),
            "1235": ("F17", "W7"),
            "1241": ("F2", "W7"),
            "1242": ("F0", "W7"),
            "1243": ("F0", "W7"),
            "1244": ("F0", "W7"),
            "1245": ("F18", "W7"),
            "1251": ("F9", "W1"),
            "1252": ("F9", "W1"),
            "1253": ("F9", "W1"),
            "1254": ("F12", "W1"),
            "1255": ("F12", "W1"),
            "1261": ("F12", "W2"),
            "1262": ("F12", "W2"),
            "1263": ("F12", "W2"),
            "1264": ("F12", "W2"),
            "1265": ("F12", "W2"),
            "1271": ("F12", "W3"),
            "1272": ("F12", "W3"),
            "1273": ("F12", "W3"),
            "1274": ("F12", "W3"),
            "1275": ("F12", "W3"),
            "1281": ("F12", "W4"),
            "1282": ("F12", "W4"),
            "1283": ("F12", "W4"),
            "1284": ("F12", "W4"),
            "1285": ("F12", "W4"),
            "1411": ("F0", "W7"),
            "1412": ("F0", "W7"),
            "1413": ("F0", "W7"),
            "1414": ("F3", "W7"),
            "1415": ("F14", "W7"),
            "1421": ("F3", "W7"),
            "1422": ("F3", "W7"),
            "1423": ("F3", "W7"),
            "1424": ("F3", "W7"),
            "1425": ("F14", "W7"),
            "1431": ("F0", "W7"),
            "1432": ("F3", "W7"),
            "1433": ("F3", "W7"),
            "1434": ("F3", "W7"),
            "1435": ("F14", "W7"),
            "1441": ("F0", "W7"),
            "1442": ("F19", "W7"),
            "1443": ("F19", "W7"),
            "1444": ("F3", "W7"),
            "1445": ("F14", "W7"),
            "1451": ("F9", "W1"),
            "1452": ("F12", "W1"),
            "1453": ("F12", "W1"),
            "1454": ("F12", "W1"),
            "1455": ("F12", "W1"),
            "1461": ("F12", "W2"),
            "1462": ("F12", "W2"),
            "1463": ("F12", "W2"),
            "1464": ("F12", "W2"),
            "1465": ("F12", "W2"),
            "1471": ("F12", "W3"),
            "1472": ("F12", "W3"),
            "1473": ("F12", "W3"),
            "1474": ("F12", "W3"),
            "1475": ("F12", "W3"),
            "1481": ("F12", "W4"),
            "1482": ("F12", "W4"),
            "1483": ("F12", "W4"),
            "1484": ("F12", "W4"),
            "1485": ("F12", "W4"),
            "1111": ("F2", "W7"),
            "1112": ("F2", "W7"),
            "1113": ("F2", "W7"),
            "1114": ("F2", "W7"),
            "1115": ("F18", "W7"),
            "1121": ("F3", "W7"),
            "1122": ("F1", "W7"),
            "1123": ("F1", "W7"),
            "1124": ("F1", "W7"),
            "1125": ("F19", "W7"),
            "1131": ("F2", "W7"),
            "1132": ("F0", "W7"),
            "1133": ("F0", "W7"),
            "1134": ("F0", "W7"),
            "1135": ("F18", "W7"),
            "1141": ("F3", "W7"),
            "1142": ("F1", "W7"),
            "1143": ("F1", "W7"),
            "1144": ("F1", "W7"),
            "1145": ("F19", "W7"),
            "1151": ("F9", "W1"),
            "1152": ("F12", "W1"),
            "1153": ("F12", "W1"),
            "1154": ("F12", "W1"),
            "1155": ("F12", "W1"),
            "1161": ("F12", "W2"),
            "1162": ("F12", "W2"),
            "1163": ("F12", "W2"),
            "1164": ("F12", "W2"),
            "1165": ("F12", "W2"),
            "1171": ("F12", "W3"),
            "1172": ("F12", "W3"),
            "1173": ("F12", "W3"),
            "1174": ("F12", "W3"),
            "1175": ("F12", "W3"),
            "1181": ("F12", "W4"),
            "1182": ("F12", "W4"),
            "1183": ("F12", "W4"),
            "1184": ("F12", "W4"),
            "1185": ("F12", "W4"),
            "1511": ("F6", "W0"),
            "1512": ("F6", "W0"),
            "1513": ("F6", "W0"),
            "1514": ("F6", "W0"),
            "1515": ("F8", "W0"),
            "1521": ("F7", "W1"),
            "1522": ("F7", "W1"),
            "1523": ("F7", "W1"),
            "1524": ("F7", "W1"),
            "1525": ("F9", "W1"),
            "1531": ("F7", "W1"),
            "1532": ("F7", "W1"),
            "1533": ("F7", "W1"),
            "1534": ("F7", "W1"),
            "1535": ("F9", "W1"),
            "1541": ("F7", "W1"),
            "1542": ("F7", "W1"),
            "1543": ("F7", "W1"),
            "1544": ("F9", "W1"),
            "1545": ("F9", "W1"),
            "1551": ("F9", "W1"),
            "1552": ("F12", "W1"),
            "1553": ("F12", "W1"),
            "1554": ("F12", "W1"),
            "1555": ("F12", "W1"),
            "1561": ("F12", "W2"),
            "1562": ("F12", "W2"),
            "1563": ("F12", "W2"),
            "1564": ("F12", "W2"),
            "1565": ("F12", "W2"),
            "1571": ("F12", "W3"),
            "1572": ("F12", "W3"),
            "1573": ("F12", "W3"),
            "1574": ("F12", "W3"),
            "1575": ("F12", "W3"),
            "1581": ("F12", "W4"),
            "1582": ("F12", "W4"),
            "1583": ("F12", "W4"),
            "1584": ("F12", "W4"),
            "1585": ("F12", "W4"),
            # STEADY patterns for all pressure levels
            "2211": ("F0", "W7"),
            "2212": ("F0", "W7"),
            "2213": ("F0", "W7"),
            "2214": ("F0", "W7"),
            "2215": ("F16", "W7"),
            "2221": ("F0", "W7"),
            "2222": ("F0", "W7"),
            "2223": ("F0", "W7"),
            "2224": ("F0", "W7"),
            "2225": ("F17", "W7"),
            "2231": ("F2", "W7"),
            "2232": ("F2", "W7"),
            "2233": ("F2", "W7"),
            "2234": ("F2", "W7"),
            "2235": ("F17", "W7"),
            "2241": ("F2", "W7"),
            "2242": ("F0", "W7"),
            "2243": ("F0", "W7"),
            "2244": ("F0", "W7"),
            "2245": ("F18", "W7"),
            "2251": ("F9", "W1"),
            "2252": ("F12", "W1"),
            "2253": ("F12", "W1"),
            "2254": ("F12", "W1"),
            "2255": ("F12", "W1"),
            "2261": ("F12", "W2"),
            "2262": ("F12", "W2"),
            "2263": ("F12", "W2"),
            "2264": ("F12", "W2"),
            "2265": ("F12", "W2"),
            "2271": ("F12", "W3"),
            "2272": ("F12", "W3"),
            "2273": ("F12", "W3"),
            "2274": ("F12", "W3"),
            "2275": ("F12", "W3"),
            "2281": ("F12", "W4"),
            "2282": ("F12", "W4"),
            "2283": ("F12", "W4"),
            "2284": ("F12", "W4"),
            "2285": ("F12", "W4"),
            "2411": ("F0", "W7"),
            "2412": ("F3", "W7"),
            "2413": ("F3", "W7"),
            "2414": ("F3", "W7"),
            "2415": ("F14", "W7"),
            "2421": ("F0", "W7"),
            "2422": ("F3", "W7"),
            "2423": ("F6", "W7"),
            "2424": ("F6", "W7"),
            "2425": ("F8", "W7"),
            "2431": ("F0", "W7"),
            "2432": ("F3", "W7"),
            "2433": ("F6", "W7"),
            "2434": ("F6", "W7"),
            "2435": ("F8", "W7"),
            "2441": ("F0", "W7"),
            "2442": ("F3", "W7"),
            "2443": ("F6", "W7"),
            "2444": ("F6", "W7"),
            "2445": ("F8", "W7"),
            "2451": ("F9", "W1"),
            "2452": ("F12", "W1"),
            "2453": ("F12", "W1"),
            "2454": ("F12", "W1"),
            "2455": ("F12", "W1"),
            "2461": ("F12", "W2"),
            "2462": ("F12", "W2"),
            "2463": ("F12", "W2"),
            "2464": ("F12", "W2"),
            "2465": ("F12", "W2"),
            "2471": ("F12", "W3"),
            "2472": ("F12", "W3"),
            "2473": ("F12", "W3"),
            "2474": ("F12", "W3"),
            "2475": ("F12", "W3"),
            "2481": ("F12", "W4"),
            "2482": ("F12", "W4"),
            "2483": ("F12", "W4"),
            "2484": ("F12", "W4"),
            "2485": ("F12", "W4"),
            "2111": ("F2", "W7"),
            "2112": ("F0", "W7"),
            "2113": ("F0", "W7"),
            "2114": ("F0", "W7"),
            "2115": ("F18", "W7"),
            "2121": ("F2", "W7"),
            "2122": ("F0", "W7"),
            "2123": ("F0", "W7"),
            "2124": ("F0", "W7"),
            "2125": ("F18", "W7"),
            "2131": ("F2", "W7"),
            "2132": ("F0", "W7"),
            "2133": ("F0", "W7"),
            "2134": ("F0", "W7"),
            "2135": ("F18", "W7"),
            "2141": ("F2", "W7"),
            "2142": ("F0", "W7"),
            "2143": ("F0", "W7"),
            "2144": ("F0", "W7"),
            "2145": ("F18", "W7"),
            "2151": ("F9", "W1"),
            "2152": ("F12", "W1"),
            "2153": ("F12", "W1"),
            "2154": ("F12", "W1"),
            "2155": ("F12", "W1"),
            "2161": ("F12", "W2"),
            "2162": ("F12", "W2"),
            "2163": ("F12", "W2"),
            "2164": ("F12", "W2"),
            "2165": ("F12", "W2"),
            "2171": ("F12", "W3"),
            "2172": ("F12", "W3"),
            "2173": ("F12", "W3"),
            "2174": ("F12", "W3"),
            "2175": ("F12", "W3"),
            "2181": ("F12", "W4"),
            "2182": ("F12", "W4"),
            "2183": ("F12", "W4"),
            "2184": ("F12", "W4"),
            "2185": ("F12", "W4"),
            # VEERING patterns for remaining pressure levels
            "3211": ("F2", "W7"),
            "3212": ("F2", "W7"),
            "3213": ("F2", "W7"),
            "3214": ("F2", "W7"),
            "3215": ("F17", "W7"),
            "3221": ("F2", "W7"),
            "3222": ("F2", "W7"),
            "3223": ("F2", "W7"),
            "3224": ("F2", "W7"),
            "3225": ("F17", "W7"),
            "3231": ("F2", "W7"),
            "3232": ("F2", "W7"),
            "3233": ("F2", "W7"),
            "3234": ("F2", "W7"),
            "3235": ("F17", "W7"),
            "3241": ("F2", "W7"),
            "3242": ("F2", "W7"),
            "3243": ("F2", "W7"),
            "3244": ("F2", "W7"),
            "3245": ("F17", "W7"),
            "3251": ("F9", "W1"),
            "3252": ("F12", "W1"),
            "3253": ("F12", "W1"),
            "3254": ("F12", "W1"),
            "3255": ("F12", "W1"),
            "3261": ("F12", "W2"),
            "3262": ("F12", "W2"),
            "3263": ("F12", "W2"),
            "3264": ("F12", "W2"),
            "3265": ("F12", "W2"),
            "3271": ("F12", "W3"),
            "3272": ("F12", "W3"),
            "3273": ("F12", "W3"),
            "3274": ("F12", "W3"),
            "3275": ("F12", "W3"),
            "3281": ("F12", "W4"),
            "3282": ("F12", "W4"),
            "3283": ("F12", "W4"),
            "3284": ("F12", "W4"),
            "3285": ("F12", "W4"),
            "3411": ("F0", "W7"),
            "3412": ("F3", "W7"),
            "3413": ("F3", "W7"),
            "3414": ("F3", "W7"),
            "3415": ("F14", "W7"),
            "3421": ("F3", "W7"),
            "3422": ("F3", "W7"),
            "3423": ("F3", "W7"),
            "3424": ("F3", "W7"),
            "3425": ("F14", "W7"),
            "3431": ("F0", "W7"),
            "3432": ("F3", "W7"),
            "3433": ("F3", "W7"),
            "3434": ("F3", "W7"),
            "3435": ("F14", "W7"),
            "3441": ("F0", "W7"),
            "3442": ("F3", "W7"),
            "3443": ("F6", "W7"),
            "3444": ("F6", "W7"),
            "3445": ("F8", "W7"),
            "3451": ("F9", "W1"),
            "3452": ("F12", "W1"),
            "3453": ("F12", "W1"),
            "3454": ("F12", "W1"),
            "3455": ("F12", "W1"),
            "3461": ("F12", "W2"),
            "3462": ("F12", "W2"),
            "3463": ("F12", "W2"),
            "3464": ("F12", "W2"),
            "3465": ("F12", "W2"),
            "3471": ("F12", "W3"),
            "3472": ("F12", "W3"),
            "3473": ("F12", "W3"),
            "3474": ("F12", "W3"),
            "3475": ("F12", "W3"),
            "3481": ("F12", "W4"),
            "3482": ("F12", "W4"),
            "3483": ("F12", "W4"),
            "3484": ("F12", "W4"),
            "3485": ("F12", "W4"),
            "3111": ("F2", "W7"),
            "3112": ("F2", "W7"),
            "3113": ("F2", "W7"),
            "3114": ("F2", "W7"),
            "3115": ("F18", "W7"),
            "3121": ("F2", "W7"),
            "3122": ("F0", "W7"),
            "3123": ("F0", "W7"),
            "3124": ("F0", "W7"),
            "3125": ("F18", "W7"),
            "3131": ("F2", "W7"),
            "3132": ("F0", "W7"),
            "3133": ("F0", "W7"),
            "3134": ("F0", "W7"),
            "3135": ("F18", "W7"),
            "3141": ("F2", "W7"),
            "3142": ("F0", "W7"),
            "3143": ("F0", "W7"),
            "3144": ("F0", "W7"),
            "3145": ("F18", "W7"),
            "3151": ("F9", "W1"),
            "3152": ("F12", "W1"),
            "3153": ("F12", "W1"),
            "3154": ("F12", "W1"),
            "3155": ("F12", "W1"),
            "3161": ("F12", "W2"),
            "3162": ("F12", "W2"),
            "3163": ("F12", "W2"),
            "3164": ("F12", "W2"),
            "3165": ("F12", "W2"),
            "3171": ("F12", "W3"),
            "3172": ("F12", "W3"),
            "3173": ("F12", "W3"),
            "3174": ("F12", "W3"),
            "3175": ("F12", "W3"),
            "3181": ("F12", "W4"),
            "3182": ("F12", "W4"),
            "3183": ("F12", "W4"),
            "3184": ("F12", "W4"),
            "3185": ("F12", "W4"),
            "3511": ("F6", "W0"),
            "3512": ("F6", "W0"),
            "3513": ("F6", "W0"),
            "3514": ("F6", "W0"),
            "3515": ("F8", "W0"),
            "3521": ("F7", "W1"),
            "3522": ("F7", "W1"),
            "3523": ("F7", "W1"),
            "3524": ("F7", "W1"),
            "3525": ("F9", "W1"),
            "3531": ("F7", "W1"),
            "3532": ("F7", "W1"),
            "3533": ("F7", "W1"),
            "3534": ("F7", "W1"),
            "3535": ("F9", "W1"),
            "3541": ("F7", "W1"),
            "3542": ("F7", "W1"),
            "3543": ("F7", "W1"),
            "3544": ("F9", "W1"),
            "3545": ("F9", "W1"),
            "3551": ("F9", "W1"),
            "3552": ("F12", "W1"),
            "3553": ("F12", "W1"),
            "3554": ("F12", "W1"),
            "3555": ("F12", "W1"),
            "3561": ("F12", "W2"),
            "3562": ("F12", "W2"),
            "3563": ("F12", "W2"),
            "3564": ("F12", "W2"),
            "3565": ("F12", "W2"),
            "3571": ("F12", "W3"),
            "3572": ("F12", "W3"),
            "3573": ("F12", "W3"),
            "3574": ("F12", "W3"),
            "3575": ("F12", "W3"),
            "3581": ("F12", "W4"),
            "3582": ("F12", "W4"),
            "3583": ("F12", "W4"),
            "3584": ("F12", "W4"),
            "3585": ("F12", "W4"),
            # Pressure levels 6, 7, 8 for all wind trends (stormy conditions)
            "1611": ("F11", "W2"),
            "1612": ("F11", "W2"),
            "1613": ("F11", "W2"),
            "1614": ("F11", "W2"),
            "1615": ("F11", "W2"),
            "1621": ("F11", "W2"),
            "1622": ("F11", "W2"),
            "1623": ("F11", "W2"),
            "1624": ("F11", "W2"),
            "1625": ("F11", "W2"),
            "1631": ("F11", "W2"),
            "1632": ("F11", "W2"),
            "1633": ("F11", "W2"),
            "1634": ("F11", "W2"),
            "1635": ("F11", "W2"),
            "1641": ("F11", "W2"),
            "1642": ("F11", "W2"),
            "1643": ("F11", "W2"),
            "1644": ("F11", "W2"),
            "1645": ("F11", "W2"),
            "1651": ("F12", "W2"),
            "1652": ("F12", "W2"),
            "1653": ("F12", "W2"),
            "1654": ("F12", "W2"),
            "1655": ("F12", "W2"),
            "1711": ("F11", "W3"),
            "1712": ("F11", "W3"),
            "1713": ("F11", "W3"),
            "1714": ("F11", "W3"),
            "1715": ("F11", "W3"),
            "1721": ("F11", "W3"),
            "1722": ("F11", "W3"),
            "1723": ("F11", "W3"),
            "1724": ("F11", "W3"),
            "1725": ("F11", "W3"),
            "1731": ("F11", "W3"),
            "1732": ("F11", "W3"),
            "1733": ("F11", "W3"),
            "1734": ("F11", "W3"),
            "1735": ("F11", "W3"),
            "1741": ("F11", "W3"),
            "1742": ("F11", "W3"),
            "1743": ("F11", "W3"),
            "1744": ("F11", "W3"),
            "1745": ("F11", "W3"),
            "1751": ("F12", "W3"),
            "1752": ("F12", "W3"),
            "1753": ("F12", "W3"),
            "1754": ("F12", "W3"),
            "1755": ("F12", "W3"),
            "1811": ("F11", "W4"),
            "1812": ("F11", "W4"),
            "1813": ("F11", "W4"),
            "1814": ("F11", "W4"),
            "1815": ("F11", "W4"),
            "1821": ("F11", "W4"),
            "1822": ("F11", "W4"),
            "1823": ("F11", "W4"),
            "1824": ("F11", "W4"),
            "1825": ("F11", "W4"),
            "1831": ("F11", "W4"),
            "1832": ("F11", "W4"),
            "1833": ("F11", "W4"),
            "1834": ("F11", "W4"),
            "1835": ("F11", "W4"),
            "1841": ("F11", "W4"),
            "1842": ("F11", "W4"),
            "1843": ("F11", "W4"),
            "1844": ("F11", "W4"),
            "1845": ("F11", "W4"),
            "1851": ("F12", "W4"),
            "1852": ("F12", "W4"),
            "1853": ("F12", "W4"),
            "1854": ("F12", "W4"),
            "1855": ("F12", "W4"),
            "2611": ("F11", "W2"),
            "2612": ("F11", "W2"),
            "2613": ("F11", "W2"),
            "2614": ("F11", "W2"),
            "2615": ("F11", "W2"),
            "2621": ("F11", "W2"),
            "2622": ("F11", "W2"),
            "2623": ("F11", "W2"),
            "2624": ("F11", "W2"),
            "2625": ("F11", "W2"),
            "2631": ("F11", "W2"),
            "2632": ("F11", "W2"),
            "2633": ("F11", "W2"),
            "2634": ("F11", "W2"),
            "2635": ("F11", "W2"),
            "2641": ("F11", "W2"),
            "2642": ("F11", "W2"),
            "2643": ("F11", "W2"),
            "2644": ("F11", "W2"),
            "2645": ("F11", "W2"),
            "2651": ("F12", "W2"),
            "2652": ("F12", "W2"),
            "2653": ("F12", "W2"),
            "2654": ("F12", "W2"),
            "2655": ("F12", "W2"),
            "2711": ("F11", "W3"),
            "2712": ("F11", "W3"),
            "2713": ("F11", "W3"),
            "2714": ("F11", "W3"),
            "2715": ("F11", "W3"),
            "2721": ("F11", "W3"),
            "2722": ("F11", "W3"),
            "2723": ("F11", "W3"),
            "2724": ("F11", "W3"),
            "2725": ("F11", "W3"),
            "2731": ("F11", "W3"),
            "2732": ("F11", "W3"),
            "2733": ("F11", "W3"),
            "2734": ("F11", "W3"),
            "2735": ("F11", "W3"),
            "2741": ("F11", "W3"),
            "2742": ("F11", "W3"),
            "2743": ("F11", "W3"),
            "2744": ("F11", "W3"),
            "2745": ("F11", "W3"),
            "2751": ("F12", "W3"),
            "2752": ("F12", "W3"),
            "2753": ("F12", "W3"),
            "2754": ("F12", "W3"),
            "2755": ("F12", "W3"),
            "2811": ("F11", "W4"),
            "2812": ("F11", "W4"),
            "2813": ("F11", "W4"),
            "2814": ("F11", "W4"),
            "2815": ("F11", "W4"),
            "2821": ("F11", "W4"),
            "2822": ("F11", "W4"),
            "2823": ("F11", "W4"),
            "2824": ("F11", "W4"),
            "2825": ("F11", "W4"),
            "2831": ("F11", "W4"),
            "2832": ("F11", "W4"),
            "2833": ("F11", "W4"),
            "2834": ("F11", "W4"),
            "2835": ("F11", "W4"),
            "2841": ("F11", "W4"),
            "2842": ("F11", "W4"),
            "2843": ("F11", "W4"),
            "2844": ("F11", "W4"),
            "2845": ("F11", "W4"),
            "2851": ("F12", "W4"),
            "2852": ("F12", "W4"),
            "2853": ("F12", "W4"),
            "2854": ("F12", "W4"),
            "2855": ("F12", "W4"),
            "3611": ("F11", "W2"),
            "3612": ("F11", "W2"),
            "3613": ("F11", "W2"),
            "3614": ("F11", "W2"),
            "3615": ("F11", "W2"),
            "3621": ("F11", "W2"),
            "3622": ("F11", "W2"),
            "3623": ("F11", "W2"),
            "3624": ("F11", "W2"),
            "3625": ("F11", "W2"),
            "3631": ("F11", "W2"),
            "3632": ("F11", "W2"),
            "3633": ("F11", "W2"),
            "3634": ("F11", "W2"),
            "3635": ("F11", "W2"),
            "3641": ("F11", "W2"),
            "3642": ("F11", "W2"),
            "3643": ("F11", "W2"),
            "3644": ("F11", "W2"),
            "3645": ("F11", "W2"),
            "3651": ("F12", "W2"),
            "3652": ("F12", "W2"),
            "3653": ("F12", "W2"),
            "3654": ("F12", "W2"),
            "3655": ("F12", "W2"),
            "3711": ("F11", "W3"),
            "3712": ("F11", "W3"),
            "3713": ("F11", "W3"),
            "3714": ("F11", "W3"),
            "3715": ("F11", "W3"),
            "3721": ("F11", "W3"),
            "3722": ("F11", "W3"),
            "3723": ("F11", "W3"),
            "3724": ("F11", "W3"),
            "3725": ("F11", "W3"),
            "3731": ("F11", "W3"),
            "3732": ("F11", "W3"),
            "3733": ("F11", "W3"),
            "3734": ("F11", "W3"),
            "3735": ("F11", "W3"),
            "3741": ("F11", "W3"),
            "3742": ("F11", "W3"),
            "3743": ("F11", "W3"),
            "3744": ("F11", "W3"),
            "3745": ("F11", "W3"),
            "3751": ("F12", "W3"),
            "3752": ("F12", "W3"),
            "3753": ("F12", "W3"),
            "3754": ("F12", "W3"),
            "3755": ("F12", "W3"),
            "3811": ("F11", "W4"),
            "3812": ("F11", "W4"),
            "3813": ("F11", "W4"),
            "3814": ("F11", "W4"),
            "3815": ("F11", "W4"),
            "3821": ("F11", "W4"),
            "3822": ("F11", "W4"),
            "3823": ("F11", "W4"),
            "3824": ("F11", "W4"),
            "3825": ("F11", "W4"),
            "3831": ("F11", "W4"),
            "3832": ("F11", "W4"),
            "3833": ("F11", "W4"),
            "3834": ("F11", "W4"),
            "3835": ("F11", "W4"),
            "3841": ("F11", "W4"),
            "3842": ("F11", "W4"),
            "3843": ("F11", "W4"),
            "3844": ("F11", "W4"),
            "3845": ("F11", "W4"),
            "3851": ("F12", "W4"),
            "3852": ("F12", "W4"),
            "3853": ("F12", "W4"),
            "3854": ("F12", "W4"),
            "3855": ("F12", "W4"),
        }
