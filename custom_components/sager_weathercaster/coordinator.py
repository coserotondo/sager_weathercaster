"""DataUpdateCoordinator for Sager Weathercaster."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
import math
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
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
    CONF_TEMPERATURE_ENTITY,
    CONF_WIND_DIR_ENTITY,
    CONF_WIND_HISTORIC_ENTITY,
    CONF_WIND_SPEED_ENTITY,
    DOMAIN,
    FORECAST_CODES,
    FORECAST_CONDITIONS,
    HPA_LEVELS,
    LATITUDE_NORTHERN_POLAR,
    LATITUDE_NORTHERN_TROPIC,
    LATITUDE_SOUTHERN_POLAR,
    LATITUDE_SOUTHERN_TROPIC,
    LUX_ATMOSPHERIC_A,
    LUX_ATMOSPHERIC_B,
    LUX_ATMOSPHERIC_C,
    LUX_CLEAR_SKY_COEFFICIENT,
    OPEN_METEO_UPDATE_INTERVAL_MINUTES,
    PRESSURE_CHANGE_MAX,
    PRESSURE_CHANGE_MIN,
    PRESSURE_MAX,
    PRESSURE_MIN,
    PRESSURE_TREND_DECREASING_RAPIDLY,
    PRESSURE_TREND_DECREASING_SLOWLY,
    PRESSURE_TREND_NORMAL,
    PRESSURE_TREND_RISING_RAPIDLY,
    PRESSURE_TREND_RISING_SLOWLY,
    SHOWER_FORECAST_CODES,
    TEMP_THRESHOLD_FLURRIES,
    UPDATE_INTERVAL_MINUTES,
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
    WIND_DIRECTION_KEYS,
    WIND_SPEED_MAX,
    WIND_SPEED_MIN,
    WIND_TREND_BACKING,
    WIND_TREND_STEADY,
    WIND_TREND_VEERING,
    WIND_VELOCITY_KEYS,
    ZAMBRETTI_FALLING_CONSTANT,
    ZAMBRETTI_FALLING_FACTOR,
    ZAMBRETTI_FORECASTS,
    ZAMBRETTI_RISING_CONSTANT,
    ZAMBRETTI_RISING_FACTOR,
    ZAMBRETTI_STEADY_CONSTANT,
    ZAMBRETTI_STEADY_FACTOR,
    ZAMBRETTI_TREND_THRESHOLD,
    ZONE_DIRECTIONS_NP,
    ZONE_DIRECTIONS_NT,
    ZONE_DIRECTIONS_SP,
    ZONE_DIRECTIONS_ST,
)
from .open_meteo import OpenMeteoClient, OpenMeteoData, OpenMeteoError

_LOGGER = logging.getLogger(__name__)


class SagerWeathercasterCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Sager Weathercaster coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: Any,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MINUTES),
            config_entry=entry,
        )
        # Merge initial data with any options saved via the options flow.
        # Options take precedence so reconfiguration always wins.
        self.config_data = {**entry.data, **entry.options}
        self._latitude = hass.config.latitude
        self._longitude = hass.config.longitude
        self._zone_directions = self._get_zone_directions()
        self._is_southern = self._latitude < 0

        # Open-Meteo API client and state
        self._open_meteo = OpenMeteoClient(
            async_get_clientsession(hass),
            self._latitude,
            self._longitude,
        )
        self._open_meteo_data: OpenMeteoData | None = None
        self._open_meteo_last_fetch: datetime | None = None
        self._open_meteo_failures: int = 0

    def _get_zone_directions(self) -> list[str]:
        """Get zone-specific wind direction array based on latitude.

        Returns the appropriate direction-to-index mapping for the
        configured latitude zone, following the Sager algorithm's
        hemisphere and climate zone adjustments.
        """
        lat = self._latitude
        if lat >= LATITUDE_NORTHERN_POLAR:
            return ZONE_DIRECTIONS_NP  # Northern Polar
        if lat >= LATITUDE_NORTHERN_TROPIC:
            return ZONE_DIRECTIONS_NT  # Northern Temperate (standard)
        if lat >= 0:
            return ZONE_DIRECTIONS_NP  # Northern Tropical
        if lat > LATITUDE_SOUTHERN_TROPIC:
            return ZONE_DIRECTIONS_SP  # Southern Tropical
        if lat > LATITUDE_SOUTHERN_POLAR:
            return ZONE_DIRECTIONS_ST  # Southern Temperate
        return ZONE_DIRECTIONS_SP  # Southern Polar

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from sensors and calculate forecast."""
        try:
            # Get sensor data (with lux-to-cloud-cover conversion)
            sensor_data = self._get_sensor_data()

            # Fetch Open-Meteo data on a separate interval
            await self._async_fetch_open_meteo()

            # Use Open-Meteo cloud cover as fallback if no local sensor
            if (
                not self.config_data.get(CONF_CLOUD_COVER_ENTITY)
                and self._open_meteo_data is not None
                and self._open_meteo_data.current_cloud_cover is not None
            ):
                sensor_data["cloud_cover"] = float(
                    self._open_meteo_data.current_cloud_cover
                )

            # Calculate reliability score
            reliability = self._calculate_reliability(sensor_data)

            # Calculate Sager forecast
            forecast = self._sager_algorithm(sensor_data)

            # Calculate Zambretti forecast for cross-validation
            zambretti = self._zambretti_forecast(sensor_data)

            # Cross-validate: adjust confidence based on agreement
            forecast = self._cross_validate(forecast, zambretti)
        except ValueError as err:
            if self.last_update_success:
                _LOGGER.warning("Sager Weathercaster is unavailable: %s", err)
            raise UpdateFailed(f"Failed to calculate forecast: {err}") from err
        except Exception as err:
            if self.last_update_success:
                _LOGGER.warning("Sager Weathercaster is unavailable: %s", err)
            raise UpdateFailed(f"Unexpected error during update: {err}") from err

        # Log recovery after a previous failure
        if not self.last_update_success:
            _LOGGER.info("Sager Weathercaster is back online")

        # Build Open-Meteo result for weather entity
        open_meteo_result: dict[str, Any] = {
            "available": self._open_meteo_data is not None,
            "hourly": [],
            "daily": [],
            "last_updated": self._open_meteo_last_fetch,
        }
        if self._open_meteo_data is not None:
            open_meteo_result["hourly"] = self._open_meteo_data.hourly
            open_meteo_result["daily"] = self._open_meteo_data.daily

        return {
            "sensor_data": sensor_data,
            "forecast": forecast,
            "zambretti": zambretti,
            "reliability": reliability,
            "open_meteo": open_meteo_result,
        }

    async def _async_fetch_open_meteo(self) -> None:
        """Fetch Open-Meteo data if the update interval has elapsed."""
        now = dt_util.utcnow()
        interval = timedelta(minutes=OPEN_METEO_UPDATE_INTERVAL_MINUTES)

        if (
            self._open_meteo_last_fetch is not None
            and now - self._open_meteo_last_fetch < interval
        ):
            return

        try:
            self._open_meteo_data = await self._open_meteo.async_get_forecast()
            self._open_meteo_last_fetch = now
            self._open_meteo_failures = 0
            _LOGGER.debug(
                "Open-Meteo data fetched: %d hourly, %d daily entries",
                len(self._open_meteo_data.hourly),
                len(self._open_meteo_data.daily),
            )
        except OpenMeteoError as err:
            self._open_meteo_failures += 1
            _LOGGER.warning(
                "Open-Meteo fetch failed (attempt %d): %s",
                self._open_meteo_failures,
                err,
            )
            # Keep using stale data if available; local-only fallback otherwise

    def _get_sensor_data(self) -> dict[str, Any]:
        """Get input data from configured entities."""
        data: dict[str, Any] = {}

        # Sensors with standard numeric range validation
        entities_map = {
            CONF_PRESSURE_ENTITY: ("pressure", 1013.25, PRESSURE_MIN, PRESSURE_MAX),
            CONF_WIND_DIR_ENTITY: ("wind_direction", 0, WIND_DIR_MIN, WIND_DIR_MAX),
            CONF_WIND_SPEED_ENTITY: ("wind_speed", 0, WIND_SPEED_MIN, WIND_SPEED_MAX),
            CONF_WIND_HISTORIC_ENTITY: (
                "wind_historic",
                0,
                WIND_DIR_MIN,
                WIND_DIR_MAX,
            ),
            CONF_PRESSURE_CHANGE_ENTITY: (
                "pressure_change",
                0,
                PRESSURE_CHANGE_MIN,
                PRESSURE_CHANGE_MAX,
            ),
        }

        for config_key, (data_key, default, min_val, max_val) in entities_map.items():
            entity_id = self.config_data.get(config_key)
            if entity_id:
                state = self.hass.states.get(entity_id)
                if state and state.state not in ("unavailable", "unknown", "none"):
                    try:
                        value = float(state.state)
                        if min_val <= value <= max_val:
                            data[data_key] = value
                        else:
                            _LOGGER.warning(
                                "Value out of range for %s: %s (expected %s-%s), using default %s",
                                entity_id,
                                value,
                                min_val,
                                max_val,
                                default,
                            )
                            data[data_key] = default
                    except (ValueError, TypeError) as err:
                        _LOGGER.warning(
                            "Invalid value for %s: %s (%s), using default %s",
                            entity_id,
                            state.state,
                            err,
                            default,
                        )
                        data[data_key] = default
                else:
                    data[data_key] = default
            else:
                data[data_key] = default

        # Cloud cover: auto-detect lux vs percentage by unit_of_measurement
        data["cloud_cover"] = self._get_cloud_cover()

        # Boolean sensor for rain
        raining_entity = self.config_data.get(CONF_RAINING_ENTITY)
        if raining_entity:
            rain_state = self.hass.states.get(raining_entity)
            data["raining"] = rain_state and rain_state.state in ("on", "true", "1")
        else:
            data["raining"] = False

        # Temperature for forecast refinement (showers vs flurries)
        temp_entity = self.config_data.get(CONF_TEMPERATURE_ENTITY)
        if temp_entity:
            temp_state = self.hass.states.get(temp_entity)
            if temp_state and temp_state.state not in (
                "unavailable",
                "unknown",
                "none",
            ):
                try:
                    data["temperature"] = float(temp_state.state)
                except (ValueError, TypeError):
                    data["temperature"] = None
            else:
                data["temperature"] = None
        else:
            data["temperature"] = None

        return data

    def _sager_algorithm(self, data: dict[str, Any]) -> dict[str, Any]:
        """Complete Sager weather algorithm.

        Args:
            data: Dictionary containing sensor data (pressure, wind, clouds, etc.)

        Returns:
            Dictionary containing forecast text and analysis parameters

        Raises:
            ValueError: If algorithm calculation fails
        """
        # Calculate input variables
        z_hpa = self._get_hpa_level(data["pressure"])
        z_wind = self._get_wind_dir(data["wind_direction"], data["wind_speed"])
        z_rumbo = self._get_wind_trend(data["wind_direction"], data["wind_historic"])
        z_trend = self._get_pressure_trend(data["pressure_change"])
        z_nubes = self._get_cloud_level(data["cloud_cover"], data["raining"])

        # Zone-aware wind direction index mapping
        wind_index_map = {
            direction: idx for idx, direction in enumerate(self._zone_directions)
        }
        wind_index_map[WIND_CARDINAL_CALM] = 7
        wind_index = wind_index_map.get(z_wind, 7)

        # Lookup forecast
        forecast_map = self._get_complete_forecast_map()
        lookup_key = f"{z_rumbo}{z_hpa}{z_trend}{z_nubes}"

        if lookup_key in forecast_map:
            f_code, w_code = forecast_map[lookup_key]
            confidence = 95
        else:
            _LOGGER.warning(
                "Combination not found: %s (trend:%d, hpa:%d, pressure:%d, cloud:%d), using default",
                lookup_key,
                z_rumbo,
                z_hpa,
                z_trend,
                z_nubes,
            )
            f_code, w_code = "F3", "W7"  # Default: Unstable weather, no change
            confidence = 60

        # Parse codes safely
        try:
            forecast_idx = int(f_code[1:])
            wind_idx = int(w_code[1:]) if w_code != "FF" else 7
        except (ValueError, IndexError) as err:
            _LOGGER.error("Error parsing forecast codes %s/%s: %s", f_code, w_code, err)
            forecast_idx = 3
            wind_idx = 7

        # Convert numeric index to letter code
        if forecast_idx < len(FORECAST_CODES):
            forecast_code = FORECAST_CODES[forecast_idx]
        else:
            forecast_code = "d"  # Default: unsettled

        # Temperature-based forecast refinement (showers vs flurries)
        if forecast_code in SHOWER_FORECAST_CODES:
            temperature = data.get("temperature")
            if temperature is not None:
                forecast_code += "1" if temperature > TEMP_THRESHOLD_FLURRIES else "2"

        # Wind keys for translation
        wind_velocity_key = (
            WIND_VELOCITY_KEYS[wind_idx]
            if wind_idx < len(WIND_VELOCITY_KEYS)
            else "no_significant_change"
        )
        wind_direction_key = (
            WIND_DIRECTION_KEYS[wind_index]
            if wind_index < len(WIND_DIRECTION_KEYS)
            else "nw_or_n"
        )

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
            "forecast_code": forecast_code,
            "wind_velocity_key": wind_velocity_key,
            "wind_direction_key": wind_direction_key,
            "hpa_level": z_hpa,
            "wind_dir": z_wind,
            "wind_trend": trend_names[z_rumbo - 1],
            "pressure_trend": pressure_names[z_trend - 1],
            "cloud_level": cloud_names[z_nubes - 1],
            "confidence": confidence,
            "latitude_zone": self._get_zone_name(),
        }

    def _get_hpa_level(self, hpa: float) -> int:
        """Get pressure level 1-8.

        Args:
            hpa: Atmospheric pressure in hectopascals

        Returns:
            Pressure level from 1 (very high) to 8 (extremely low)
        """
        for max_hpa, min_hpa, level in HPA_LEVELS:
            if min_hpa <= hpa < max_hpa:
                return level
        return 8  # Lowest pressure

    def _get_wind_dir(self, direction: float, speed: float) -> str:
        """Get 8-point cardinal wind direction.

        Args:
            direction: Wind direction in degrees (0-360)
            speed: Wind speed in km/h

        Returns:
            Cardinal direction (N, NE, E, SE, S, SW, W, NW) or 'calm'
        """
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
        """Get wind trend, hemisphere-aware.

        In the Northern Hemisphere, clockwise shift = veering, counterclockwise = backing.
        In the Southern Hemisphere, this is reversed due to the Coriolis effect.

        Args:
            current: Current wind direction in degrees
            historic: Historic wind direction (6h ago) in degrees

        Returns:
            1 for STEADY, 2 for VEERING, 3 for BACKING
        """
        if historic == 0 or current == 0:
            return 1  # No historic data

        # Calculate smallest angular difference
        diff = (current - historic + 180) % 360 - 180

        if abs(diff) <= 45:
            return 1  # STEADY

        # In Southern Hemisphere, backing and veering are reversed
        if self._is_southern:
            return 3 if diff > 0 else 2

        return 2 if diff > 0 else 3  # NH: clockwise=veering, counter=backing

    def _get_pressure_trend(self, change: float) -> int:
        """Get pressure trend.

        Args:
            change: Pressure change in hPa over 3 hours

        Returns:
            1 for Rising Rapidly, 2 for Rising Slowly, 3 for Normal,
            4 for Decreasing Slowly, 5 for Decreasing Rapidly
        """
        if change > 1.4:
            return 1
        if change > 0.68:
            return 2
        if change > -0.68:
            return 3
        if change > -1.4:
            return 4
        return 5

    def _get_cloud_level(self, cover: float, raining: bool) -> int:
        """Get cloud level.

        Args:
            cover: Cloud cover percentage (0-100)
            raining: Whether it's currently raining

        Returns:
            1 for Clear, 2 for Partly Cloudy, 3 for Mostly Cloudy,
            4 for Overcast, 5 for Raining
        """
        if raining:
            return 5
        if cover > 80:
            return 4
        if cover > 50:
            return 3
        if cover > 20:
            return 2
        return 1

    def _get_zone_name(self) -> str:
        """Get human-readable name of the current latitude zone."""
        lat = self._latitude
        if lat >= LATITUDE_NORTHERN_POLAR:
            return "Northern Polar"
        if lat >= LATITUDE_NORTHERN_TROPIC:
            return "Northern Temperate"
        if lat >= 0:
            return "Northern Tropical"
        if lat > LATITUDE_SOUTHERN_TROPIC:
            return "Southern Tropical"
        if lat > LATITUDE_SOUTHERN_POLAR:
            return "Southern Temperate"
        return "Southern Polar"

    def _get_cloud_cover(self) -> float:
        """Get cloud cover percentage, auto-detecting lux vs % input.

        If the configured cloud_cover_entity has unit_of_measurement 'lx',
        the value is treated as solar lux and converted to cloud cover %
        using the Kasten & Czeplak clear-sky illuminance model.
        Otherwise, the value is used directly as cloud cover %.
        """
        entity_id = self.config_data.get(CONF_CLOUD_COVER_ENTITY)
        if not entity_id:
            return 0.0

        state = self.hass.states.get(entity_id)
        if not state or state.state in ("unavailable", "unknown", "none"):
            return 0.0

        try:
            value = float(state.state)
        except (ValueError, TypeError):
            return 0.0

        unit = state.attributes.get("unit_of_measurement", "")
        if unit == "lx":
            cloud_cover = self._lux_to_cloud_cover(value)
            _LOGGER.debug(
                "Lux %s → cloud cover %s%%", value, round(cloud_cover, 1)
            )
            return cloud_cover

        # Direct percentage input
        return max(CLOUD_COVER_MIN, min(CLOUD_COVER_MAX, value))

    def _lux_to_cloud_cover(self, lux: float) -> float:
        """Convert solar lux to cloud cover % using clear-sky model.

        Uses sun elevation to calculate theoretical clear-sky illuminance,
        then compares with measured lux to estimate cloud cover.
        Falls back to Open-Meteo cloud cover during nighttime/twilight.
        """
        sun_state = self.hass.states.get("sun.sun")
        if not sun_state:
            return 50.0

        elevation = sun_state.attributes.get("elevation", 0)
        if not isinstance(elevation, (int, float)):
            return 50.0

        if elevation <= 1:
            # Night or deep twilight: lux model unreliable
            # Use Open-Meteo cloud cover if available
            if (
                self._open_meteo_data is not None
                and self._open_meteo_data.current_cloud_cover is not None
            ):
                return float(self._open_meteo_data.current_cloud_cover)
            return 50.0

        # Kasten & Czeplak clear-sky illuminance model
        sin_elev = math.sin(math.radians(elevation))
        airmass_term = (
            (1229 + (614 * sin_elev) ** 2) ** 0.5 - 614 * sin_elev
        )
        clear_sky_lux = (
            LUX_CLEAR_SKY_COEFFICIENT
            * (LUX_ATMOSPHERIC_A + LUX_ATMOSPHERIC_B * (LUX_ATMOSPHERIC_C ** airmass_term))
            * sin_elev
        )

        if clear_sky_lux <= 0:
            return 50.0

        # Ratio of clear-sky to measured: >1 means clouds reducing light
        factor = clear_sky_lux / max(lux, 0.001)
        cloud_cover = math.log(factor) * 100.0
        return max(0.0, min(100.0, cloud_cover))

    def _calculate_reliability(self, sensor_data: dict[str, Any]) -> dict[str, Any]:
        """Calculate forecast reliability as a percentage (0-100).

        Reliability is based on how many critical input sensors are
        configured and providing valid data. Each sensor has a weight
        reflecting its importance to the Sager algorithm accuracy.

        Returns a dict with score and per-sensor status details.
        """
        # (config_key, label, weight) - weights sum to 100
        critical_entities: list[tuple[str, str, int]] = [
            (CONF_PRESSURE_ENTITY, "pressure", 20),
            (CONF_WIND_DIR_ENTITY, "wind_direction", 15),
            (CONF_WIND_SPEED_ENTITY, "wind_speed", 10),
            (CONF_WIND_HISTORIC_ENTITY, "wind_historic", 20),
            (CONF_PRESSURE_CHANGE_ENTITY, "pressure_change", 20),
            (CONF_CLOUD_COVER_ENTITY, "cloud_cover", 15),
        ]

        score = 0
        sensor_status: dict[str, str] = {}

        for config_key, label, weight in critical_entities:
            entity_id = self.config_data.get(config_key)
            if not entity_id:
                sensor_status[label] = "not configured"
                continue
            state = self.hass.states.get(entity_id)
            if state and state.state not in ("unavailable", "unknown", "none"):
                score += weight
                sensor_status[label] = "ok"
            else:
                sensor_status[label] = "unavailable"

        return {
            "score": min(score, 100),
            "sensor_status": sensor_status,
        }

    def _zambretti_forecast(self, sensor_data: dict[str, Any]) -> dict[str, Any]:
        """Calculate Zambretti weather forecast.

        Uses current pressure and pressure change to produce an independent
        forecast for cross-validation with the Sager algorithm.

        Returns dict with zambretti_key, condition, and trend.
        """
        pressure = sensor_data.get("pressure", 1013.25)
        pressure_change = sensor_data.get("pressure_change", 0.0)

        # Determine pressure trend
        # pressure_change is over 6h; Zambretti uses 3h with threshold 1.6 hPa
        # Scale: 6h change / 2 ≈ 3h change
        change_3h = pressure_change / 2.0

        if change_3h < -ZAMBRETTI_TREND_THRESHOLD:
            trend = "falling"
            forecast_idx = math.floor(
                ZAMBRETTI_FALLING_CONSTANT - ZAMBRETTI_FALLING_FACTOR * pressure
            )
            forecast_idx = max(1, min(9, forecast_idx))
        elif change_3h > ZAMBRETTI_TREND_THRESHOLD:
            trend = "rising"
            forecast_idx = math.floor(
                ZAMBRETTI_RISING_CONSTANT - ZAMBRETTI_RISING_FACTOR * pressure
            )
            forecast_idx = max(20, min(32, forecast_idx))
        else:
            trend = "steady"
            forecast_idx = math.floor(
                ZAMBRETTI_STEADY_CONSTANT - ZAMBRETTI_STEADY_FACTOR * pressure
            )
            forecast_idx = max(10, min(19, forecast_idx))

        # Wind direction adjustment (N=0, E/W=+1, S=+2)
        wind_dir = sensor_data.get("wind_direction", 0)
        if 135 <= wind_dir <= 225:  # South-ish
            forecast_idx = min(forecast_idx + 2, max(ZAMBRETTI_FORECASTS[trend]))
        elif 45 <= wind_dir < 135 or 225 < wind_dir <= 315:  # East or West
            forecast_idx = min(forecast_idx + 1, max(ZAMBRETTI_FORECASTS[trend]))

        lookup = ZAMBRETTI_FORECASTS.get(trend, {})
        if forecast_idx in lookup:
            zambretti_key, condition = lookup[forecast_idx]
        else:
            zambretti_key = "unknown"
            condition = "partlycloudy"

        return {
            "zambretti_key": zambretti_key,
            "condition": condition,
            "trend": trend,
            "index": forecast_idx,
        }

    def _cross_validate(
        self, forecast: dict[str, Any], zambretti: dict[str, Any]
    ) -> dict[str, Any]:
        """Cross-validate Sager and Zambretti forecasts.

        Adjusts confidence based on agreement between the two algorithms.
        """
        sager_code = forecast.get("forecast_code", "d")
        sager_condition = FORECAST_CONDITIONS.get(sager_code, "partlycloudy")
        zambretti_condition = zambretti.get("condition", "partlycloudy")

        # Severity ranking for comparison
        severity = {
            "sunny": 0,
            "clear-night": 0,
            "partlycloudy": 1,
            "cloudy": 2,
            "rainy": 3,
            "snowy": 3,
            "pouring": 4,
        }
        sager_sev = severity.get(sager_condition, 1)
        zambretti_sev = severity.get(zambretti_condition, 1)

        base_confidence = forecast.get("confidence", 80)
        diff = abs(sager_sev - zambretti_sev)

        if diff == 0:
            # Perfect agreement: boost confidence
            forecast["confidence"] = min(base_confidence + 10, 99)
            forecast["cross_validation"] = "agree"
        elif diff == 1:
            # Close agreement: keep confidence
            forecast["cross_validation"] = "close"
        elif diff == 2:
            # Moderate disagreement: reduce confidence slightly
            forecast["confidence"] = max(base_confidence - 10, 40)
            forecast["cross_validation"] = "diverge"
        else:
            # Strong disagreement: significant confidence reduction
            forecast["confidence"] = max(base_confidence - 20, 30)
            forecast["cross_validation"] = "conflict"

        forecast["zambretti_condition"] = zambretti_condition
        return forecast

    def _get_complete_forecast_map(self) -> dict[str, tuple[str, str]]:
        """Complete lookup table from Sager algorithm.

        Returns:
            Dictionary mapping lookup keys to (forecast_code, wind_code) tuples

        Note:
            Contains 600+ combinations covering all possible weather scenarios
        """
        # Complete Sager forecast lookup table
        # Format: "trend+hpa_level+pressure_trend+cloud_level": (forecast_code, wind_code)
        # Copied from original implementation to maintain algorithm accuracy
        return {
            # BACKING (trend=1, representing index 3 in code)
            "1311": ("F0", "W7"),
            "1312": ("F0", "W7"),
            "1313": ("F0", "W7"),
            "1314": ("F0", "W7"),
            "1315": ("F18", "W7"),
            "1321": ("F0", "W7"),
            "1322": ("F0", "W7"),
            "1323": ("F0", "W7"),
            "1324": ("F19", "W7"),
            "1325": ("F14", "W7"),
            "1331": ("F0", "W7"),
            "1332": ("F0", "W7"),
            "1333": ("F0", "W7"),
            "1334": ("F19", "W7"),
            "1335": ("F14", "W7"),
            "1341": ("F0", "W7"),
            "1342": ("F19", "W7"),
            "1343": ("F19", "W7"),
            "1344": ("F3", "W7"),
            "1345": ("F14", "W7"),
            "1351": ("F8", "W0"),
            "1352": ("F8", "W0"),
            "1353": ("F8", "W0"),
            "1354": ("F11", "W0"),
            "1355": ("F11", "W0"),
            "1361": ("F11", "W2"),
            "1362": ("F11", "W2"),
            "1363": ("F11", "W2"),
            "1364": ("F11", "W2"),
            "1365": ("F11", "W2"),
            "1371": ("F11", "W3"),
            "1372": ("F11", "W3"),
            "1373": ("F11", "W3"),
            "1374": ("F11", "W3"),
            "1375": ("F11", "W3"),
            "1381": ("F11", "W4"),
            "1382": ("F11", "W4"),
            "1383": ("F11", "W4"),
            "1384": ("F11", "W4"),
            "1385": ("F11", "W4"),
            # STEADY (trend=2)
            "2311": ("F0", "W7"),
            "2312": ("F0", "W7"),
            "2313": ("F0", "W7"),
            "2314": ("F19", "W7"),
            "2315": ("F14", "W7"),
            "2321": ("F0", "W7"),
            "2322": ("F0", "W7"),
            "2323": ("F0", "W7"),
            "2324": ("F19", "W7"),
            "2325": ("F14", "W7"),
            "2331": ("F0", "W7"),
            "2332": ("F0", "W7"),
            "2333": ("F0", "W7"),
            "2334": ("F19", "W7"),
            "2335": ("F14", "W7"),
            "2341": ("F0", "W7"),
            "2342": ("F19", "W7"),
            "2343": ("F19", "W7"),
            "2344": ("F3", "W7"),
            "2345": ("F14", "W7"),
            "2351": ("F8", "W0"),
            "2352": ("F11", "W0"),
            "2353": ("F11", "W0"),
            "2354": ("F11", "W0"),
            "2355": ("F11", "W0"),
            "2361": ("F11", "W2"),
            "2362": ("F11", "W2"),
            "2363": ("F11", "W2"),
            "2364": ("F11", "W2"),
            "2365": ("F11", "W2"),
            "2371": ("F11", "W3"),
            "2372": ("F11", "W3"),
            "2373": ("F11", "W3"),
            "2374": ("F11", "W3"),
            "2375": ("F11", "W3"),
            "2381": ("F11", "W4"),
            "2382": ("F11", "W4"),
            "2383": ("F11", "W4"),
            "2384": ("F11", "W4"),
            "2385": ("F11", "W4"),
            # VEERING (trend=3)
            "3311": ("F0", "W7"),
            "3312": ("F0", "W7"),
            "3313": ("F0", "W7"),
            "3314": ("F19", "W7"),
            "3315": ("F14", "W7"),
            "3321": ("F0", "W7"),
            "3322": ("F0", "W7"),
            "3323": ("F0", "W7"),
            "3324": ("F19", "W7"),
            "3325": ("F14", "W7"),
            "3331": ("F0", "W7"),
            "3332": ("F0", "W7"),
            "3333": ("F0", "W7"),
            "3334": ("F19", "W7"),
            "3335": ("F14", "W7"),
            "3341": ("F0", "W7"),
            "3342": ("F0", "W7"),
            "3343": ("F19", "W7"),
            "3344": ("F3", "W7"),
            "3345": ("F14", "W7"),
            "3351": ("F8", "W0"),
            "3352": ("F8", "W0"),
            "3353": ("F8", "W0"),
            "3354": ("F11", "W0"),
            "3355": ("F11", "W0"),
            "3361": ("F11", "W2"),
            "3362": ("F11", "W2"),
            "3363": ("F11", "W2"),
            "3364": ("F11", "W2"),
            "3365": ("F11", "W2"),
            "3371": ("F11", "W3"),
            "3372": ("F11", "W3"),
            "3373": ("F11", "W3"),
            "3374": ("F11", "W3"),
            "3375": ("F11", "W3"),
            "3381": ("F11", "W4"),
            "3382": ("F11", "W4"),
            "3383": ("F11", "W4"),
            "3384": ("F11", "W4"),
            "3385": ("F11", "W4"),
            # Additional pressure level combinations - continuing pattern
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
            # STEADY patterns for remaining pressure levels
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
