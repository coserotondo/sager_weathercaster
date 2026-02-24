"""Config flow for Sager Weathercaster integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    TextSelector,
)

from .const import (
    CONF_CLOUD_COVER_ENTITY,
    CONF_DEWPOINT_ENTITY,
    CONF_HUMIDITY_ENTITY,
    CONF_OPEN_METEO_ENABLED,
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

    # Cloud cover sensor must be %, lx, or W/m².
    # Any other unit cannot be interpreted and will silently default to 0 %.
    if cloud_id := user_input.get(CONF_CLOUD_COVER_ENTITY):
        state = hass.states.get(cloud_id)
        if state:
            unit = state.attributes.get("unit_of_measurement", "")
            if unit and unit not in ("%", "lx", "W/m²", "W/m2"):
                errors[CONF_CLOUD_COVER_ENTITY] = "invalid_cloud_unit"

    return errors


def _opt_entity(
    key: str,
    current: dict[str, Any],
    domain: str | list[str] = "sensor",
) -> tuple[vol.Optional, EntitySelector]:
    """Return a (vol.Optional, EntitySelector) pair for an optional entity field.

    When the field is not currently configured the voluptuous key has no default,
    so the key is absent from validated output rather than being set to None (which
    EntitySelector would reject).  When a value is already configured it is used as
    the pre-filled default.
    """
    current_value = current.get(key)
    opt = (
        vol.Optional(key, default=current_value)
        if current_value is not None
        else vol.Optional(key)
    )
    return opt, EntitySelector(EntitySelectorConfig(domain=domain))


def _req_entity(
    key: str,
    current: dict[str, Any],
) -> tuple[vol.Required, EntitySelector]:
    """Return a (vol.Required, EntitySelector) pair for a required entity field.

    When a value is already configured it is used as the pre-filled default so
    the user sees it pre-selected on reconfigure / error re-display.
    """
    current_value = current.get(key)
    req = (
        vol.Required(key, default=current_value)
        if current_value is not None
        else vol.Required(key)
    )
    return req, EntitySelector(EntitySelectorConfig(domain="sensor"))


def _build_required_schema(current: dict[str, Any]) -> vol.Schema:
    """Build the step-1 schema: name + the two required entity selectors."""
    return vol.Schema(
        {
            vol.Optional(
                CONF_NAME, default=current.get(CONF_NAME, DEFAULT_NAME)
            ): TextSelector(),
            **dict(
                [
                    _req_entity(CONF_PRESSURE_ENTITY, current),
                    _req_entity(CONF_WIND_DIR_ENTITY, current),
                ]
            ),
        }
    )


def _build_optional_schema(current: dict[str, Any]) -> vol.Schema:
    """Build the step-2 schema: all eight optional entity selectors."""
    return vol.Schema(
        {
            **dict(
                [
                    _opt_entity(CONF_WIND_SPEED_ENTITY, current),
                    _opt_entity(CONF_WIND_HISTORIC_ENTITY, current),
                    _opt_entity(CONF_PRESSURE_CHANGE_ENTITY, current),
                    _opt_entity(CONF_CLOUD_COVER_ENTITY, current),
                    _opt_entity(
                        CONF_RAINING_ENTITY,
                        current,
                        domain=["binary_sensor", "sensor"],
                    ),
                    _opt_entity(CONF_TEMPERATURE_ENTITY, current),
                    _opt_entity(CONF_HUMIDITY_ENTITY, current),
                    _opt_entity(CONF_DEWPOINT_ENTITY, current),
                ]
            ),
        }
    )


def _build_reconfigure_schema(current: dict[str, Any]) -> vol.Schema:
    """Build the reconfigure schema: all 11 fields pre-filled from current values."""
    return vol.Schema(
        {
            vol.Optional(
                CONF_NAME, default=current.get(CONF_NAME, DEFAULT_NAME)
            ): TextSelector(),
            **dict(
                [
                    _req_entity(CONF_PRESSURE_ENTITY, current),
                    _req_entity(CONF_WIND_DIR_ENTITY, current),
                    _opt_entity(CONF_WIND_SPEED_ENTITY, current),
                    _opt_entity(CONF_WIND_HISTORIC_ENTITY, current),
                    _opt_entity(CONF_PRESSURE_CHANGE_ENTITY, current),
                    _opt_entity(CONF_CLOUD_COVER_ENTITY, current),
                    _opt_entity(
                        CONF_RAINING_ENTITY,
                        current,
                        domain=["binary_sensor", "sensor"],
                    ),
                    _opt_entity(CONF_TEMPERATURE_ENTITY, current),
                    _opt_entity(CONF_HUMIDITY_ENTITY, current),
                    _opt_entity(CONF_DEWPOINT_ENTITY, current),
                ]
            ),
        }
    )


class SagerWeathercasterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Sager Weathercaster."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow, storing required-step data between steps."""
        self._required_data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle step 1 — required sensors (pressure + wind direction)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors.update(_validate_sensor_units(self.hass, user_input))
            if not errors:
                self._required_data = user_input
                return await self.async_step_optional_sensors()

        return self.async_show_form(
            step_id="user",
            data_schema=_build_required_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_optional_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle step 2 — optional enhancement sensors."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors.update(_validate_sensor_units(self.hass, user_input))
            if not errors:
                data = {**self._required_data, **user_input}
                await self.async_set_unique_id(
                    f"{data[CONF_PRESSURE_ENTITY]}_{data[CONF_WIND_DIR_ENTITY]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=data.get(CONF_NAME, DEFAULT_NAME),
                    data=data,
                )

        return self.async_show_form(
            step_id="optional_sensors",
            data_schema=_build_optional_schema(user_input or {}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> SagerWeathercasterOptionsFlow:
        """Get the options flow for this handler."""
        return SagerWeathercasterOptionsFlow()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of an existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            errors.update(_validate_sensor_units(self.hass, user_input))
            if not errors:
                self.hass.config_entries.async_update_entry(
                    entry,
                    title=user_input.get(CONF_NAME, entry.title),
                    data=user_input,
                )
                return self.async_abort(reason="reconfigure_successful")

        # Pre-fill form with current entry data; use entry.title as name fallback.
        current = dict(entry.data)
        current.setdefault(CONF_NAME, entry.title)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_build_reconfigure_schema(current),
            errors=errors,
        )


class SagerWeathercasterOptionsFlow(OptionsFlow):
    """Options flow for behavioral settings (not sensor wiring)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage behavioral options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current_enabled = self.config_entry.options.get(CONF_OPEN_METEO_ENABLED, True)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_OPEN_METEO_ENABLED, default=current_enabled
                    ): BooleanSelector(),
                }
            ),
        )
