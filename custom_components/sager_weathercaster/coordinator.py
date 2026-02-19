"""DataUpdateCoordinator for Sager Weathercaster."""

from __future__ import annotations

import contextlib
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
    CONF_OPEN_METEO_ENABLED,
    CONF_PRESSURE_CHANGE_ENTITY,
    CONF_PRESSURE_ENTITY,
    CONF_RAINING_ENTITY,
    CONF_TEMPERATURE_ENTITY,
    CONF_WIND_DIR_ENTITY,
    CONF_WIND_HISTORIC_ENTITY,
    CONF_WIND_SPEED_ENTITY,
    DOMAIN,
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
    RAIN_THRESHOLD_LIGHT,
    SHOWER_FORECAST_CODES,
    TEMP_THRESHOLD_FLURRIES,
    UPDATE_INTERVAL_MINUTES,
    VELOCITY_LETTER_TO_INDEX,
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
    WIND_LETTERS,
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
from .sager_table import SAGER_TABLE

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
        self.config_data = dict(entry.data)
        self._open_meteo_enabled: bool = entry.options.get(
            CONF_OPEN_METEO_ENABLED, True
        )
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
            "disabled": not self._open_meteo_enabled,
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
        if not self._open_meteo_enabled:
            return

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

        # Rain sensor: binary (on/true/1) or numeric mm/h >= threshold
        raining_entity = self.config_data.get(CONF_RAINING_ENTITY)
        if raining_entity:
            rain_state = self.hass.states.get(raining_entity)
            if rain_state and rain_state.state not in (
                "unavailable",
                "unknown",
                "none",
            ):
                if rain_state.state in ("on", "true", "1"):
                    data["raining"] = True
                else:
                    data["raining"] = False
                    with contextlib.suppress(ValueError, TypeError):
                        data["raining"] = (
                            float(rain_state.state) >= RAIN_THRESHOLD_LIGHT
                        )
            else:
                data["raining"] = False
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
                data["temperature"] = None
                with contextlib.suppress(ValueError, TypeError):
                    data["temperature"] = float(temp_state.state)
            else:
                data["temperature"] = None
        else:
            data["temperature"] = None

        return data

    def _sager_algorithm(self, data: dict[str, Any]) -> dict[str, Any]:
        """Complete Sager weather algorithm using the full OpenHAB lookup table.

        Implements the original Sager Weathercaster algorithm with 25-letter
        wind encoding (A-Y + Z for calm) for accurate direction-dependent
        forecasts across all latitude zones.

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

        # Zone-aware wind direction index (0-7)
        wind_index_map = {
            direction: idx for idx, direction in enumerate(self._zone_directions)
        }
        wind_index = wind_index_map.get(z_wind)

        # Compute the Sager wind letter (A-Y) or Z for calm
        # trend_offset: 0=backing, 1=steady, 2=veering (z_rumbo: 1=steady, 2=veering, 3=backing)
        if wind_index is None:
            # Calm wind → letter Z
            wind_letter = "Z"
        else:
            trend_offset = (0, 1, 2, 0)[z_rumbo]  # 1→1, 2→2, 3→0
            wind_letter = WIND_LETTERS[wind_index * 3 + trend_offset]

        # Build lookup key: letter + hpa + pressure_trend + cloud
        lookup_key = f"{wind_letter}{z_hpa}{z_trend}{z_nubes}"

        value = SAGER_TABLE.get(lookup_key)
        if value is not None:
            confidence = 95
        else:
            _LOGGER.warning(
                "Combination not found in Sager table: %s "
                "(letter:%s, hpa:%d, pressure_trend:%d, cloud:%d), using default",
                lookup_key,
                wind_letter,
                z_hpa,
                z_trend,
                z_nubes,
            )
            value = "DU7"  # Default: unsettled, no change, W/NW
            confidence = 60

        # Decode value: forecast_letter + velocity_letter + direction_digit(s)
        forecast_code = value[0].lower()
        velocity_letter = value[1]
        dir1_digit = int(value[2])
        dir2_digit = int(value[3]) if len(value) == 4 else None

        # Temperature-based refinement: shower codes get "1" (rain) or "2" (snow/flurry)
        if forecast_code in SHOWER_FORECAST_CODES:
            temperature = data.get("temperature")
            if temperature is not None:
                forecast_code += "1" if temperature > TEMP_THRESHOLD_FLURRIES else "2"

        # Velocity letter → key (N=increasing, U=unchanged, D=decreasing, etc.)
        wind_vel_idx = VELOCITY_LETTER_TO_INDEX.get(velocity_letter, 7)
        wind_velocity_key = (
            WIND_VELOCITY_KEYS[wind_vel_idx]
            if wind_vel_idx < len(WIND_VELOCITY_KEYS)
            else "no_significant_change"
        )

        # Direction digit 1-9 → index 0-8 in WIND_DIRECTION_KEYS
        dir1_idx = dir1_digit - 1
        wind_direction_key = (
            WIND_DIRECTION_KEYS[dir1_idx]
            if 0 <= dir1_idx < len(WIND_DIRECTION_KEYS)
            else "variable"
        )

        # Optional second direction (transition forecast)
        wind_direction_key2: str | None = None
        if dir2_digit is not None:
            dir2_idx = dir2_digit - 1
            wind_direction_key2 = (
                WIND_DIRECTION_KEYS[dir2_idx]
                if 0 <= dir2_idx < len(WIND_DIRECTION_KEYS)
                else None
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

        result: dict[str, Any] = {
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
            "sager_letter": wind_letter,
        }
        if wind_direction_key2 is not None:
            result["wind_direction_key2"] = wind_direction_key2
        return result

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
        except ValueError:
            return 0.0
        except TypeError:
            return 0.0

        unit = state.attributes.get("unit_of_measurement", "")
        if unit == "lx":
            cloud_cover = self._lux_to_cloud_cover(value)
            _LOGGER.debug("Lux %s → cloud cover %s%%", value, round(cloud_cover, 1))
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
        airmass_term = (1229 + (614 * sin_elev) ** 2) ** 0.5 - 614 * sin_elev
        clear_sky_lux = (
            LUX_CLEAR_SKY_COEFFICIENT
            * (
                LUX_ATMOSPHERIC_A
                + LUX_ATMOSPHERIC_B * (LUX_ATMOSPHERIC_C**airmass_term)
            )
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
