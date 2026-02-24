"""Tests for Sager Weathercaster config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData

from custom_components.sager_weathercaster.const import (
    CONF_CLOUD_COVER_ENTITY,
    CONF_PRESSURE_ENTITY,
    CONF_WIND_DIR_ENTITY,
    DEFAULT_NAME,
    DOMAIN,
)

from .conftest import MOCK_PRESSURE_ENTITY, MOCK_WIND_DIR_ENTITY


# ── Shared helper ────────────────────────────────────────────────────────────


async def _create_entry(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    required_input: dict[str, str],
    optional_input: dict[str, str] | None = None,
) -> config_entries.ConfigEntry:
    """Create a config entry by going through both config flow steps."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], required_input
    )
    assert result["step_id"] == "optional_sensors"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], optional_input or {}
    )
    return hass.config_entries.async_entries(DOMAIN)[0]


# ── Config flow: initial form ─────────────────────────────────────────────────


async def test_form_shows(hass: HomeAssistant) -> None:
    """Test that the user step shows the form without errors."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


# ── Config flow: step-1 → step-2 transition ───────────────────────────────────


async def test_user_step_advances_to_optional_sensors(hass: HomeAssistant) -> None:
    """Test that valid required-sensor input advances to the optional sensors step."""
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
    assert result["step_id"] == "optional_sensors"
    assert result["errors"] == {}


async def test_optional_sensors_step_can_be_skipped(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test that the optional sensors step can be submitted empty to create an entry."""
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
    assert result["step_id"] == "optional_sensors"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == FlowResultType.CREATE_ENTRY


# ── Config flow: unit validation ──────────────────────────────────────────────


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
    assert result["step_id"] == "user"
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
    # Step 1 valid → should advance to optional sensors
    assert result["step_id"] == "optional_sensors"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_optional_sensors_step_invalid_cloud_unit(hass: HomeAssistant) -> None:
    """Test error when the cloud cover sensor uses an unsupported unit."""
    hass.states.async_set(
        "sensor.cloud", "500", {"unit_of_measurement": "klux"}
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
    assert result["step_id"] == "optional_sensors"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CLOUD_COVER_ENTITY: "sensor.cloud"},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "optional_sensors"
    assert result["errors"].get(CONF_CLOUD_COVER_ENTITY) == "invalid_cloud_unit"


@pytest.mark.parametrize("unit", ["%", "lx", "W/m²", "W/m2"])
async def test_optional_sensors_step_valid_cloud_units(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    unit: str,
) -> None:
    """Test that %, lx, W/m², and W/m2 are all accepted as cloud cover units."""
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
        },
    )
    assert result["step_id"] == "optional_sensors"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CLOUD_COVER_ENTITY: "sensor.cloud"},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY


# ── Config flow: happy path ───────────────────────────────────────────────────


async def test_user_step_success(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test a successful config entry is created after completing both steps."""
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
    assert result["step_id"] == "optional_sensors"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == DEFAULT_NAME
    assert result["data"][CONF_PRESSURE_ENTITY] == MOCK_PRESSURE_ENTITY
    assert result["data"][CONF_WIND_DIR_ENTITY] == MOCK_WIND_DIR_ENTITY
    mock_setup_entry.assert_called_once()


async def test_user_step_success_with_custom_name(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test that a custom name entered in step 1 is stored as the entry title."""
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
    assert result["step_id"] == "optional_sensors"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "My Station"


# ── Config flow: duplicate prevention ─────────────────────────────────────────


async def test_user_step_already_configured(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    user_input_valid: dict[str, str],
) -> None:
    """Test that a second entry for the same entity pair is rejected."""
    await _create_entry(hass, mock_setup_entry, user_input_valid)

    result2 = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result2["flow_id"], user_input_valid
    )
    assert result2["step_id"] == "optional_sensors"
    result2 = await hass.config_entries.flow.async_configure(result2["flow_id"], {})
    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "already_configured"


# ── Options flow ──────────────────────────────────────────────────────────────


async def test_options_flow_shows(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    user_input_valid: dict[str, str],
) -> None:
    """Test that the options form is shown."""
    entry = await _create_entry(hass, mock_setup_entry, user_input_valid)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"


async def test_options_flow_success_no_entity(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    user_input_valid: dict[str, str],
) -> None:
    """Test submitting the options flow with no weather entity (blank) succeeds."""
    entry = await _create_entry(hass, mock_setup_entry, user_input_valid)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {},  # blank = no external weather entity
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_options_flow_invalid_pressure_unit(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    user_input_valid: dict[str, str],
) -> None:
    """Test that a unit validation error is shown in the reconfigure flow.

    Unit validation lives in the reconfigure step (sensor wiring), not the
    options flow (weather entity selector only).
    """
    entry = await _create_entry(hass, mock_setup_entry, user_input_valid)

    hass.states.async_set(
        MOCK_PRESSURE_ENTITY, "101325", {"unit_of_measurement": "Pa"}
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
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


async def test_options_flow_success_with_entity(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    user_input_valid: dict[str, str],
) -> None:
    """Test that selecting an external weather entity is saved in options."""
    from custom_components.sager_weathercaster.const import CONF_WEATHER_ENTITY

    entry = await _create_entry(hass, mock_setup_entry, user_input_valid)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_WEATHER_ENTITY: "weather.met_no_home"},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_WEATHER_ENTITY] == "weather.met_no_home"


async def test_options_flow_cannot_use_own_entity(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    user_input_valid: dict[str, str],
) -> None:
    """Test that the integration's own weather entity is excluded from the selector.

    The EntitySelector is built with exclude_entities=[sager's weather entity_id],
    so the schema rejects the entity at validation time before our handler runs.
    """
    from homeassistant.helpers import entity_registry as er

    from custom_components.sager_weathercaster.const import CONF_WEATHER_ENTITY, DOMAIN

    entry = await _create_entry(hass, mock_setup_entry, user_input_valid)

    # Register a weather entity that belongs to this integration
    entity_reg = er.async_get(hass)
    sager_entity = entity_reg.async_get_or_create(
        "weather", DOMAIN, "sager_weather", config_entry=entry
    )

    result = await hass.config_entries.options.async_init(entry.entry_id)
    # The own entity is in exclude_entities, so the schema rejects it directly.
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_WEATHER_ENTITY: sager_entity.entity_id},
        )
