"""Sager Weathercaster - Home Assistant Integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import SagerWeathercasterCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.WEATHER]

type SagerConfigEntry = ConfigEntry[SagerWeathercasterCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: SagerConfigEntry) -> bool:
    """Set up Sager Weathercaster from a config entry."""
    coordinator = SagerWeathercasterCoordinator(hass, entry)

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator in runtime_data
    entry.runtime_data = coordinator

    # Reload the entry when the user saves new options so the coordinator
    # is recreated with the updated entity references.
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    # Forward setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def _async_reload_entry(hass: HomeAssistant, entry: SagerConfigEntry) -> None:
    """Reload the config entry after an options flow update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SagerConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
