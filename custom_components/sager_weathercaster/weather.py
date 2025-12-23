"""Sager Weathercaster Weather Platform."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.weather import (
    PLATFORM_SCHEMA as WEATHER_PLATFORM_SCHEMA,
    Forecast,
    WeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.const import (
    CONF_NAME,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_ATTRIBUTION,
    ATTR_CLOUD_LEVEL,
    ATTR_CONFIDENCE,
    ATTR_PRESSURE_LEVEL,
    ATTR_PRESSURE_TREND,
    ATTR_SAGER_FORECAST,
    ATTR_WIND_TREND,
    ATTRIBUTION,
    CONF_CLOUD_COVER_ENTITY,
    CONF_CONDITION_ENTITY,
    CONF_HUMIDITY_ENTITY,
    CONF_PRESSURE_CHANGE_ENTITY,
    CONF_PRESSURE_ENTITY,
    CONF_RAINING_ENTITY,
    CONF_TEMPERATURE_ENTITY,
    CONF_WIND_DIR_ENTITY,
    CONF_WIND_HISTORIC_ENTITY,
    CONF_WIND_SPEED_ENTITY,
    DEFAULT_NAME,
    DOMAIN,
    MANUFACTURER,
    MODEL,
    NAME,
    VERSION,
)

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = WEATHER_PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Optional(CONF_PRESSURE_ENTITY): cv.entity_id,
        vol.Optional(CONF_TEMPERATURE_ENTITY): cv.entity_id,
        vol.Optional(CONF_HUMIDITY_ENTITY): cv.entity_id,
        vol.Optional(CONF_WIND_DIR_ENTITY): cv.entity_id,
        vol.Optional(CONF_WIND_SPEED_ENTITY): cv.entity_id,
        vol.Optional(CONF_WIND_HISTORIC_ENTITY): cv.entity_id,
        vol.Optional(CONF_PRESSURE_CHANGE_ENTITY): cv.entity_id,
        vol.Optional(CONF_CLOUD_COVER_ENTITY): cv.entity_id,
        vol.Optional(CONF_RAINING_ENTITY): cv.entity_id,
        vol.Optional(CONF_CONDITION_ENTITY): cv.entity_id,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Sager Weathercaster weather entity."""
    # Handle discovery vs direct config
    if discovery_info is not None:
        conf = discovery_info
    else:
        conf = config

    name = conf.get(CONF_NAME, DEFAULT_NAME)

    _LOGGER.debug(f"Setting up Sager weather entity '{name}'")

    async_add_entities([SagerWeatherEntity(hass, name, conf)], True)


