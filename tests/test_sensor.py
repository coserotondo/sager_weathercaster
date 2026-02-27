"""Tests for Sager Weathercaster sensor entities."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant

from custom_components.sager_weathercaster.const import DOMAIN
from custom_components.sager_weathercaster.sensor import (
    SagerReliabilitySensor,
    SagerSensor,
)

from .conftest import MOCK_COORDINATOR_DATA


def _make_coordinator(hass: HomeAssistant, data: dict | None) -> MagicMock:
    """Return a mock coordinator with the given data and success state."""
    coordinator = MagicMock()
    coordinator.hass = hass
    coordinator.data = data
    coordinator.last_update_success = data is not None
    coordinator.sky_calibration_factor = 1.0
    coordinator.calibration_seed = None
    return coordinator


def _make_entry(entry_id: str = "test_entry") -> MagicMock:
    """Return a minimal mock config entry."""
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.title = "Sager Weather"
    return entry


# ── SagerSensor ───────────────────────────────────────────────────────────────


def test_sager_sensor_native_value(hass: HomeAssistant) -> None:
    """Test that native_value returns the forecast code from coordinator data."""
    coordinator = _make_coordinator(hass, MOCK_COORDINATOR_DATA)
    sensor = SagerSensor(coordinator, _make_entry())

    assert sensor.native_value == "a"


def test_sager_sensor_native_value_no_data(hass: HomeAssistant) -> None:
    """Test that native_value returns None when coordinator has no data."""
    coordinator = _make_coordinator(hass, None)
    sensor = SagerSensor(coordinator, _make_entry())

    assert sensor.native_value is None


def test_sager_sensor_extra_state_attributes(hass: HomeAssistant) -> None:
    """Test that extra_state_attributes includes expected forecast keys."""
    coordinator = _make_coordinator(hass, MOCK_COORDINATOR_DATA)
    sensor = SagerSensor(coordinator, _make_entry())

    attrs = sensor.extra_state_attributes
    assert "pressure_level" in attrs
    assert "wind_trend" in attrs
    assert "pressure_trend" in attrs
    assert "cloud_level" in attrs
    assert "confidence" in attrs
    assert "zambretti_forecast" in attrs
    assert "raw_data" not in attrs
    assert attrs["cloud_cover"] == 10.0
    assert attrs["sky_calibration_factor"] == 1.0
    assert attrs["calibration_seed"] is None


def test_sager_sensor_extra_state_attributes_no_data(hass: HomeAssistant) -> None:
    """Test that extra_state_attributes is empty when coordinator has no data."""
    coordinator = _make_coordinator(hass, None)
    sensor = SagerSensor(coordinator, _make_entry())

    assert sensor.extra_state_attributes == {}


def test_sager_sensor_unique_id(hass: HomeAssistant) -> None:
    """Test that the unique ID is derived from the entry ID."""
    coordinator = _make_coordinator(hass, MOCK_COORDINATOR_DATA)
    sensor = SagerSensor(coordinator, _make_entry("my_entry"))

    assert sensor.unique_id == "my_entry_forecast"


# ── SagerReliabilitySensor ────────────────────────────────────────────────────


def test_reliability_sensor_native_value(hass: HomeAssistant) -> None:
    """Test that the reliability score is returned from coordinator data."""
    coordinator = _make_coordinator(hass, MOCK_COORDINATOR_DATA)
    sensor = SagerReliabilitySensor(coordinator, _make_entry())

    assert sensor.native_value == 75


def test_reliability_sensor_native_value_no_data(hass: HomeAssistant) -> None:
    """Test that native_value is None (not 0) when coordinator has no data."""
    coordinator = _make_coordinator(hass, None)
    sensor = SagerReliabilitySensor(coordinator, _make_entry())

    assert sensor.native_value is None


def test_reliability_sensor_external_weather_not_configured(hass: HomeAssistant) -> None:
    """Test external weather status shows 'not_configured' when no entity is set."""
    coordinator = _make_coordinator(hass, MOCK_COORDINATOR_DATA)
    sensor = SagerReliabilitySensor(coordinator, _make_entry())

    attrs = sensor.extra_state_attributes
    assert attrs.get("external_weather") == "not_configured"


def test_reliability_sensor_external_weather_available(hass: HomeAssistant) -> None:
    """Test external weather status shows 'available' when data is fresh."""
    import copy
    from datetime import datetime, timezone

    data = copy.deepcopy(MOCK_COORDINATOR_DATA)
    data["ext_weather"]["configured"] = True
    data["ext_weather"]["available"] = True
    data["ext_weather"]["last_updated"] = datetime.now(timezone.utc)
    coordinator = _make_coordinator(hass, data)
    sensor = SagerReliabilitySensor(coordinator, _make_entry())

    attrs = sensor.extra_state_attributes
    assert attrs.get("external_weather") == "available"
    assert "external_weather_last_updated" in attrs


def test_reliability_sensor_external_weather_stale(hass: HomeAssistant) -> None:
    """Test external weather status shows 'stale' when cached data exists."""
    import copy
    from datetime import datetime, timezone

    data = copy.deepcopy(MOCK_COORDINATOR_DATA)
    data["ext_weather"]["configured"] = True
    data["ext_weather"]["available"] = False
    data["ext_weather"]["last_updated"] = datetime.now(timezone.utc)
    coordinator = _make_coordinator(hass, data)
    sensor = SagerReliabilitySensor(coordinator, _make_entry())

    attrs = sensor.extra_state_attributes
    assert attrs.get("external_weather") == "stale"


def test_reliability_sensor_extra_attributes_no_data(hass: HomeAssistant) -> None:
    """Test that extra_state_attributes is empty when coordinator has no data."""
    coordinator = _make_coordinator(hass, None)
    sensor = SagerReliabilitySensor(coordinator, _make_entry())

    assert sensor.extra_state_attributes == {}


def test_reliability_sensor_unique_id(hass: HomeAssistant) -> None:
    """Test that the unique ID is derived from the entry ID."""
    coordinator = _make_coordinator(hass, MOCK_COORDINATOR_DATA)
    sensor = SagerReliabilitySensor(coordinator, _make_entry("my_entry"))

    assert sensor.unique_id == "my_entry_reliability"


# ── Forecast verification attributes ─────────────────────────────────────────


def test_reliability_sensor_verification_absent_before_first_result(
    hass: HomeAssistant,
) -> None:
    """Test that verification attrs are absent when no verification has run yet."""
    coordinator = _make_coordinator(hass, MOCK_COORDINATOR_DATA)
    sensor = SagerReliabilitySensor(coordinator, _make_entry())

    attrs = sensor.extra_state_attributes
    assert "forecast_accuracy" not in attrs
    assert "last_verification_score" not in attrs


def test_reliability_sensor_verification_present_after_result(
    hass: HomeAssistant,
) -> None:
    """Test that verification attrs appear once at least one verification has run."""
    import copy

    data = copy.deepcopy(MOCK_COORDINATOR_DATA)
    data["verification"] = {
        "rolling_accuracy": 75.0,
        "last_score": 75,
        "last_rain_correct": True,
        "last_cloud_delta": 1,
        "last_predicted_at": "2026-02-27T10:00:00+00:00",
        "last_verified_at": "2026-02-27T22:00:00+00:00",
        "verifications_count": 3,
        "pending_since": "2026-02-27T22:00:00+00:00",
    }
    coordinator = _make_coordinator(hass, data)
    sensor = SagerReliabilitySensor(coordinator, _make_entry())

    attrs = sensor.extra_state_attributes
    assert attrs["forecast_accuracy"] == 75.0
    assert attrs["forecast_verifications"] == 3
    assert attrs["last_verification_score"] == 75
    assert attrs["last_verification_rain_correct"] is True
    assert "last_verification_predicted_at" in attrs
    assert "last_verification_verified_at" in attrs
    assert "verification_pending_since" in attrs
