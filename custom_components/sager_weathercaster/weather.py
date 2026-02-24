"""Sager Weathercaster Weather Platform."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.weather import (
    Forecast,
    SingleCoordinatorWeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.const import (
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_CLOUD_LEVEL,
    ATTR_CONFIDENCE,
    ATTR_PRESSURE_LEVEL,
    ATTR_PRESSURE_TREND,
    ATTR_SAGER_FORECAST,
    ATTR_WIND_TREND,
    ATTRIBUTION,
    CLOUD_LEVEL_CLEAR,
    CLOUD_LEVEL_MOSTLY_CLOUDY,
    CLOUD_LEVEL_OVERCAST,
    CLOUD_LEVEL_PARTLY_CLOUDY,
    CLOUD_LEVEL_RAINING,
    CONF_CLOUD_COVER_ENTITY,
    CONF_HUMIDITY_ENTITY,
    CONF_PRESSURE_ENTITY,
    CONF_RAINING_ENTITY,
    CONF_TEMPERATURE_ENTITY,
    CONF_WIND_DIR_ENTITY,
    CONF_WIND_SPEED_ENTITY,
    DOMAIN,
    FORECAST_CODES_COOLER,
    FORECAST_CODES_WARMER,
    FORECAST_CONDITIONS,
    FORECAST_EVOLUTION,
    MANUFACTURER,
    MODEL,
    PRECIPITATION_PROBABILITY,
    RAIN_THRESHOLD_HEAVY,
    RAIN_THRESHOLD_LIGHT,
    VERSION,
    WMO_TO_HA_CONDITION,
)
from .coordinator import SagerWeathercasterCoordinator
from .ha_weather import ExternalWeatherDailyEntry, ExternalWeatherHourlyEntry
from .wind_names import get_named_wind, get_named_wind_from_degrees

PARALLEL_UPDATES = 0

if TYPE_CHECKING:
    from . import SagerConfigEntry

_LOGGER = logging.getLogger(__name__)

# Cloud cover % implied by each Sager cloud level string
_CLOUD_LEVEL_TO_PERCENT: dict[str, float] = {
    CLOUD_LEVEL_CLEAR: 10.0,
    CLOUD_LEVEL_PARTLY_CLOUDY: 30.0,
    CLOUD_LEVEL_MOSTLY_CLOUDY: 60.0,
    CLOUD_LEVEL_OVERCAST: 85.0,
    CLOUD_LEVEL_RAINING: 95.0,
}

# Cloud cover % implied by HA condition string
_CONDITION_TO_CLOUD: dict[str, float] = {
    "sunny": 10.0,
    "clear-night": 5.0,
    "partlycloudy": 45.0,
    "cloudy": 75.0,
    "rainy": 85.0,
    "pouring": 90.0,
    "snowy": 80.0,
    "lightning": 90.0,
    "lightning-rainy": 90.0,
    "fog": 90.0,
}

# Relative humidity % implied by HA condition string
_CONDITION_TO_HUMIDITY: dict[str, float] = {
    "sunny": 40.0,
    "clear-night": 45.0,
    "partlycloudy": 55.0,
    "cloudy": 65.0,
    "rainy": 80.0,
    "pouring": 90.0,
    "snowy": 75.0,
    "lightning": 80.0,
    "lightning-rainy": 85.0,
    "fog": 95.0,
}

# Target wind speed (km/h) for Beaufort-level Sager velocity keys.
# None means the key is relative (percentage change from current reading).
_WIND_VELOCITY_TARGET: dict[str, float | None] = {
    "probably_increasing": None,  # increase 50% over 24h (relative)
    "moderate_to_fresh": 30.0,  # Beaufort 4-5 midpoint
    "fresh_to_strong": 45.0,  # Beaufort 5-6 midpoint
    "gale": 65.0,  # Beaufort 7-8 midpoint
    "storm_to_hurricane": 90.0,  # Beaufort 9-10
    "hurricane": 130.0,  # Beaufort 12+
    "decreasing_or_moderate": None,  # decrease 50% over 24h (relative)
    "no_significant_change": None,  # stay near current (relative)
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SagerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Sager Weathercaster weather entity."""
    coordinator = entry.runtime_data
    async_add_entities([SagerWeatherEntity(coordinator, entry)])


