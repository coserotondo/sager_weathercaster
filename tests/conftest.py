"""Fixtures for Sager Weathercaster tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant

from custom_components.sager_weathercaster.const import (
    CONF_PRESSURE_ENTITY,
    CONF_WIND_DIR_ENTITY,
    DOMAIN,
)

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
    "open_meteo": {
        "available": False,
        "hourly": [],
        "daily": [],
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