class SagerWeatherEntity(WeatherEntity):
    """Sager Weathercaster Forecast Entity."""

    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_supported_features = WeatherEntityFeature.FORECAST_DAILY
    _attr_should_poll = True

    def __init__(
        self, hass: HomeAssistant, name: str | None, config: ConfigType
    ) -> None:
        """Initialize the weather entity."""
        self._hass = hass

        # Handle None name
        if name is None:
            name = DEFAULT_NAME

        self._attr_name = f"{name}"
        self._attr_unique_id = f"sager_weather_{name.lower().replace(' ', '_')}"
        self._config = config

        # Current conditions
        self._attr_native_temperature: float | None = None
        self._attr_humidity: float | None = None
        self._attr_native_pressure: float | None = None
        self._attr_native_wind_speed: float | None = None
        self._attr_wind_bearing: float | None = None
        self._attr_condition: str = "cloudy"

        # Sager forecast
        self._sager_forecast_text: str = "Initializing..."
        self._sager_attributes: dict[str, Any] = {}
        self._forecast_data: list[Forecast] = []

        _LOGGER.debug(f"Initialized Sager weather entity: {self._attr_name}")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional Sager-specific attributes."""
        return {
            ATTR_SAGER_FORECAST: self._sager_forecast_text,
            ATTR_PRESSURE_LEVEL: self._sager_attributes.get(ATTR_PRESSURE_LEVEL),
            ATTR_WIND_TREND: self._sager_attributes.get(ATTR_WIND_TREND),
            ATTR_PRESSURE_TREND: self._sager_attributes.get(ATTR_PRESSURE_TREND),
            ATTR_CLOUD_LEVEL: self._sager_attributes.get(ATTR_CLOUD_LEVEL),
            ATTR_CONFIDENCE: self._sager_attributes.get(ATTR_CONFIDENCE),
            ATTR_ATTRIBUTION: ATTRIBUTION,
        }

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

    async def async_forecast_daily(self) -> list[Forecast]:
        """Return the daily forecast."""
        return self._forecast_data

    async def async_update(self) -> None:
        """Update weather data."""
        await self._hass.async_add_executor_job(self.update)

    def update(self) -> None:
        """Fetch new state data."""
        try:
            # Get current conditions
            self._update_current_conditions()

            # Calculate Sager forecast
            data = self._get_sensor_data()
            forecast = self._sager_algorithm(data)
            self._sager_forecast_text = forecast["text"]
            self._sager_attributes = {
                ATTR_PRESSURE_LEVEL: forecast["hpa_level"],
                ATTR_WIND_TREND: forecast["wind_trend"],
                ATTR_PRESSURE_TREND: forecast["pressure_trend"],
                ATTR_CLOUD_LEVEL: forecast["cloud_level"],
                ATTR_CONFIDENCE: forecast["confidence"],
            }

            # Generate daily forecast
            self._forecast_data = self._generate_forecast(forecast)

            _LOGGER.debug(
                f"Weather update completed, confidence: {forecast['confidence']}%"
            )

        except Exception as e:
            _LOGGER.error(f"Sager Weather update error: {e}", exc_info=True)

    def _update_current_conditions(self) -> None:
        """Update current weather conditions from sensors."""
        # Temperature
        temp_entity = self._config.get(CONF_TEMPERATURE_ENTITY)
        if temp_entity:
            temp_state = self._hass.states.get(temp_entity)
            if temp_state and temp_state.state not in ["unavailable", "unknown"]:
                try:
                    self._attr_native_temperature = float(temp_state.state)
                except (ValueError, TypeError):
                    _LOGGER.debug(f"Invalid temperature value: {temp_state.state}")

        # Humidity
        humidity_entity = self._config.get(CONF_HUMIDITY_ENTITY)
        if humidity_entity:
            hum_state = self._hass.states.get(humidity_entity)
            if hum_state and hum_state.state not in ["unavailable", "unknown"]:
                try:
                    self._attr_humidity = float(hum_state.state)
                except (ValueError, TypeError):
                    _LOGGER.debug(f"Invalid humidity value: {hum_state.state}")

        # Pressure
        pressure_entity = self._config.get(CONF_PRESSURE_ENTITY)
        if pressure_entity:
            press_state = self._hass.states.get(pressure_entity)
            if press_state and press_state.state not in ["unavailable", "unknown"]:
                try:
                    self._attr_native_pressure = float(press_state.state)
                except (ValueError, TypeError):
                    _LOGGER.debug(f"Invalid pressure value: {press_state.state}")

        # Wind Speed
        wind_speed_entity = self._config.get(CONF_WIND_SPEED_ENTITY)
        if wind_speed_entity:
            wind_state = self._hass.states.get(wind_speed_entity)
            if wind_state and wind_state.state not in ["unavailable", "unknown"]:
                try:
                    self._attr_native_wind_speed = float(wind_state.state)
                except (ValueError, TypeError):
                    _LOGGER.debug(f"Invalid wind speed value: {wind_state.state}")

        # Wind Direction
        wind_dir_entity = self._config.get(CONF_WIND_DIR_ENTITY)
        if wind_dir_entity:
            dir_state = self._hass.states.get(wind_dir_entity)
            if dir_state and dir_state.state not in ["unavailable", "unknown"]:
                try:
                    self._attr_wind_bearing = float(dir_state.state)
                except (ValueError, TypeError):
                    _LOGGER.debug(f"Invalid wind direction value: {dir_state.state}")

        # Condition
        condition_entity = self._config.get(CONF_CONDITION_ENTITY)
        if condition_entity:
            cond_state = self._hass.states.get(condition_entity)
            if cond_state and cond_state.state not in ["unavailable", "unknown"]:
                self._attr_condition = self._map_condition(cond_state.state)
        else:
            # Auto-detect condition from cloud cover and rain
            cloud_entity = self._config.get(CONF_CLOUD_COVER_ENTITY)
            rain_entity = self._config.get(CONF_RAINING_ENTITY)

            is_raining = False
            if rain_entity:
                rain_state = self._hass.states.get(rain_entity)
                is_raining = rain_state and rain_state.state in ["on", "true"]

            if is_raining:
                self._attr_condition = "rainy"
            elif cloud_entity:
                cloud_state = self._hass.states.get(cloud_entity)
                if cloud_state and cloud_state.state not in ["unavailable", "unknown"]:
                    try:
                        cloud_cover = float(cloud_state.state)
                        if cloud_cover > 80:
                            self._attr_condition = "cloudy"
                        elif cloud_cover > 50:
                            self._attr_condition = "partlycloudy"
                        elif cloud_cover > 20:
                            self._attr_condition = "sunny"
                        else:
                            self._attr_condition = (
                                "clear-night" if self._is_night() else "sunny"
                            )
                    except (ValueError, TypeError):
                        self._attr_condition = "cloudy"

    def _map_condition(self, state: str) -> str:
        """Map various condition strings to HA weather conditions."""
        condition_map = {
            "clear": "sunny",
            "sunny": "sunny",
            "clear-night": "clear-night",
            "cloudy": "cloudy",
            "overcast": "cloudy",
            "partly-cloudy": "partlycloudy",
            "partlycloudy": "partlycloudy",
            "fog": "fog",
            "rainy": "rainy",
            "rain": "rainy",
            "pouring": "pouring",
            "snowy": "snowy",
            "snow": "snowy",
            "hail": "hail",
            "lightning": "lightning",
            "thunderstorm": "lightning",
            "windy": "windy",
            "exceptional": "exceptional",
        }
        return condition_map.get(state.lower(), "cloudy")

    def _is_night(self) -> bool:
        """Check if it's currently night."""
        now = dt_util.now()
        return now.hour < 6 or now.hour > 20

    def _get_sensor_data(self) -> dict[str, Any]:
        """Get input data from configured entities."""
        # Import sensor class to reuse method
        from .sensor import SagerSensor

        # Create temporary sensor instance to reuse data gathering
        temp_sensor = SagerSensor(self._hass, "temp", self._config)
        return temp_sensor._get_sensor_data()

    def _sager_algorithm(self, data: dict[str, Any]) -> dict[str, Any]:
        """Complete Sager weather algorithm."""
        # Import sensor class to reuse algorithm
        from .sensor import SagerSensor

        # Create temporary sensor instance to reuse algorithm
        temp_sensor = SagerSensor(self._hass, "temp", self._config)
        return temp_sensor._sager_algorithm(data)

    def _generate_forecast(self, sager_result: dict[str, Any]) -> list[Forecast]:
        """Generate a simple daily forecast based on Sager prediction."""
        forecasts: list[Forecast] = []
        now = dt_util.now()

        # Determine condition from forecast text
        forecast_text = sager_result["text"].lower()

        if "pioggia" in forecast_text or "rovesci" in forecast_text:
            condition = "rainy"
            precipitation = 80.0
        elif "coperto" in forecast_text or "nuvoloso" in forecast_text:
            condition = "cloudy"
            precipitation = 30.0
        elif "sereno" in forecast_text:
            condition = "sunny"
            precipitation = 0.0
        else:
            condition = "partlycloudy"
            precipitation = 20.0

        # Temperature trend from forecast
        temp_change = 0.0
        if "aumento" in forecast_text:
            temp_change = 3.0
        elif "calo" in forecast_text:
            temp_change = -3.0

        # Generate 3-day forecast
        for day in range(3):
            forecast_date = now + timedelta(days=day)
            base_temp = self._attr_native_temperature or 15.0

            forecasts.append(
                Forecast(
                    datetime=forecast_date.isoformat(),
                    condition=condition,
                    native_temperature=base_temp + (temp_change * day),
                    native_templow=base_temp + (temp_change * day) - 5.0,
                    native_precipitation=precipitation
                    if day == 0
                    else precipitation * 0.7,
                    native_pressure=self._attr_native_pressure,
                    native_wind_speed=self._attr_native_wind_speed,
                    wind_bearing=self._attr_wind_bearing,
                )
            )

        return forecasts
