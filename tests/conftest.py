"""Fixtures for Sager Weathercaster tests."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.core import HomeAssistant

from custom_components.sager_weathercaster.const import (
    CONF_PRESSURE_ENTITY,
    CONF_WIND_DIR_ENTITY,
    DOMAIN,
)

# Point hass at the real config/ directory so it can find the custom component.
# config/custom_components/sager_weathercaster/ is the live integration directory.
_CONFIG_DIR = str(Path(__file__).parents[4] / "config")


@pytest.fixture(name="hass_config_dir")
def hass_config_dir_fixture() -> str:
    """Override the default test config dir to use the repo's config/ directory."""
    return _CONFIG_DIR


@pytest.fixture(autouse=True)
def enable_custom_integrations_fixture(enable_custom_integrations: None) -> None:
    """Enable custom integration loading for every test in this package."""


MOCK_PRESSURE_ENTITY = "sensor.mock_pressure"
MOCK_WIND_DIR_ENTITY = "sensor.mock_wind_dir"

# Minimal coordinator data returned by the Sager algorithm for a fair-weather scenario
MOCK_COORDINATOR_DATA: dict = {
    "sensor_data": {
        "pressure": 1020.0,
        "wind_direction": 270.0,
        "wind_speed": 15.0,
        "wind_historic": 270.0,
        "pressure_change": 0.5,
        "cloud_cover": 10.0,
        "raining": False,
        "temperature": 18.0,
        "humidity": 55.0,
    },
    "forecast": {
        "forecast_code": "a",
        "hpa_level": 2,
        "wind_dir": "W",
        "wind_trend": "STEADY",
        "cloud_level": "Clear",
        "pressure_trend": "Rising Slowly",
        "confidence": 80.0,
        "wind_velocity_key": "no_significant_change",
        "wind_direction_key": "w_or_nw",
        "latitude_zone": "Northern Temperate",
        "cross_validation": "agree",
        "zambretti_condition": "sunny",
    },
    "zambretti": {
        "zambretti_key": "settled_fine",
        "condition": "sunny",
    },
    "reliability": {
        "score": 75,
        "sensor_status": {
            "pressure": "ok",
            "wind_direction": "ok",
        },
    },
    "ext_weather": {
        "configured": False,
        "available": False,
        "hourly": [],
        "daily": [],
        "attribution": None,
        "last_updated": None,
    },
}


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Prevent the coordinator from running during config flow tests."""
    with patch(
        "custom_components.sager_weathercaster.async_setup_entry",
        return_value=True,
    ) as mock:
        yield mock


@pytest.fixture
def user_input_valid() -> dict[str, str]:
    """Return minimal valid user input for the config flow."""
    return {
        CONF_PRESSURE_ENTITY: MOCK_PRESSURE_ENTITY,
        CONF_WIND_DIR_ENTITY: MOCK_WIND_DIR_ENTITY,
    }


@pytest.fixture
def mock_coordinator_data() -> dict:
    """Return a sample coordinator data payload for entity tests."""
    return dict(MOCK_COORDINATOR_DATA)
