"""Sager Weathercaster - Home Assistant Integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import Event, HomeAssistant, callback

from .coordinator import SagerWeathercasterCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.WEATHER]

type SagerConfigEntry = ConfigEntry[SagerWeathercasterCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: SagerConfigEntry) -> bool:
    """Set up Sager Weathercaster from a config entry."""
    coordinator = SagerWeathercasterCoordinator(hass, entry)
    entry.runtime_data = coordinator

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    if hass.is_running:
        # Reload / manual restart: all sensor entities already in the state
        # machine, so fetch real data immediately before platforms are set up.
        await coordinator.async_refresh()
    else:
        # First HA boot: sensor entities load in parallel with this integration.
        # Defer the first fetch until HA has fully started so we read real values
        # instead of defaults. Entities will show unavailable in the meantime.
        _listener_fired = False

        async def _refresh_on_started(_event: Event) -> None:
            nonlocal _listener_fired
            _listener_fired = True
            await coordinator.async_refresh()

        cancel = hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED, _refresh_on_started
        )

        @callback
        def _cancel_if_pending() -> None:
            """Cancel the listener only if it has not yet fired.

            async_listen_once self-removes the job when it fires, so calling
            cancel() afterwards would log an error in HA core before raising.
            """
            if not _listener_fired:
                cancel()

        entry.async_on_unload(_cancel_if_pending)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def _async_reload_entry(hass: HomeAssistant, entry: SagerConfigEntry) -> None:
    """Reload the config entry when its data or options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SagerConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
