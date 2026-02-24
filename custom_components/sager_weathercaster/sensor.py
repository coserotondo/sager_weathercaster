"""Sager Weathercaster Sensor Platform."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_CLOUD_LEVEL,
    ATTR_CONFIDENCE,
    ATTR_LAST_UPDATE,
    ATTR_PRESSURE_LEVEL,
    ATTR_PRESSURE_TREND,
    ATTR_RAW_DATA,
    ATTR_WIND_DIR,
    ATTR_WIND_TREND,
    DOMAIN,
    FORECAST_CONDITIONS,
    MANUFACTURER,
    MODEL,
    VERSION,
)
from .coordinator import SagerWeathercasterCoordinator

PARALLEL_UPDATES = 0

if TYPE_CHECKING:
    from . import SagerConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SagerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Sager Weathercaster sensors from a config entry."""
    coordinator = entry.runtime_data

    async_add_entities(
        [
            SagerSensor(coordinator, entry),
            SagerReliabilitySensor(coordinator, entry),
        ]
    )


class SagerSensor(CoordinatorEntity[SagerWeathercasterCoordinator], SensorEntity):
    """Sager Weathercaster Forecast Sensor."""

    _attr_has_entity_name = True
    _attr_translation_key = "sager_forecast"
    _attr_device_class = "enum"

    def __init__(
        self,
        coordinator: SagerWeathercasterCoordinator,
        entry: SagerConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        self._attr_unique_id = f"{entry.entry_id}_forecast"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=VERSION,
        )
        # All possible forecast codes (base + shower/flurry variants)
        self._attr_options = list(FORECAST_CONDITIONS.keys())

    @property
    def native_value(self) -> str | None:
        """Return the forecast code as state (translated by HA)."""
        if not self.coordinator.data:
            return None

        forecast = self.coordinator.data.get("forecast", {})
        return forecast.get("forecast_code")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data:
            return {}

        forecast = self.coordinator.data.get("forecast", {})
        sensor_data = self.coordinator.data.get("sensor_data", {})

        # Build raw data without raining boolean
        raw_data = {k: v for k, v in sensor_data.items() if k != "raining"}

        zambretti = self.coordinator.data.get("zambretti", {})

        return {
            ATTR_PRESSURE_LEVEL: forecast.get("hpa_level"),
            ATTR_WIND_DIR: forecast.get("wind_dir"),
            ATTR_WIND_TREND: forecast.get("wind_trend"),
            ATTR_CLOUD_LEVEL: forecast.get("cloud_level"),
            ATTR_PRESSURE_TREND: forecast.get("pressure_trend"),
            ATTR_CONFIDENCE: forecast.get("confidence"),
            "wind_velocity": forecast.get("wind_velocity_key"),
            "wind_direction": forecast.get("wind_direction_key"),
            "latitude_zone": forecast.get("latitude_zone"),
            "cross_validation": forecast.get("cross_validation"),
            "zambretti_condition": forecast.get("zambretti_condition"),
            "zambretti_forecast": zambretti.get("zambretti_key"),
            ATTR_RAW_DATA: raw_data,
            ATTR_LAST_UPDATE: dt_util.now().strftime("%Y-%m-%d %H:%M:%S"),
        }


class SagerReliabilitySensor(
    CoordinatorEntity[SagerWeathercasterCoordinator], SensorEntity
):
    """Sager Weathercaster reliability score sensor."""

    _attr_icon = "mdi:gauge"
    _attr_has_entity_name = True
    _attr_translation_key = "sager_reliability"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: SagerWeathercasterCoordinator,
        entry: SagerConfigEntry,
    ) -> None:
        """Initialize the reliability sensor."""
        super().__init__(coordinator)

        self._attr_unique_id = f"{entry.entry_id}_reliability"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=VERSION,
        )

    @property
    def native_value(self) -> int | None:
        """Return the reliability score."""
        if not self.coordinator.data:
            return None

        reliability = self.coordinator.data.get("reliability", {})
        return reliability.get("score", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return per-sensor status and external weather status."""
        if not self.coordinator.data:
            return {}

        reliability = self.coordinator.data.get("reliability", {})
        attrs = dict(reliability.get("sensor_status", {}))

        # Add external weather entity status
        ext_weather = self.coordinator.data.get("ext_weather", {})
        if not ext_weather.get("configured"):
            attrs["external_weather"] = "not_configured"
        elif ext_weather.get("available"):
            attrs["external_weather"] = "available"
        elif ext_weather.get("last_updated") is not None:
            attrs["external_weather"] = "stale"
        else:
            attrs["external_weather"] = "not_fetched"

        last_updated = ext_weather.get("last_updated")
        if last_updated is not None:
            attrs["external_weather_last_updated"] = last_updated.isoformat()

        return attrs
