"""DataUpdateCoordinator for Sager Weathercaster."""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta
import logging
import math
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import state_changes_during_period
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    ALGORITHM_WINDOW_HOURS,
    CLOUD_COVER_MAX,
    CLOUD_COVER_MIN,
    CLOUD_LEVEL_CLEAR,
    CLOUD_LEVEL_MOSTLY_CLOUDY,
    CLOUD_LEVEL_OVERCAST,
    CLOUD_LEVEL_PARTLY_CLOUDY,
    CLOUD_LEVEL_RAINING,
    CONF_CLOUD_COVER_ENTITY,
    CONF_DEWPOINT_ENTITY,
    CONF_HUMIDITY_ENTITY,
    CONF_INITIAL_CALIBRATION_FACTOR,
    CONF_PRESSURE_ENTITY,
    CONF_RAINING_ENTITY,
    CONF_TEMPERATURE_ENTITY,
    CONF_WEATHER_ENTITY,
    CONF_WIND_DIR_ENTITY,
    CONF_WIND_SPEED_ENTITY,
    DEFAULT_AOD_550NM,
    DOMAIN,
    EXTERNAL_WEATHER_UPDATE_INTERVAL_MINUTES,
    FORECAST_CONDITIONS,
    HPA_LEVELS,
    IRRADIANCE_CLEAR_SKY_COEFFICIENT,
    LATITUDE_NORTHERN_POLAR,
    LATITUDE_NORTHERN_TROPIC,
    LATITUDE_SOUTHERN_POLAR,
    LATITUDE_SOUTHERN_TROPIC,
    LUX_CLEAR_SKY_COEFFICIENT,
    PRESSURE_MAX,
    PRESSURE_MIN,
    PRESSURE_TREND_DECREASING_RAPIDLY,
    PRESSURE_TREND_DECREASING_SLOWLY,
    PRESSURE_TREND_NORMAL,
    PRESSURE_TREND_RISING_RAPIDLY,
    PRESSURE_TREND_RISING_SLOWLY,
    RAIN_THRESHOLD_LIGHT,
    SHOWER_FORECAST_CODES,
    SOLAR_CONSTANT_WM2,
    SOLAR_LUMINOUS_EFFICACY,
    TEMP_THRESHOLD_FLURRIES,
    UPDATE_INTERVAL_MINUTES,
    VELOCITY_LETTER_TO_INDEX,
    WIND_AVERAGE_WINDOW_MINUTES,
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
from .ha_weather import ExternalWeatherData, HAWeatherClient
from .sager_table import SAGER_TABLE

_LOGGER = logging.getLogger(__name__)


