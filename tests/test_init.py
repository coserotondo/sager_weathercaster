"""Tests for Sager Weathercaster integration setup and teardown."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.sager_weathercaster.const import DOMAIN

from .conftest import MOCK_COORDINATOR_DATA, MOCK_PRESSURE_ENTITY, MOCK_WIND_DIR_ENTITY


async def _setup_integration(hass: HomeAssistant) -> None:
    """Create and load a config entry using a mocked coordinator refresh."""
    from homeassistant.config_entries import ConfigEntry

    entry = hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, None)
    if entry is not None:
        return

    # Patch the coordinator's data fetch so no real sensors or network are needed
    with patch(
        "custom_components.sager_weathercaster.coordinator"
        ".SagerWeathercasterCoordinator._async_update_data",
        return_value=MOCK_COORDINATOR_DATA,
    ):
        from homeassistant.config_entries import ConfigEntry

        entry = ConfigEntry(
            version=1,
            minor_version=1,
            domain=DOMAIN,
            title="Sager Weather",
            data={
                "pressure_entity": MOCK_PRESSURE_ENTITY,
                "wind_dir_entity": MOCK_WIND_DIR_ENTITY,
            },
            options={},
            source="user",
            unique_id=f"{MOCK_PRESSURE_ENTITY}_{MOCK_WIND_DIR_ENTITY}",
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


@pytest.fixture
async def loaded_entry(hass: HomeAssistant):
    """Fixture that returns a successfully loaded config entry."""
    from homeassistant.config_entries import ConfigEntry

    with patch(
        "custom_components.sager_weathercaster.coordinator"
        ".SagerWeathercasterCoordinator._async_update_data",
        return_value=MOCK_COORDINATOR_DATA,
    ):
        entry = ConfigEntry(
            version=1,
            minor_version=1,
            domain=DOMAIN,
            title="Sager Weather",
            data={
                "pressure_entity": MOCK_PRESSURE_ENTITY,
                "wind_dir_entity": MOCK_WIND_DIR_ENTITY,
            },
            options={},
            source="user",
            unique_id=f"{MOCK_PRESSURE_ENTITY}_{MOCK_WIND_DIR_ENTITY}",
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return entry


async def test_setup_entry_success(hass: HomeAssistant, loaded_entry) -> None:
    """Test that the integration sets up and reaches LOADED state."""
    assert loaded_entry.state is ConfigEntryState.LOADED


async def test_setup_entry_creates_entities(hass: HomeAssistant, loaded_entry) -> None:
    """Test that setup registers the expected sensor and weather entities."""
    entity_ids = hass.states.async_entity_ids()
    # Expect: forecast sensor, reliability sensor, weather entity
    domains_found = {e.split(".")[0] for e in entity_ids}
    assert "sensor" in domains_found
    assert "weather" in domains_found


async def test_unload_entry(hass: HomeAssistant, loaded_entry) -> None:
    """Test that the integration can be unloaded cleanly."""
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert loaded_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_entry_coordinator_failure(hass: HomeAssistant) -> None:
    """Test that a coordinator failure on first refresh raises ConfigEntryNotReady."""
    from homeassistant.helpers.update_coordinator import UpdateFailed
    from homeassistant.config_entries import ConfigEntry, ConfigEntryState

    with patch(
        "custom_components.sager_weathercaster.coordinator"
        ".SagerWeathercasterCoordinator._async_update_data",
        side_effect=UpdateFailed("Simulated failure"),
    ):
        entry = ConfigEntry(
            version=1,
            minor_version=1,
            domain=DOMAIN,
            title="Sager Weather",
            data={
                "pressure_entity": MOCK_PRESSURE_ENTITY,
                "wind_dir_entity": MOCK_WIND_DIR_ENTITY,
            },
            options={},
            source="user",
            unique_id="fail_test",
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
