"""Tests for Sager Weathercaster integration setup and teardown."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from tests.common import MockConfigEntry

from custom_components.sager_weathercaster.const import DOMAIN

from .conftest import MOCK_COORDINATOR_DATA, MOCK_PRESSURE_ENTITY, MOCK_WIND_DIR_ENTITY


def _make_entry(**kwargs) -> MockConfigEntry:
    """Return a MockConfigEntry with sensible defaults for this integration."""
    defaults = {
        "domain": DOMAIN,
        "title": "Sager Weather",
        "data": {
            "pressure_entity": MOCK_PRESSURE_ENTITY,
            "wind_dir_entity": MOCK_WIND_DIR_ENTITY,
        },
        "options": {},
        "source": "user",
        "unique_id": f"{MOCK_PRESSURE_ENTITY}_{MOCK_WIND_DIR_ENTITY}",
    }
    defaults.update(kwargs)
    return MockConfigEntry(**defaults)


@pytest.fixture
async def loaded_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Fixture that returns a successfully loaded config entry."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.sager_weathercaster.coordinator"
        ".SagerWeathercasterCoordinator._async_update_data",
        return_value=MOCK_COORDINATOR_DATA,
    ):
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
    """Test that a coordinator failure on first refresh is handled gracefully.

    The integration uses async_refresh() (not async_config_entry_first_refresh()),
    so UpdateFailed is caught internally: the entry stays LOADED but the coordinator
    marks last_update_success as False.
    """
    from homeassistant.helpers.update_coordinator import UpdateFailed

    entry = _make_entry(unique_id="fail_test")
    entry.add_to_hass(hass)

    with patch(
        "custom_components.sager_weathercaster.coordinator"
        ".SagerWeathercasterCoordinator._async_update_data",
        side_effect=UpdateFailed("Simulated failure"),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    coordinator = entry.runtime_data
    assert coordinator.last_update_success is False