def _is_valid_float(value: str) -> bool:
    """Return True if *value* can be converted to a float."""
    try:
        float(value)
    except ValueError, TypeError:
        return False
    return True


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
        # Entities start unavailable; set to True only after the first real
        # refresh (once all source sensor entities are loaded in the state machine).
        self.last_update_success = False
        self.config_data = dict(entry.data)
        self._ext_weather_entity: str | None = entry.options.get(CONF_WEATHER_ENTITY)
        self._initial_calib_factor: float | None = entry.options.get(
            CONF_INITIAL_CALIBRATION_FACTOR
        )
        self._latitude = hass.config.latitude
        self._longitude = hass.config.longitude
        self._zone_directions = self._get_zone_directions()
        self._is_southern = self._latitude < 0

        # External HA weather entity client and cached data
        self._ext_weather_client: HAWeatherClient | None = (
            HAWeatherClient(hass, self._ext_weather_entity)
            if self._ext_weather_entity
            else None
        )
        self._ext_weather_data: ExternalWeatherData | None = None
        self._ext_weather_last_fetch: datetime | None = None
        # Multiplicative correction for local atmospheric turbidity/sensor offset.
        # Shared by the lux and W/m² cloud-cover paths; converges toward the
        # true local ratio of measured clear-sky value to modelled clear-sky
        # value via external weather ground-truth calibration. Persisted across
        # reloads and restarts via .storage so calibration is not lost.
        self._sky_calibration_factor: float = 1.0
        # Version 2: invalidates Kasten & Czeplak-era calibration values so
        # the new Ineichen-Perez model starts from a neutral factor of 1.0.
        self._store: Store[dict[str, float]] = Store(
            hass, 2, f"{DOMAIN}.calibration.{entry.entry_id}"
        )
        self._calibration_loaded: bool = False
        self._calibration_dirty: bool = False
        # Set to True when local lux indicates clear sky but external weather
        # reports heavy cloud/fog; exposed as a diagnostic attribute so the
        # user can see when and how often the sources disagree.
        self._ext_weather_disagreement: bool = False

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
        if not self._calibration_loaded:
            await self._async_load_calibration()

        try:
            # Fetch external HA weather entity data first so that
            # _get_sensor_data() → _sky_to_cloud_cover() can use it for the
            # nighttime / low-angle fallback on the very first run after a
            # reload (when _ext_weather_data would otherwise still be None).
            await self._async_fetch_external_weather()

            # Get sensor data (with lux-to-cloud-cover conversion)
            sensor_data = self._get_sensor_data()

            # Use external weather cloud cover as fallback if no local sensor
            if (
                not self.config_data.get(CONF_CLOUD_COVER_ENTITY)
                and (ext_cloud := self._ext_cloud_cover()) is not None
            ):
                sensor_data["cloud_cover"] = float(ext_cloud)

            # Overwrite defaults with historically-computed values from recorder.
            # pressure_change and wind_historic default to 0 / current direction
            # in _get_sensor_data(); recorder results (when available) are used here.
            pressure_change = await self._async_compute_pressure_change(
                sensor_data.get("pressure")
            )
            if pressure_change is not None:
                sensor_data["pressure_change"] = pressure_change
                sensor_data["_pressure_change_from_recorder"] = True

            wind_historic = await self._async_compute_wind_historic()
            if wind_historic is not None:
                sensor_data["wind_historic"] = wind_historic
                sensor_data["_wind_historic_from_recorder"] = True

            mean_dir, mean_speed = await self._async_compute_vector_wind_avg()
            if mean_dir is not None:
                sensor_data["wind_direction"] = mean_dir
            if mean_speed is not None:
                sensor_data["wind_speed"] = mean_speed

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

        # Persist calibration factor if it was updated during this cycle
        if self._calibration_dirty:
            await self._async_save_calibration()
            self._calibration_dirty = False

        # Build external weather result for weather/sensor entities
        ext_weather_result: dict[str, Any] = {
            "configured": self._ext_weather_entity is not None,
            "available": self._ext_weather_data is not None,
            "hourly": [],
            "daily": [],
            "attribution": None,
            "last_updated": self._ext_weather_last_fetch,
            "cloud_conflict": self._ext_weather_disagreement,
        }
        if self._ext_weather_data is not None:
            ext_weather_result["hourly"] = self._ext_weather_data.hourly
            ext_weather_result["daily"] = self._ext_weather_data.daily
            ext_weather_result["attribution"] = self._ext_weather_data.attribution

        return {
            "sensor_data": sensor_data,
            "forecast": forecast,
            "zambretti": zambretti,
            "reliability": reliability,
            "ext_weather": ext_weather_result,
        }

    async def _async_query_history(
        self,
        entity_id: str,
        start: datetime,
        end: datetime,
        include_start_time_state: bool = True,
    ) -> list[State]:
        """Query entity state history from the HA recorder.

        Runs the blocking database call in the recorder's executor.
        Returns an empty list when the recorder is unavailable or the
        entity has no history in the requested window.

        include_start_time_state=True (default): includes the state that was
        active at `start`, even if it last changed before `start`.  Use for
        short windows (e.g. 10-min wind average) where a recent stable reading
        is valid.

        include_start_time_state=False: returns only real state changes inside
        [start, end].  Use for 6 h look-backs to avoid a synthetic "start-time
        state" whose timestamp is faked to `start` by HA's recorder, which
        would defeat any staleness guard.
        """
        try:
            instance = get_instance(self.hass)
        except Exception:  # noqa: BLE001
            # Recorder not running (e.g. minimal HA setup or migration in progress).
            return []
        result: dict[str, list[State]] = await instance.async_add_executor_job(
            state_changes_during_period,
            self.hass,
            start,
            end,
            entity_id,  # single entity string
            True,  # no_attributes — we only need .state
            False,  # descending
            None,  # limit
            include_start_time_state,
        )
        return result.get(entity_id, [])

    async def _async_compute_pressure_change(
        self, current_pressure: float | None
    ) -> float | None:
        """Return the 6h pressure change in hPa, computed from recorder history.

        Queries the pressure sensor history to find the reading from
        ALGORITHM_WINDOW_HOURS ago, then returns (current − past).
        Returns None when the recorder has less than 6h of history or
        is unavailable.
        """
        entity_id = self.config_data.get(CONF_PRESSURE_ENTITY)
        if not entity_id or current_pressure is None:
            return None

        now = dt_util.utcnow()
        # Query a 2 h window ending at ALGORITHM_WINDOW_HOURS ago.  Using
        # include_start_time_state=False means only real recorded state changes
        # are returned — the recorder's synthetic "start-time state" would have
        # its last_changed faked to the window-start timestamp, making a
        # staleness guard ineffective.  An empty result correctly signals that
        # the recorder has a gap at the 6 h mark (e.g. after an HA restart).
        end = now - timedelta(hours=ALGORITHM_WINDOW_HOURS)
        start = now - timedelta(hours=ALGORITHM_WINDOW_HOURS + 2)

        states = await self._async_query_history(
            entity_id, start, end, include_start_time_state=False
        )
        if not states:
            return None

        try:
            pressure_past = float(states[-1].state)
        except ValueError, TypeError:
            return None

        if not PRESSURE_MIN <= pressure_past <= PRESSURE_MAX:
            return None

        change = current_pressure - pressure_past
        _LOGGER.debug(
            "Pressure change computed from recorder: %.2f hPa over %dh",
            change,
            ALGORITHM_WINDOW_HOURS,
        )
        return max(-50.0, min(50.0, change))

    async def _async_compute_wind_historic(self) -> float | None:
        """Return the wind direction from ALGORITHM_WINDOW_HOURS ago via recorder.

        Returns None when the recorder has insufficient history.
        """
        entity_id = self.config_data.get(CONF_WIND_DIR_ENTITY)
        if not entity_id:
            return None

        now = dt_util.utcnow()
        # Same reasoning as _async_compute_pressure_change: use a 2 h window
        # ending at ALGORITHM_WINDOW_HOURS ago with include_start_time_state=False
        # so that only real recorded changes are returned.
        end = now - timedelta(hours=ALGORITHM_WINDOW_HOURS)
        start = now - timedelta(hours=ALGORITHM_WINDOW_HOURS + 2)

        states = await self._async_query_history(
            entity_id, start, end, include_start_time_state=False
        )
        if not states:
            return None

        try:
            direction = float(states[-1].state)
        except ValueError, TypeError:
            return None

        if not WIND_DIR_MIN <= direction <= WIND_DIR_MAX:
            return None

        _LOGGER.debug("Historic wind direction from recorder: %.1f°", direction)
        return direction

    async def _async_compute_vector_wind_avg(
        self,
    ) -> tuple[float | None, float | None]:
        """Return vector-averaged (direction, speed) over the last WIND_AVERAGE_WINDOW_MINUTES.

        Uses the circular mean of all recorded direction readings in the window,
        weighted uniformly (not by speed) to keep the computation simple.
        Speed is the scalar mean of all speed readings in the window.

        Returns (None, None) when no direction history is available.
        """
        dir_entity_id = self.config_data.get(CONF_WIND_DIR_ENTITY)
        if not dir_entity_id:
            return None, None

        now = dt_util.utcnow()
        start = now - timedelta(minutes=WIND_AVERAGE_WINDOW_MINUTES)

        dir_states = await self._async_query_history(dir_entity_id, start, now)

        directions: list[float] = []
        for state in dir_states:
            if state.state in ("unavailable", "unknown", "none"):
                continue
            try:
                d = float(state.state)
                if WIND_DIR_MIN <= d <= WIND_DIR_MAX:
                    directions.append(d)
            except ValueError, TypeError:
                pass

        if not directions:
            return None, None

        sin_sum = sum(math.sin(math.radians(d)) for d in directions)
        cos_sum = sum(math.cos(math.radians(d)) for d in directions)
        mean_dir = math.degrees(math.atan2(sin_sum, cos_sum)) % 360

        mean_speed: float | None = None
        speed_entity_id = self.config_data.get(CONF_WIND_SPEED_ENTITY)
        if speed_entity_id:
            speed_states = await self._async_query_history(speed_entity_id, start, now)
            speeds: list[float] = [
                float(s.state)
                for s in speed_states
                if s.state not in ("unavailable", "unknown", "none")
                and _is_valid_float(s.state)
                and WIND_SPEED_MIN <= float(s.state) <= WIND_SPEED_MAX
            ]
            if speeds:
                mean_speed = sum(speeds) / len(speeds)

        _LOGGER.debug(
            "Vector wind avg: dir=%.1f° (%d samples), speed=%s",
            mean_dir,
            len(directions),
            f"{mean_speed:.1f}" if mean_speed is not None else "n/a",
        )
        return mean_dir, mean_speed

    def _ext_cloud_cover(self) -> int | None:
        """Return the best available current cloud cover from external weather data.

        Prefers the ``current_cloud_cover`` state attribute; falls back to the
        ``cloud_cover`` field of the first hourly forecast entry that carries a
        value.  Many integrations (e.g. met.no) only include cloud coverage in
        their hourly forecasts, not in the entity's current state attributes.
        """
        if self._ext_weather_data is None:
            return None
        if self._ext_weather_data.current_cloud_cover is not None:
            return self._ext_weather_data.current_cloud_cover
        return next(
            (
                e.cloud_cover
                for e in self._ext_weather_data.hourly
                if e.cloud_cover is not None
            ),
            None,
        )

    async def _async_fetch_external_weather(self) -> None:
        """Fetch external HA weather entity data if the update interval has elapsed."""
        if self._ext_weather_client is None:
            return

        now = dt_util.utcnow()
        interval = timedelta(minutes=EXTERNAL_WEATHER_UPDATE_INTERVAL_MINUTES)

        if (
            self._ext_weather_last_fetch is not None
            and now - self._ext_weather_last_fetch < interval
        ):
            return

        data = await self._ext_weather_client.async_get_data()
        if data is not None:
            self._ext_weather_data = data
            self._ext_weather_last_fetch = now

    def _get_sensor_data(self) -> dict[str, Any]:
        """Get input data from configured entities."""
        data: dict[str, Any] = {}

        # Sensors with standard numeric range validation
        entities_map = {
            CONF_PRESSURE_ENTITY: ("pressure", 1013.25, PRESSURE_MIN, PRESSURE_MAX),
            CONF_WIND_DIR_ENTITY: ("wind_direction", 0, WIND_DIR_MIN, WIND_DIR_MAX),
            CONF_WIND_SPEED_ENTITY: ("wind_speed", 0, WIND_SPEED_MIN, WIND_SPEED_MAX),
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

        # Defaults for historically-computed fields; overwritten in _async_update_data
        # once the recorder query results are available.
        data.setdefault("wind_historic", data.get("wind_direction", 0.0))
        data.setdefault("pressure_change", 0.0)

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
        """Complete Sager weather algorithm using the full Sager Weathercaster lookup table.

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
        """Get cloud cover percentage, auto-detecting the sensor unit.

        Supported units for the configured cloud_cover_entity:
        - '%': used directly as cloud cover percentage.
        - 'lx': solar illuminance converted via the Kasten & Czeplak
          clear-sky model with local turbidity correction and external weather calibration.
        - 'W/m²' / 'W/m2': solar irradiance converted via the same model
          using the solar-constant coefficient — the most accurate input since
          the Kasten formula was designed for irradiance.
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
            return self._sky_to_cloud_cover(value, LUX_CLEAR_SKY_COEFFICIENT, "lux")
        if unit in ("W/m²", "W/m2"):
            return self._sky_to_cloud_cover(
                value, IRRADIANCE_CLEAR_SKY_COEFFICIENT, "W/m²"
            )

        # Direct percentage input
        return max(CLOUD_COVER_MIN, min(CLOUD_COVER_MAX, value))

    def _get_temperature_celsius(self) -> float | None:
        """Return current air temperature (°C) from the configured sensor, or None."""
        entity_id = self.config_data.get(CONF_TEMPERATURE_ENTITY)
        if entity_id:
            state = self.hass.states.get(entity_id)
            if state and state.state not in ("unavailable", "unknown", "none"):
                with contextlib.suppress(ValueError, TypeError):
                    return float(state.state)
        return None

    def _get_current_pressure(self) -> float:
        """Return current barometric pressure (hPa); falls back to ISA sea-level value."""
        entity_id = self.config_data.get(CONF_PRESSURE_ENTITY)
        if entity_id:
            state = self.hass.states.get(entity_id)
            if state and state.state not in ("unavailable", "unknown", "none"):
                with contextlib.suppress(ValueError, TypeError):
                    return float(state.state)
        return 1013.25

    def _compute_vapor_pressure(self) -> float | None:
        """Compute actual vapor pressure e_a (hPa) from available moisture sensors.

        Priority:
        1. Dewpoint sensor (most accurate): e_a via Alduchov-Eskridge formula.
        2. Temperature + humidity: e_a = e_s(T) × (RH / 100).
        3. Humidity only: e_a = e_s(15 °C) × (RH / 100) — approximate.
        4. No sensor configured: returns None.
        """
        # Priority 1: dewpoint → direct e_a
        dew_entity = self.config_data.get(CONF_DEWPOINT_ENTITY)
        if dew_entity:
            dew_state = self.hass.states.get(dew_entity)
            if dew_state and dew_state.state not in ("unavailable", "unknown", "none"):
                td: float | None = None
                with contextlib.suppress(ValueError, TypeError):
                    td = float(dew_state.state)
                if td is not None:
                    return 6.112 * math.exp(17.67 * td / (td + 243.5))

        # Priority 2 & 3: humidity (with or without temperature)
        rh_entity = self.config_data.get(CONF_HUMIDITY_ENTITY)
        if not rh_entity:
            return None
        rh_state = self.hass.states.get(rh_entity)
        if not rh_state or rh_state.state in ("unavailable", "unknown", "none"):
            return None
        rh: float | None = None
        with contextlib.suppress(ValueError, TypeError):
            rh = float(rh_state.state)
        if rh is None:
            return None

        # Saturation vapor pressure at actual temperature (or 15 °C default)
        t_c = self._get_temperature_celsius() or 15.0
        e_s = 6.112 * math.exp(17.67 * t_c / (t_c + 243.5))
        return e_s * (rh / 100.0)

    def _linke_turbidity(self, pressure: float) -> float:
        """Estimate Linke turbidity TL from measurable atmospheric inputs.

        Uses the Kasten (1980) formula relating TL to precipitable water W
        and aerosol optical depth τ_a.  Precipitable water is derived from
        vapor pressure via the Garrison-Adler / Reitan (1963) expression.

        TL ranges from ~2 (clean, dry, high-altitude air) to ~8 (tropical,
        humid, polluted cities).  The EMA calibration factor in
        _sky_to_cloud_cover absorbs any residual between the estimated and
        actual TL — mainly the difference between DEFAULT_AOD_550NM and the
        true local aerosol load.
        """
        vapor_pressure = self._compute_vapor_pressure()
        if vapor_pressure is None or vapor_pressure <= 0:
            # No moisture sensor → use climatological default (moderate clean air)
            return 3.0

        # Precipitable water W (cm) via Reitan (1963) / pvlib formula.
        # Requires dewpoint Td, derived here from e_a via inverse Magnus.
        log_ea = math.log(vapor_pressure / 6.112)
        td_celsius = 243.5 * log_ea / (17.67 - log_ea)
        w_cm = max(0.1, math.exp(0.07 * td_celsius - 0.075))

        p_ratio = pressure / 1013.25
        tau_a = DEFAULT_AOD_550NM
        tl = (
            2.0
            + 0.54 * p_ratio
            + 0.376 * math.log(w_cm)
            + 3.91 * tau_a * math.exp(0.689 * p_ratio)
        )
        _LOGGER.debug(
            "Linke turbidity TL=%.2f (W=%.2f cm, e_a=%.1f hPa, P=%.0f hPa)",
            tl,
            w_cm,
            vapor_pressure,
            pressure,
        )
        return max(1.0, tl)

    def _sky_to_cloud_cover(
        self, value: float, coefficient: float, input_label: str
    ) -> float:
        """Convert solar illuminance (lx) or irradiance (W/m²) to cloud cover %.

        `coefficient` selects the unit path:
        - LUX_CLEAR_SKY_COEFFICIENT  → input is illuminance (lx)
        - IRRADIANCE_CLEAR_SKY_COEFFICIENT → input is irradiance (W/m²)

        `input_label` is used only for debug logging.

        Three-step pipeline:
        1. Ineichen-Perez (2002) clear-sky GHI — altitude (HA config elevation +
           measured pressure) and Linke turbidity (from precipitable water and
           aerosol baseline) are used for location-specific physical modelling.
        2. Auto-calibration — absorbs residual sensor offset / local AOD by
           learning from clear-sky external weather periods (EMA, α=0.15).
        3. Log-ratio cloud cover — ln(calibrated_clear_sky / measured) × 100.

        Falls back to external weather cloud cover during night/low-angle twilight.
        """
        sun_state = self.hass.states.get("sun.sun")
        if not sun_state:
            return 50.0

        elevation = sun_state.attributes.get("elevation", 0)
        if not isinstance(elevation, (int, float)):
            return 50.0

        if elevation <= 5:
            # Night or low-angle twilight: model unreliable near the horizon.
            # Use external weather cloud cover if available (state attribute
            # preferred; falls back to first hourly entry for integrations
            # like met.no that only include cloud_coverage in forecasts).
            if (ext_cloud := self._ext_cloud_cover()) is not None:
                return float(ext_cloud)
            return 50.0

        # Ineichen-Perez (2002) clear-sky model.
        # Replaces Kasten & Czeplak (1980) for better location-adaptability:
        # altitude (via HA config + measured pressure) and atmospheric moisture
        # (via Linke turbidity TL) are now physically modelled rather than
        # approximated with fixed European-climate coefficients.
        altitude_m = float(self.hass.config.elevation or 0)
        fh1 = math.exp(-altitude_m / 8000.0)  # altitude factor 1 (Rayleigh)
        fh2 = math.exp(-altitude_m / 1250.0)  # altitude factor 2 (aerosol)
        cg1 = 5.09e-5 * altitude_m + 0.868  # model constant 1
        cg2 = 3.92e-5 * altitude_m + 0.0387  # model constant 2

        cos_zenith = math.cos(math.radians(90.0 - elevation))
        sin_elev = math.sin(math.radians(elevation))

        # Earth-Sun distance correction: orbital eccentricity causes the
        # extraterrestrial irradiance to vary ±3.3% through the year
        # (perihelion ~Jan 3: +3.3%; aphelion ~Jul 4: −3.3%).  Spencer (1971)
        # approximation, accurate to ±0.01%.  Without this factor the model
        # over-predicts in winter and under-predicts in summer by up to 3.3%,
        # which the EMA calibration would otherwise have to absorb as a
        # seasonal drift.
        doy = dt_util.now().timetuple().tm_yday
        earth_sun_factor = 1.0 + 0.033 * math.cos(2.0 * math.pi * doy / 365.0)

        # Kasten & Young (1989) relative airmass, pressure-corrected for altitude.
        # Using measured barometric pressure makes the airmass accurate for any
        # altitude — high-altitude sites get correctly lower airmass values.
        pressure = self._get_current_pressure()
        airmass_rel = (1229 + (614 * sin_elev) ** 2) ** 0.5 - 614 * sin_elev
        airmass_abs = airmass_rel * (pressure / 1013.25)

        # Linke turbidity encapsulates all atmospheric extinction (Rayleigh,
        # water vapour, aerosols) into one parameter estimated from local
        # pressure and precipitable water derived from the moisture sensors.
        tl = self._linke_turbidity(pressure)

        # Ineichen-Perez GHI (W/m²) with Earth-Sun distance correction.
        ghi = (
            cg1
            * SOLAR_CONSTANT_WM2
            * earth_sun_factor
            * cos_zenith
            * math.exp(-cg2 * airmass_abs * (fh1 + fh2 * (tl - 1)))
            * math.exp(0.01 * airmass_abs**1.8)
        )

        # Convert GHI to the sensor's unit.  The luminous efficacy constant is
        # derived from the old Kasten & Czeplak lux/irradiance ratio so that
        # the EMA calibration factor does not reset on upgrade.
        if coefficient == LUX_CLEAR_SKY_COEFFICIENT:
            clear_sky = max(0.0, ghi * SOLAR_LUMINOUS_EFFICACY)
        else:
            clear_sky = max(0.0, ghi)

        if clear_sky <= 0:
            return 50.0

        # Step 2 — auto-calibrate with external weather ground truth.
        # TL estimates the bulk atmosphere, but site-specific offsets (dust,
        # smoke, sea-salt, sensor gain) remain.  When external weather reports
        # ≤5% cloud cover at elevation ≥ 15°, the ratio measured/model gives
        # the residual factor; EMA (α=0.15) updates the calibration gently.
        # Sanity bounds [0.4, 1.4] reject physically impossible readings.
        #
        # Use _ext_cloud_cover() (same best-available logic as the display path)
        # so that integrations like met.no — which only expose cloud coverage in
        # their hourly forecast, not in state attributes — can also drive
        # calibration.  Without this fallback current_cloud_cover would be None
        # for those integrations and calibration would never fire.
        ext_cloud_now = self._ext_cloud_cover()
        if (
            elevation >= 15.0
            and ext_cloud_now is not None
            and ext_cloud_now <= 5.0
        ):
            observed_factor = value / clear_sky
            if 0.4 <= observed_factor <= 1.4:
                alpha = 0.15
                self._sky_calibration_factor = (
                    1.0 - alpha
                ) * self._sky_calibration_factor + alpha * observed_factor
                self._calibration_dirty = True
                _LOGGER.debug(
                    "Sky calibration updated: factor=%.3f"
                    " (observed=%.3f, ext cloud=%.1f%%, elev=%.1f°)",
                    self._sky_calibration_factor,
                    observed_factor,
                    ext_cloud_now,
                    elevation,
                )

        # Step 3 — apply residual calibration and derive cloud cover.
        calibrated_clear_sky = clear_sky * self._sky_calibration_factor

        # Ratio > 1 means clouds are reducing measured value below clear-sky.
        ratio = calibrated_clear_sky / max(value, 0.001)
        cloud_cover = math.log(ratio) * 100.0
        _LOGGER.debug(
            "%s %.1f → GHI %.1f W/m² (E₀×%.4f) → clear_sky %.1f"
            " (TL=%.2f calib×%.3f) → cloud %.1f%%",
            input_label,
            value,
            ghi,
            earth_sun_factor,
            calibrated_clear_sky,
            tl,
            self._sky_calibration_factor,
            round(cloud_cover, 1),
        )
        cloud_cover = max(0.0, min(100.0, cloud_cover))

        # Cross-validate: when local lux indicates clear sky but external
        # weather reports heavy cloud or fog, flag the disagreement.
        # The calibration is already protected (only updates at ext cloud ≤ 5%),
        # so no correction is needed here — this is purely diagnostic.
        if (
            cloud_cover < 20.0
            and self._ext_weather_data is not None
            and self._ext_weather_data.current_cloud_cover is not None
            and self._ext_weather_data.current_cloud_cover > 60.0
        ):
            _LOGGER.debug(
                "Local lux indicates clear sky (%.0f%%) but external weather"
                " reports %.0f%% cloud cover — trusting local sensors",
                cloud_cover,
                self._ext_weather_data.current_cloud_cover,
            )
            self._ext_weather_disagreement = True
        else:
            self._ext_weather_disagreement = False

        return cloud_cover

    async def _async_load_calibration(self) -> None:
        """Load the persisted sky calibration factor from storage.

        If the user has set a manual initial calibration factor (via options)
        that differs from 1.0, it always takes precedence over the stored EMA
        value on startup — giving deterministic, predictable cloud cover from
        the first update.  The EMA still runs in-session and saves its refined
        value, so removing the manual option later hands control back to the
        storage-persisted EMA.
        """
        manual = self._initial_calib_factor
        if manual is not None and manual != 1.0 and 0.4 <= manual <= 1.4:
            self._sky_calibration_factor = manual
            _LOGGER.debug(
                "Sky calibration seeded from config option: %.3f (storage bypassed)",
                manual,
            )
            self._calibration_loaded = True
            return

        data = await self._store.async_load()
        if data is not None:
            factor = data.get("sky_calibration_factor")
            if isinstance(factor, float) and 0.4 <= factor <= 1.4:
                self._sky_calibration_factor = factor
                _LOGGER.debug(
                    "Sky calibration factor restored from storage: %.3f", factor
                )
        self._calibration_loaded = True

    async def _async_save_calibration(self) -> None:
        """Persist the sky calibration factor to storage."""
        await self._store.async_save(
            {"sky_calibration_factor": self._sky_calibration_factor}
        )

    def _calculate_reliability(self, sensor_data: dict[str, Any]) -> dict[str, Any]:
        """Calculate forecast reliability as a percentage (0-100).

        Reliability is based on how many critical input sensors are
        configured and providing valid data. Each sensor has a weight
        reflecting its importance to the Sager algorithm accuracy.
        Wind historic and pressure change now come from the recorder
        rather than user-configured helper sensors.

        Returns a dict with score and per-sensor status details.
        """
        # (config_key, label, weight) - entity-based checks sum to 60 pts
        critical_entities: list[tuple[str, str, int]] = [
            (CONF_PRESSURE_ENTITY, "pressure", 20),
            (CONF_WIND_DIR_ENTITY, "wind_direction", 15),
            (CONF_WIND_SPEED_ENTITY, "wind_speed", 10),
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

        # Recorder-computed fields: available once the integration has accumulated
        # ALGORITHM_WINDOW_HOURS of history (typically after the first 6h of use).
        if sensor_data.get("_wind_historic_from_recorder"):
            score += 20
            sensor_status["wind_historic"] = "ok"
        else:
            sensor_status["wind_historic"] = "no history yet"

        if sensor_data.get("_pressure_change_from_recorder"):
            score += 20
            sensor_status["pressure_change"] = "ok"
        else:
            sensor_status["pressure_change"] = "no history yet"

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
