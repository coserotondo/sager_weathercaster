"""Config flow for Sager Weathercaster integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    TextSelector,
)

from .const import (
    CONF_CLOUD_COVER_ENTITY,
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
)


def _validate_sensor_units(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> dict[str, str]:
    """Validate unit of measurement for sensors that have strict requirements.

    Returns a dict of field_key → error_key for any violations found.
    Sensors that are unavailable or have no unit are skipped (coordinator
    handles missing data gracefully via range validation).
    """
    errors: dict[str, str] = {}

    # Pressure must be hPa (or the equivalent mbar).
    # Using Pa, kPa, or other units would put values far outside the
    # algorithm's 900–1100 hPa table range and produce silently wrong results.
    if pressure_id := user_input.get(CONF_PRESSURE_ENTITY):
        state = hass.states.get(pressure_id)
        if state:
            unit = state.attributes.get("unit_of_measurement", "")
            if unit and unit not in ("hPa", "mbar"):
                errors[CONF_PRESSURE_ENTITY] = "invalid_pressure_unit"

    # Cloud cover sensor must be % or lx.
    # Any other unit cannot be interpreted and will silently default to 0 %.
    if cloud_id := user_input.get(CONF_CLOUD_COVER_ENTITY):
        state = hass.states.get(cloud_id)
        if state:
            unit = state.attributes.get("unit_of_measurement", "")
            if unit and unit not in ("%", "lx"):
                errors[CONF_CLOUD_COVER_ENTITY] = "invalid_cloud_unit"

    return errors


def _build_sensor_schema(current: dict[str, Any]) -> vol.Schema:
    """Build the sensor entity selection schema pre-filled from current values."""
    return vol.Schema(
        {
            vol.Optional(
                CONF_NAME, default=current.get(CONF_NAME, DEFAULT_NAME)
            ): TextSelector(),
            vol.Optional(
                CONF_PRESSURE_ENTITY,
                default=current.get(CONF_PRESSURE_ENTITY),
            ): EntitySelector(EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_WIND_DIR_ENTITY,
                default=current.get(CONF_WIND_DIR_ENTITY),
            ): EntitySelector(EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_WIND_SPEED_ENTITY,
                default=current.get(CONF_WIND_SPEED_ENTITY),
            ): EntitySelector(EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_WIND_HISTORIC_ENTITY,
                default=current.get(CONF_WIND_HISTORIC_ENTITY),
            ): EntitySelector(EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_PRESSURE_CHANGE_ENTITY,
                default=current.get(CONF_PRESSURE_CHANGE_ENTITY),
            ): EntitySelector(EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_CLOUD_COVER_ENTITY,
                default=current.get(CONF_CLOUD_COVER_ENTITY),
            ): EntitySelector(EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_RAINING_ENTITY,
                default=current.get(CONF_RAINING_ENTITY),
            ): EntitySelector(
                EntitySelectorConfig(domain=["binary_sensor", "sensor"])
            ),
            vol.Optional(
                CONF_TEMPERATURE_ENTITY,
                default=current.get(CONF_TEMPERATURE_ENTITY),
            ): EntitySelector(EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_HUMIDITY_ENTITY,
                default=current.get(CONF_HUMIDITY_ENTITY),
            ): EntitySelector(EntitySelectorConfig(domain="sensor")),
        }
    )


class SagerWeathercasterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Sager Weathercaster."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate required fields
            if not user_input.get(CONF_PRESSURE_ENTITY):
                errors["base"] = "missing_pressure"
            elif not user_input.get(CONF_WIND_DIR_ENTITY):
                errors["base"] = "missing_wind_dir"
            else:
                # Validate units for sensors that have strict requirements
                errors.update(_validate_sensor_units(self.hass, user_input))

            if not errors:
                # Create unique ID based on configured entities
                await self.async_set_unique_id(
                    f"{user_input[CONF_PRESSURE_ENTITY]}_{user_input[CONF_WIND_DIR_ENTITY]}"
                )
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, DEFAULT_NAME),
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_sensor_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of an existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            if not user_input.get(CONF_PRESSURE_ENTITY):
                errors["base"] = "missing_pressure"
            elif not user_input.get(CONF_WIND_DIR_ENTITY):
                errors["base"] = "missing_wind_dir"
            else:
                errors.update(_validate_sensor_units(self.hass, user_input))

            if not errors:
                return self.async_update_reload_and_abort(
                    entry,
                    title=user_input.get(CONF_NAME, entry.title),
                    data=user_input,
                )

        # Pre-fill form with current entry data; use entry.title as name fallback
        current = dict(entry.data)
        current.setdefault(CONF_NAME, entry.title)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_build_sensor_schema(current),
            errors=errors,
        )