class SagerWeatherEntity(
    SingleCoordinatorWeatherEntity[SagerWeathercasterCoordinator],
):
    """Sager Weathercaster Forecast Entity."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_DAILY | WeatherEntityFeature.FORECAST_HOURLY
    )
    _attr_translation_key = "sager_weather"

    def __init__(
        self,
        coordinator: SagerWeathercasterCoordinator,
        entry: SagerConfigEntry,
    ) -> None:
        """Initialize the weather entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_weather"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=VERSION,
        )
        self.config_data = entry.data

    @property
    def attribution(self) -> str | None:
        """Return data attribution; credits the external weather entity when live."""
        if self.coordinator.data:
            ext = self.coordinator.data.get("ext_weather", {})
            if ext.get("available"):
                src = ext.get("attribution") or "external weather entity"
                return (
                    f"Sager Weathercaster forecast, enhanced by {src}"
                )
        return ATTRIBUTION

    @property
    def condition(self) -> str | None:
        """Return current condition based on sensor data."""
        rain_entity = self.config_data.get(CONF_RAINING_ENTITY)
        cloud_entity = self.config_data.get(CONF_CLOUD_COVER_ENTITY)

        # Check rain sensor first
        is_raining = False
        is_pouring = False
        if rain_entity:
            rain_state = self.hass.states.get(rain_entity)
            if rain_state and rain_state.state not in ("unavailable", "unknown"):
                try:
                    rain_rate = float(rain_state.state)
                    if rain_rate > RAIN_THRESHOLD_HEAVY:
                        is_pouring = True
                    elif rain_rate > RAIN_THRESHOLD_LIGHT:
                        is_raining = True
                except ValueError:
                    is_raining = rain_state.state in ("on", "true", "True", "1")
                except TypeError:
                    is_raining = rain_state.state in ("on", "true", "True", "1")

        if is_pouring:
            return "pouring"
        if is_raining:
            return "rainy"

        # Use coordinator's computed cloud cover (handles lux conversion)
        cloud_cover: float | None = None
        if self.coordinator.data:
            sensor_data = self.coordinator.data.get("sensor_data", {})
            cloud_cover = sensor_data.get("cloud_cover")

        # Fallback: read cloud entity directly for % sensors
        if cloud_cover is None and cloud_entity:
            cloud_state = self.hass.states.get(cloud_entity)
            if cloud_state and cloud_state.state not in ("unavailable", "unknown"):
                with contextlib.suppress(ValueError, TypeError):
                    cloud_cover = float(cloud_state.state)

        # Fallback: external weather entity current cloud cover
        if cloud_cover is None and self.coordinator.data:
            ext = self.coordinator.data.get("ext_weather", {})
            if ext.get("available"):
                hourly = ext.get("hourly", [])
                if hourly:
                    cloud_cover = hourly[0].cloud_cover

        if cloud_cover is not None:
            if cloud_cover > 85:
                return "cloudy"
            if cloud_cover > 50:
                return "partlycloudy"
            if cloud_cover < 20:
                return "clear-night" if self._is_night() else "sunny"
            return "partlycloudy"

        return "cloudy"

    @property
    def native_temperature(self) -> float | None:
        """Return current temperature."""
        return self._get_sensor_float(CONF_TEMPERATURE_ENTITY)

    @property
    def humidity(self) -> float | None:
        """Return current humidity."""
        return self._get_sensor_float(CONF_HUMIDITY_ENTITY)

    @property
    def native_pressure(self) -> float | None:
        """Return current pressure."""
        return self._get_sensor_float(CONF_PRESSURE_ENTITY)

    @property
    def native_wind_speed(self) -> float | None:
        """Return current wind speed."""
        return self._get_sensor_float(CONF_WIND_SPEED_ENTITY)

    @property
    def wind_bearing(self) -> float | str | None:
        """Return current wind bearing."""
        return self._get_sensor_float(CONF_WIND_DIR_ENTITY)

    def _get_sensor_float(self, config_key: str) -> float | None:
        """Get a float value from a configured sensor entity."""
        entity_id = self.config_data.get(config_key)
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state and state.state not in ("unavailable", "unknown"):
            with contextlib.suppress(ValueError, TypeError):
                return float(state.state)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional Sager-specific attributes."""
        if not self.coordinator.data:
            return {}

        forecast = self.coordinator.data.get("forecast", {})
        zambretti = self.coordinator.data.get("zambretti", {})
        ext_weather = self.coordinator.data.get("ext_weather", {})

        attrs: dict[str, Any] = {
            ATTR_SAGER_FORECAST: forecast.get("forecast_code"),
            ATTR_PRESSURE_LEVEL: forecast.get("hpa_level"),
            ATTR_WIND_TREND: forecast.get("wind_trend"),
            ATTR_PRESSURE_TREND: forecast.get("pressure_trend"),
            ATTR_CLOUD_LEVEL: forecast.get("cloud_level"),
            ATTR_CONFIDENCE: forecast.get("confidence"),
            "wind_velocity": forecast.get("wind_velocity_key"),
            "wind_direction": forecast.get("wind_direction_key"),
            "latitude_zone": forecast.get("latitude_zone"),
            "cross_validation": forecast.get("cross_validation"),
            "zambretti_condition": forecast.get("zambretti_condition"),
            "zambretti_forecast": zambretti.get("zambretti_key"),
            "external_weather_available": ext_weather.get("available", False),
        }

        # Named wind — current and forecast
        lat = self.coordinator.hass.config.latitude
        lon = self.coordinator.hass.config.longitude
        sensor_data = self.coordinator.data.get("sensor_data", {})
        wind_deg = sensor_data.get("wind_direction")
        if wind_deg is not None:
            attrs["current_wind_name"] = get_named_wind_from_degrees(lat, lon, wind_deg)
        forecast_wind_dir = forecast.get("wind_dir")
        if forecast_wind_dir:
            attrs["forecast_wind_name"] = get_named_wind(lat, lon, forecast_wind_dir)

        # Cross-check Sager day-1 condition vs external weather day-1 for transparency
        if ext_weather.get("available"):
            api_daily: list[ExternalWeatherDailyEntry] = ext_weather.get("daily", [])
            if api_daily:
                sager_cond = FORECAST_CONDITIONS.get(
                    forecast.get("forecast_code", "d"), "partlycloudy"
                )
                ext_cond = (
                    api_daily[0].condition
                    or _wmo_to_condition(api_daily[0].weather_code)
                    or "partlycloudy"
                )
                attrs["external_weather_day1_agreement"] = (
                    "agree" if sager_cond == ext_cond else "differ"
                )
                attrs["external_weather_day1_condition"] = ext_cond

        return attrs

    @callback
    def _async_forecast_daily(self) -> list[Forecast] | None:
        """Return the daily forecast in native units."""
        if not self.coordinator.data:
            return None

        forecast = self.coordinator.data.get("forecast", {})
        ext_weather = self.coordinator.data.get("ext_weather", {})
        try:
            return self._generate_daily_forecast(forecast, ext_weather)
        except Exception:
            _LOGGER.exception("Error generating daily forecast")
            return None

    @callback
    def _async_forecast_hourly(self) -> list[Forecast] | None:
        """Return hourly forecast: Sager-primary for 48h, extended by external weather.

        Step 1: Always build a Sager-derived 48h baseline (condition from Sager
        codes, numerical values from current sensors extrapolated by Sager signals).
        Step 2: When external weather data is available, overlay its numerical values
        on the Sager baseline (keeping Sager conditions) and extend beyond 48h.
        """
        if not self.coordinator.data:
            return None

        forecast = self.coordinator.data.get("forecast", {})
        sensor_data = self.coordinator.data.get("sensor_data", {})
        ext_weather = self.coordinator.data.get("ext_weather", {})

        # Step 1: Sager-primary 48h baseline (always available)
        try:
            sager_hourly = self._generate_sager_hourly_forecast(forecast, sensor_data)
        except Exception:
            _LOGGER.exception("Error generating Sager hourly baseline")
            sager_hourly = []

        if not ext_weather.get("available") or not ext_weather.get("hourly"):
            return sager_hourly if len(sager_hourly) >= 3 else None

        # Step 2: enrich with external weather numerical data and extend beyond 48h
        try:
            enriched = self._enrich_hourly_with_ext_weather(sager_hourly, ext_weather)
            return (
                enriched
                if len(enriched) >= 3
                else (sager_hourly if len(sager_hourly) >= 3 else None)
            )
        except Exception:
            _LOGGER.exception("Error enriching hourly with external weather data")
            return sager_hourly if len(sager_hourly) >= 3 else None

    def _generate_daily_forecast(
        self,
        sager_result: dict[str, Any],
        ext_weather: dict[str, Any],
    ) -> list[Forecast]:
        """Generate 7-day daily forecast with Sager-primary conditions.

        Days 1-2: Sager/Zambretti condition (authoritative) + external weather
                  temperature (more accurate than sensor ± trend estimate).
        Day 3:    Blended condition (40% Sager, 60% external weather).
        Days 4-7: Pure external weather.
        Fallback:  3-day Sager-only if no external weather entity is configured.
        """
        now = dt_util.utcnow()
        base_temp = self.native_temperature or 15.0
        forecast_code = sager_result.get("forecast_code", "d")

        # Day 1 condition and precipitation probability
        condition_p1 = FORECAST_CONDITIONS.get(forecast_code, "partlycloudy")
        precip_p1 = PRECIPITATION_PROBABILITY.get(condition_p1, 15)

        # Temperature trend from Sager code semantics
        temp_change = 0.0
        if forecast_code in FORECAST_CODES_WARMER:
            temp_change = 3.0
        elif forecast_code in FORECAST_CODES_COOLER:
            temp_change = -3.0

        # Day 2: evolved condition encoded in the forecast code meaning
        if forecast_code in FORECAST_EVOLUTION:
            condition_p2, precip_p2 = FORECAST_EVOLUTION[forecast_code]
        else:
            condition_p2 = condition_p1
            precip_p2 = max(precip_p1 * 0.7, 0)

        # External weather daily entries (empty list when unavailable)
        api_daily: list[ExternalWeatherDailyEntry] = (
            ext_weather.get("daily", []) if ext_weather.get("available") else []
        )

        # Build days 1-2: Sager condition + external weather temperature (when available)
        forecasts: list[Forecast] = []
        sager_days = [
            (condition_p1, int(precip_p1), 0.0),
            (condition_p2, int(precip_p2), temp_change),
        ]

        for day_offset, (condition, precip, temp_delta) in enumerate(sager_days):
            forecast_day = (now + timedelta(days=day_offset)).replace(microsecond=0)

            # Prefer external weather temperature (numerical model, more precise than
            # current sensor ± trend estimate)
            api_day = api_daily[day_offset] if day_offset < len(api_daily) else None
            if api_day is not None and api_day.temperature_max is not None:
                temp_high = round(api_day.temperature_max, 1)
                temp_low = (
                    round(api_day.temperature_min, 1)
                    if api_day.temperature_min is not None
                    else round(api_day.temperature_max - 5.0, 1)
                )
            else:
                temp_high = round(base_temp + temp_delta, 1)
                temp_low = round(base_temp + temp_delta - 5.0, 1)

            forecasts.append(
                Forecast(
                    datetime=forecast_day.isoformat(),
                    condition=condition,  # Sager is authoritative for days 1-2
                    native_temperature=temp_high,
                    native_templow=temp_low,
                    precipitation_probability=precip,
                )
            )

        # Days 3-7: blend or extend with external weather
        has_api = len(api_daily) >= 3

        if has_api:
            # Day 3: Sager-extrapolated condition blended with external weather
            sager_condition_p3 = condition_p2
            sager_precip_p3 = max(int(precip_p2 * 0.6), 0)

            api_day3 = api_daily[2] if len(api_daily) > 2 else None
            if api_day3 is not None:
                api_condition = api_day3.condition or _wmo_to_condition(api_day3.weather_code)
                # Blend condition: 40% Sager continuity, 60% external weather
                blended_condition = api_condition or sager_condition_p3

                temp_high = (
                    round(api_day3.temperature_max, 1)
                    if api_day3.temperature_max is not None
                    else round(base_temp + temp_change * 0.7, 1)
                )
                temp_low = (
                    round(api_day3.temperature_min, 1)
                    if api_day3.temperature_min is not None
                    else round(temp_high - 5.0, 1)
                )
                blended_precip = (
                    int(
                        sager_precip_p3 * 0.4
                        + api_day3.precipitation_probability_max * 0.6
                    )
                    if api_day3.precipitation_probability_max is not None
                    else sager_precip_p3
                )

                forecast_day = (now + timedelta(days=2)).replace(microsecond=0)
                forecasts.append(
                    Forecast(
                        datetime=forecast_day.isoformat(),
                        condition=blended_condition,
                        native_temperature=temp_high,
                        native_templow=temp_low,
                        precipitation_probability=blended_precip,
                    )
                )
            else:
                # Fallback: Sager-only day 3
                forecast_day = (now + timedelta(days=2)).replace(microsecond=0)
                forecasts.append(
                    Forecast(
                        datetime=forecast_day.isoformat(),
                        condition=sager_condition_p3,
                        native_temperature=round(base_temp + temp_change * 0.7, 1),
                        native_templow=round(base_temp + temp_change * 0.7 - 5.0, 1),
                        precipitation_probability=sager_precip_p3,
                    )
                )

            # Days 4-7: pure external weather
            for day_offset in range(3, min(len(api_daily), 7)):
                api_day = api_daily[day_offset]
                forecast_day = (now + timedelta(days=day_offset)).replace(microsecond=0)
                condition = (
                    api_day.condition
                    or _wmo_to_condition(api_day.weather_code)
                    or "partlycloudy"
                )
                forecasts.append(
                    Forecast(
                        datetime=forecast_day.isoformat(),
                        condition=condition,
                        native_temperature=(
                            round(api_day.temperature_max, 1)
                            if api_day.temperature_max is not None
                            else round(base_temp, 1)
                        ),
                        native_templow=(
                            round(api_day.temperature_min, 1)
                            if api_day.temperature_min is not None
                            else round(base_temp - 5.0, 1)
                        ),
                        precipitation_probability=(
                            api_day.precipitation_probability_max
                            if api_day.precipitation_probability_max is not None
                            else 0
                        ),
                        native_precipitation=(
                            round(api_day.precipitation_sum, 1)
                            if api_day.precipitation_sum is not None
                            else None
                        ),
                        wind_bearing=(
                            api_day.wind_direction_dominant
                            if api_day.wind_direction_dominant is not None
                            else None
                        ),
                        native_wind_speed=(
                            round(api_day.wind_speed_max, 1)
                            if api_day.wind_speed_max is not None
                            else None
                        ),
                    )
                )
        else:
            # No external weather: Sager-only day 3 (minimum required by HA frontend)
            condition_p3 = condition_p2
            precip_p3 = max(int(precip_p2 * 0.6), 0)
            forecast_day = (now + timedelta(days=2)).replace(microsecond=0)
            forecasts.append(
                Forecast(
                    datetime=forecast_day.isoformat(),
                    condition=condition_p3,
                    native_temperature=round(base_temp + temp_change * 0.7, 1),
                    native_templow=round(base_temp + temp_change * 0.7 - 5.0, 1),
                    precipitation_probability=precip_p3,
                )
            )

        return forecasts

    def _generate_sager_hourly_forecast(
        self,
        sager_result: dict[str, Any],
        sensor_data: dict[str, Any],
    ) -> list[Forecast]:
        """Generate Sager-primary hourly forecast for the next 48 hours.

        Condition: Sager day-1 code for hours 0-24, day-2 evolved code for
        hours 24-48 (time-of-day adjusted for sunny/clear-night).
        Temperature: current sensor value with linear trend toward day-2 target
        and a ±3°C diurnal curve peaking at 14:00.
        Wind speed: extrapolated from current sensor reading by Sager's
        wind_velocity_key (Beaufort-level or relative trend).
        Wind direction: held at current sensor value (slowly changing).
        Cloud cover: transitions from current reading to Sager cloud_level %, then
        to day-2 condition-implied % at hour 24.
        Humidity: same transition pattern, from current to condition-implied %.
        """
        now = dt_util.utcnow()

        # Sager condition codes for the two 24h periods
        forecast_code = sager_result.get("forecast_code", "d")
        condition_p1 = FORECAST_CONDITIONS.get(forecast_code, "partlycloudy")
        precip_p1 = PRECIPITATION_PROBABILITY.get(condition_p1, 15.0)

        temp_change = 0.0
        if forecast_code in FORECAST_CODES_WARMER:
            temp_change = 3.0
        elif forecast_code in FORECAST_CODES_COOLER:
            temp_change = -3.0

        if forecast_code in FORECAST_EVOLUTION:
            condition_p2, precip_p2 = FORECAST_EVOLUTION[forecast_code]
        else:
            condition_p2 = condition_p1
            precip_p2 = max(precip_p1 * 0.7, 0)

        # Current readings from coordinator sensor_data (already validated/processed)
        base_temp: float = (
            sensor_data.get("temperature") or self.native_temperature or 15.0
        )
        current_wind: float = (
            sensor_data.get("wind_speed") or self.native_wind_speed or 0.0
        )
        current_wind_dir: float = (
            sensor_data.get("wind_direction") or self.wind_bearing or 0.0
        )
        current_cloud: float = sensor_data.get("cloud_cover") or 0.0
        current_humidity: float | None = self._get_sensor_float(CONF_HUMIDITY_ENTITY)

        # Sager signals for extrapolation
        wind_velocity_key: str = sager_result.get(
            "wind_velocity_key", "no_significant_change"
        )

        # Target cloud cover per period
        cloud_level_str: str = sager_result.get("cloud_level", "Partly Cloudy")
        target_cloud_p1 = _CLOUD_LEVEL_TO_PERCENT.get(cloud_level_str, 50.0)
        target_cloud_p2 = _CONDITION_TO_CLOUD.get(condition_p2, 50.0)

        # Target humidity per period
        target_humidity_p1 = _CONDITION_TO_HUMIDITY.get(condition_p1, 60.0)
        target_humidity_p2 = _CONDITION_TO_HUMIDITY.get(condition_p2, 60.0)

        start = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        forecasts: list[Forecast] = []

        for i in range(48):
            slot_dt = start + timedelta(hours=i)
            local_hour = slot_dt.hour

            # Which Sager period governs this hour
            if i < 24:
                condition = condition_p1
                precip = int(precip_p1)
            else:
                condition = condition_p2
                precip = int(precip_p2)

            # Temperature: linear approach to day-2 target across 48h + diurnal curve
            # (Sager day-1 target = base_temp, day-2 target = base_temp + temp_change)
            mean_temp = base_temp + temp_change * (i / 48.0)
            hours_from_peak = abs(local_hour - 14)
            if hours_from_peak > 12:
                hours_from_peak = 24 - hours_from_peak
            diurnal = 3.0 * (1.0 - hours_from_peak / 6.0)
            hourly_temp = round(mean_temp + diurnal, 1)

            # Cloud cover: transition from current → p1 target over 12h, then
            # smoothly transition to p2 target starting at hour 24
            if i < 12:
                cloud = current_cloud + (target_cloud_p1 - current_cloud) * (i / 12.0)
            elif i < 24:
                cloud = target_cloud_p1
            elif i < 36:
                cloud = target_cloud_p1 + (target_cloud_p2 - target_cloud_p1) * (
                    (i - 24) / 12.0
                )
            else:
                cloud = target_cloud_p2
            cloud = round(max(0.0, min(100.0, cloud)), 1)

            # Humidity: same transition pattern as cloud
            if current_humidity is not None:
                if i < 12:
                    hum = current_humidity + (target_humidity_p1 - current_humidity) * (
                        i / 12.0
                    )
                elif i < 24:
                    hum = target_humidity_p1
                elif i < 36:
                    hum = target_humidity_p1 + (
                        target_humidity_p2 - target_humidity_p1
                    ) * ((i - 24) / 12.0)
                else:
                    hum = target_humidity_p2
            else:
                hum = target_humidity_p1 if i < 24 else target_humidity_p2

            # Wind speed: extrapolated from current by Sager velocity key
            wind_speed = _extrapolate_wind(current_wind, wind_velocity_key, i)

            # Day/night condition adjustment
            is_day_slot = 6 <= local_hour <= 20
            slot_condition = condition
            if slot_condition == "sunny" and not is_day_slot:
                slot_condition = "clear-night"

            slot: Forecast = Forecast(
                datetime=slot_dt.isoformat(),
                condition=slot_condition,
            )
            slot["native_temperature"] = hourly_temp
            slot["precipitation_probability"] = precip
            slot["native_wind_speed"] = wind_speed
            slot["wind_bearing"] = current_wind_dir
            slot["cloud_coverage"] = cloud
            slot["humidity"] = round(hum)
            forecasts.append(slot)

        return forecasts

    def _enrich_hourly_with_ext_weather(
        self,
        sager_hourly: list[Forecast],
        ext_weather: dict[str, Any],
    ) -> list[Forecast]:
        """Enrich Sager hourly with external weather data and extend beyond 48h.

        For hours 0-48h (Sager window):
          - Condition: Sager (primary, kept as-is)
          - Temperature, wind, cloud, humidity, dew point, UV, apparent
            temperature: external weather values preferred (numerical model accuracy)
          - Falls back to Sager-derived values when no matching entry.

        For hours beyond 48h:
          - Condition: external weather condition string (Sager data exhausted)
          - All values: external weather
        """
        ext_hourly: list[ExternalWeatherHourlyEntry] = ext_weather.get("hourly", [])

        # Build hour-truncated UTC key → external weather entry lookup
        ext_lookup: dict[str, ExternalWeatherHourlyEntry] = {}
        for entry in ext_hourly:
            entry_dt = _parse_api_datetime(entry.datetime)
            if entry_dt is not None:
                key = entry_dt.replace(minute=0, second=0, microsecond=0).isoformat()
                ext_lookup[key] = entry

        sager_latest_dt: datetime | None = None
        enriched: list[Forecast] = []

        # Step 1: enrich Sager 0-48h with external weather numerical data
        for slot in sager_hourly:
            slot_dt = _parse_slot_datetime(slot)
            if slot_dt is None:
                enriched.append(slot)
                continue

            sager_latest_dt = slot_dt
            key = slot_dt.replace(minute=0, second=0, microsecond=0).isoformat()
            ext = ext_lookup.get(key)

            if ext is None:
                enriched.append(slot)
                continue

            enriched.append(_enrich_sager_slot(slot, ext))

        # Step 2: extend beyond Sager 48h window with external weather
        now = dt_util.utcnow()
        for entry in ext_hourly:
            entry_dt = _parse_api_datetime(entry.datetime)
            if entry_dt is None:
                continue
            if sager_latest_dt is not None and entry_dt <= sager_latest_dt:
                continue
            if entry_dt < now:
                continue
            if entry_dt > now + timedelta(hours=168):  # cap at 7 days
                break

            enriched.append(_build_extended_slot(entry, entry_dt))

        return enriched

    def _is_night(self) -> bool:
        """Return True when the sun is below the horizon.

        Uses the ``sun.sun`` entity state for accuracy (respects actual
        sunrise/sunset regardless of season and latitude).  Falls back to a
        simple hour-based heuristic when the entity is unavailable.
        """
        sun_state = self.hass.states.get("sun.sun")
        if sun_state:
            return sun_state.state == "below_horizon"
        now = dt_util.now()
        return now.hour < 6 or now.hour >= 21


def _wmo_to_condition(weather_code: int | None) -> str | None:
    """Convert WMO weather code to HA condition string."""
    if weather_code is None:
        return None
    return WMO_TO_HA_CONDITION.get(weather_code, "partlycloudy")


def _parse_api_datetime(dt_str: str) -> datetime | None:
    """Parse an external weather API datetime string to a timezone-aware datetime."""
    try:
        dt_obj = datetime.fromisoformat(dt_str)
    except ValueError:
        return None
    except TypeError:
        return None

    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=UTC)
    return dt_obj


def _parse_slot_datetime(slot: Forecast) -> datetime | None:
    """Parse the datetime key from a Sager forecast slot to a timezone-aware datetime."""
    try:
        dt = datetime.fromisoformat(slot["datetime"])
    except KeyError:
        return None
    except ValueError:
        return None
    except TypeError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _enrich_sager_slot(slot: Forecast, ext: ExternalWeatherHourlyEntry) -> Forecast:
    """Build an enriched slot keeping Sager condition and preferring external weather data."""
    new_slot: Forecast = Forecast(
        datetime=slot["datetime"],
        condition=slot.get("condition"),  # Sager is authoritative 0-48h
    )
    # Temperature: external weather numerical model is more accurate than sensor extrapolation
    new_slot["native_temperature"] = (
        round(ext.temperature, 1)
        if ext.temperature is not None
        else slot.get("native_temperature")
    )
    # Precipitation probability: external weather is more granular than condition-based estimate
    new_slot["precipitation_probability"] = (
        ext.precipitation_probability
        if ext.precipitation_probability is not None
        else slot.get("precipitation_probability")
    )
    if ext.precipitation is not None:
        new_slot["native_precipitation"] = round(ext.precipitation, 1)
    # Wind: external weather has measured/modeled values per hour
    new_slot["native_wind_speed"] = (
        round(ext.wind_speed, 1)
        if ext.wind_speed is not None
        else slot.get("native_wind_speed")
    )
    new_slot["wind_bearing"] = (
        ext.wind_direction
        if ext.wind_direction is not None
        else slot.get("wind_bearing")
    )
    new_slot["cloud_coverage"] = (
        ext.cloud_cover if ext.cloud_cover is not None else slot.get("cloud_coverage")
    )
    new_slot["humidity"] = (
        ext.humidity if ext.humidity is not None else slot.get("humidity")
    )
    # Additional fields from external weather not available from Sager
    if ext.uv_index is not None:
        new_slot["uv_index"] = round(ext.uv_index, 1)
    if ext.apparent_temperature is not None:
        new_slot["native_apparent_temperature"] = round(ext.apparent_temperature, 1)
    if ext.dew_point is not None:
        new_slot["native_dew_point"] = round(ext.dew_point, 1)
    return new_slot


def _build_extended_slot(entry: ExternalWeatherHourlyEntry, entry_dt: datetime) -> Forecast:
    """Build a forecast slot from external weather data for hours beyond the Sager window."""
    condition = entry.condition or _wmo_to_condition(entry.weather_code)
    if condition == "sunny" and entry.is_day is False:
        condition = "clear-night"
    ext: Forecast = Forecast(
        datetime=entry_dt.isoformat(),
        condition=condition or "partlycloudy",
    )
    if entry.temperature is not None:
        ext["native_temperature"] = round(entry.temperature, 1)
    if entry.precipitation_probability is not None:
        ext["precipitation_probability"] = entry.precipitation_probability
    if entry.precipitation is not None:
        ext["native_precipitation"] = round(entry.precipitation, 1)
    if entry.wind_speed is not None:
        ext["native_wind_speed"] = round(entry.wind_speed, 1)
    if entry.wind_direction is not None:
        ext["wind_bearing"] = entry.wind_direction
    if entry.humidity is not None:
        ext["humidity"] = entry.humidity
    if entry.cloud_cover is not None:
        ext["cloud_coverage"] = entry.cloud_cover
    if entry.uv_index is not None:
        ext["uv_index"] = round(entry.uv_index, 1)
    if entry.apparent_temperature is not None:
        ext["native_apparent_temperature"] = round(entry.apparent_temperature, 1)
    if entry.dew_point is not None:
        ext["native_dew_point"] = round(entry.dew_point, 1)
    return ext


def _extrapolate_wind(
    current_speed: float, velocity_key: str, hours_ahead: int
) -> float:
    """Extrapolate hourly wind speed from Sager's wind velocity forecast.

    Relative keys (increasing/decreasing/no_change) apply percentage change
    from the current reading. Beaufort-level keys (moderate_to_fresh, gale,
    etc.) gradually lerp toward the target midpoint speed over 24h.
    """
    progress = min(hours_ahead / 24.0, 1.0)

    if velocity_key == "probably_increasing":
        # Ramp up to 50% above current over 24h
        return round(max(current_speed * (1.0 + 0.5 * progress), 0.0), 1)

    if velocity_key == "decreasing_or_moderate":
        # Ramp down to 50% of current over 24h
        return round(max(current_speed * (1.0 - 0.5 * progress), 0.0), 1)

    if velocity_key == "no_significant_change":
        return round(max(current_speed, 0.0), 1)

    # Beaufort absolute-level key: lerp at most 70% of the way to target in 24h
    target = _WIND_VELOCITY_TARGET.get(velocity_key) or current_speed
    lerp = progress * 0.7
    return round(max(current_speed + (target - current_speed) * lerp, 0.0), 1)
