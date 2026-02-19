"""Tests for Sager Weathercaster config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.sager_weathercaster.const import (
    CONF_CLOUD_COVER_ENTITY,
    CONF_PRESSURE_ENTITY,
    CONF_WIND_DIR_ENTITY,
    DEFAULT_NAME,
    DOMAIN,
)

from .conftest import MOCK_PRESSURE_ENTITY, MOCK_WIND_DIR_ENTITY


# ── Config flow: initial form ───────────────────────────────────────────────


async def test_form_shows(hass: HomeAssistant) -> None:
    """Test that the user step shows the form without errors."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


# ── Config flow: required-field validation ───────────────────────────────────


async def test_user_step_missing_pressure(hass: HomeAssistant) -> None:
    """Test error when the atmospheric pressure entity is not provided."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_WIND_DIR_ENTITY: MOCK_WIND_DIR_ENTITY},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "missing_pressure"}


async def test_user_step_missing_wind_dir(hass: HomeAssistant) -> None:
    """Test error when the wind direction entity is not provided."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PRESSURE_ENTITY: MOCK_PRESSURE_ENTITY},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "missing_wind_dir"}


# ── Config flow: unit validation ─────────────────────────────────────────────


async def test_user_step_invalid_pressure_unit(hass: HomeAssistant) -> None:
    """Test error when the pressure sensor reports in an unsupported unit."""
    hass.states.async_set(
        MOCK_PRESSURE_ENTITY, "101325", {"unit_of_measurement": "Pa"}
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_PRESSURE_ENTITY: MOCK_PRESSURE_ENTITY,
            CONF_WIND_DIR_ENTITY: MOCK_WIND_DIR_ENTITY,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"].get(CONF_PRESSURE_ENTITY) == "invalid_pressure_unit"


@pytest.mark.parametrize("unit", ["hPa", "mbar"])
async def test_user_step_valid_pressure_units(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    unit: str,
) -> None:
    """Test that hPa and mbar are both accepted as pressure units."""
    hass.states.async_set(
        MOCK_PRESSURE_ENTITY, "1013", {"unit_of_measurement": unit}
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_PRESSURE_ENTITY: MOCK_PRESSURE_ENTITY,
            CONF_WIND_DIR_ENTITY: MOCK_WIND_DIR_ENTITY,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_user_step_invalid_cloud_unit(hass: HomeAssistant) -> None:
    """Test error when the cloud cover sensor uses an unsupported unit."""
    hass.states.async_set(
        "sensor.cloud", "500", {"unit_of_measurement": "W/m²"}
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_PRESSURE_ENTITY: MOCK_PRESSURE_ENTITY,
            CONF_WIND_DIR_ENTITY: MOCK_WIND_DIR_ENTITY,
            CONF_CLOUD_COVER_ENTITY: "sensor.cloud",
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"].get(CONF_CLOUD_COVER_ENTITY) == "invalid_cloud_unit"


@pytest.mark.parametrize("unit", ["%", "lx"])
async def test_user_step_valid_cloud_units(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    unit: str,
) -> None:
    """Test that % and lx are both accepted as cloud cover units."""
    hass.states.async_set(
        "sensor.cloud", "50", {"unit_of_measurement": unit}
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_PRESSURE_ENTITY: MOCK_PRESSURE_ENTITY,
            CONF_WIND_DIR_ENTITY: MOCK_WIND_DIR_ENTITY,
            CONF_CLOUD_COVER_ENTITY: "sensor.cloud",
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY


# ── Config flow: happy path ───────────────────────────────────────────────────


async def test_user_step_success(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test a successful config entry is created with valid input."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_PRESSURE_ENTITY: MOCK_PRESSURE_ENTITY,
            CONF_WIND_DIR_ENTITY: MOCK_WIND_DIR_ENTITY,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == DEFAULT_NAME
    assert result["data"][CONF_PRESSURE_ENTITY] == MOCK_PRESSURE_ENTITY
    assert result["data"][CONF_WIND_DIR_ENTITY] == MOCK_WIND_DIR_ENTITY
    mock_setup_entry.assert_called_once()


async def test_user_step_success_with_custom_name(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test that a custom name is stored as the entry title."""
    from homeassistant.const import CONF_NAME

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "My Station",
            CONF_PRESSURE_ENTITY: MOCK_PRESSURE_ENTITY,
            CONF_WIND_DIR_ENTITY: MOCK_WIND_DIR_ENTITY,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "My Station"


# ── Config flow: duplicate prevention ────────────────────────────────────────


async def test_user_step_already_configured(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    user_input_valid: dict[str, str],
) -> None:
    """Test that a second entry for the same entity pair is rejected."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input_valid
    )

    result2 = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result2["flow_id"], user_input_valid
    )
    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "already_configured"


# ── Options flow ──────────────────────────────────────────────────────────────


async def _create_entry(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    user_input: dict[str, str],
) -> config_entries.ConfigEntry:
    """Helper that creates a config entry and returns it."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    return hass.config_entries.async_entries(DOMAIN)[0]


async def test_options_flow_shows(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    user_input_valid: dict[str, str],
) -> None:
    """Test that the options form is shown with the current entity values."""
    entry = await _create_entry(hass, mock_setup_entry, user_input_valid)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"


async def test_options_flow_success(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    user_input_valid: dict[str, str],
) -> None:
    """Test successfully updating the options via the options flow."""
    entry = await _create_entry(hass, mock_setup_entry, user_input_valid)

    new_wind_dir = "sensor.updated_wind_dir"
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_PRESSURE_ENTITY: MOCK_PRESSURE_ENTITY,
            CONF_WIND_DIR_ENTITY: new_wind_dir,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_WIND_DIR_ENTITY] == new_wind_dir


async def test_options_flow_invalid_pressure_unit(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    user_input_valid: dict[str, str],
) -> None:
    """Test that a unit validation error is shown in the options flow."""
    entry = await _create_entry(hass, mock_setup_entry, user_input_valid)

    hass.states.async_set(
        MOCK_PRESSURE_ENTITY, "101325", {"unit_of_measurement": "Pa"}
    )
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_PRESSURE_ENTITY: MOCK_PRESSURE_ENTITY,
            CONF_WIND_DIR_ENTITY: MOCK_WIND_DIR_ENTITY,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"].get(CONF_PRESSURE_ENTITY) == "invalid_pressure_unit"
