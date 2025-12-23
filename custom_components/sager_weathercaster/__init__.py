"""Sager Weathercaster - Home Assistant Integration."""

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import discovery
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Sager Weathercaster component."""
    if DOMAIN not in config:
        return True

    conf = config[DOMAIN]

    # Carica entrambe le piattaforme: sensor E weather
    _LOGGER.info("Loading Sager Weathercaster: sensor platform")
    hass.async_create_task(
        discovery.async_load_platform(hass, "sensor", DOMAIN, conf, config)
    )

    _LOGGER.info("Loading Sager Weathercaster: weather platform")
    hass.async_create_task(
        discovery.async_load_platform(hass, "weather", DOMAIN, conf, config)
    )

    _LOGGER.info("Sager Weathercaster integration successfully set up")
    return True
