"""Sager Weathercaster Sensor Platform."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
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
    ATTR_PRESSURE_CHANGE_6H,
    ATTR_PRESSURE_LEVEL,
    ATTR_PRESSURE_TREND,
    ATTR_WIND_DIRECTION_6H_AGO,
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
    _attr_device_class = SensorDeviceClass.ENUM

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
        return cast("str | None", forecast.get("forecast_code"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data:
            return {}

        forecast = self.coordinator.data.get("forecast", {})
        sensor_data = self.coordinator.data.get("sensor_data", {})
        zambretti = self.coordinator.data.get("zambretti", {})

        pressure_change = sensor_data.get("pressure_change")
        wind_historic = sensor_data.get("wind_historic")
        cloud_cover_raw = sensor_data.get("cloud_cover")

        return {
            ATTR_PRESSURE_LEVEL: forecast.get("hpa_level"),
            ATTR_PRESSURE_CHANGE_6H: round(pressure_change, 1)
            if pressure_change is not None
            else None,
            ATTR_WIND_TREND: forecast.get("wind_trend"),
            ATTR_WIND_DIRECTION_6H_AGO: wind_historic,
            ATTR_CLOUD_LEVEL: forecast.get("cloud_level"),
            ATTR_PRESSURE_TREND: forecast.get("pressure_trend"),
            ATTR_CONFIDENCE: forecast.get("confidence"),
            "wind_velocity": forecast.get("wind_velocity_key"),
            "wind_direction": forecast.get("wind_direction_key"),
            "latitude_zone": forecast.get("latitude_zone"),
            "cross_validation": forecast.get("cross_validation"),
            "zambretti_condition": forecast.get("zambretti_condition"),
            "zambretti_forecast": zambretti.get("zambretti_key"),
            "cloud_cover": round(cloud_cover_raw, 1)
            if cloud_cover_raw is not None
            else None,
            "sky_calibration_factor": round(
                self.coordinator.sky_calibration_factor, 3
            ),
            "calibration_seed": self.coordinator.calibration_seed,
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
        return cast("int | None", reliability.get("score", 0))

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

        # Highlight when local lux (clear sky) disagrees with external cloud cover
        if ext_weather.get("cloud_conflict"):
            attrs["ext_weather_cloud_conflict"] = True

        # Retrospective forecast verification
        verification = self.coordinator.data.get("verification", {})
        if verification.get("rolling_accuracy") is not None:
            attrs["forecast_accuracy"] = round(
                float(verification["rolling_accuracy"]), 1
            )
            attrs["forecast_verifications"] = verification.get(
                "verifications_count", 0
            )
        if verification.get("last_score") is not None:
            attrs["last_verification_score"] = verification["last_score"]
            attrs["last_verification_rain_correct"] = verification[
                "last_rain_correct"
            ]
            attrs["last_verification_predicted_at"] = verification[
                "last_predicted_at"
            ]
            attrs["last_verification_verified_at"] = verification[
                "last_verified_at"
            ]
        if verification.get("pending_since") is not None:
            attrs["verification_pending_since"] = verification["pending_since"]

        return attrs
