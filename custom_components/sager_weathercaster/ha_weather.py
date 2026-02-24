"""HA weather entity adapter for the Sager Weathercaster integration."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

from homeassistant.components.weather import (
    DOMAIN as WEATHER_DOMAIN,
    WeatherEntityFeature,
)
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Bit flags for WeatherEntityFeature
_FORECAST_HOURLY = WeatherEntityFeature.FORECAST_HOURLY
_FORECAST_DAILY = WeatherEntityFeature.FORECAST_DAILY
_FORECAST_TWICE_DAILY = WeatherEntityFeature.FORECAST_TWICE_DAILY


@dataclass
class ExternalWeatherHourlyEntry:
    """One hourly forecast slot from an external HA weather entity.

    Field names use short, unit-neutral names (e.g. ``temperature``, not
    ``native_temperature``) because the ``native_`` prefix is an HA entity
    concern for unit-system conversion, which does not apply to internal DTOs.

    ``condition`` carries the HA condition string (e.g. ``"sunny"``).
    ``weather_code`` is always ``None`` for HA-sourced data; it exists so
    the ``_wmo_to_condition()`` fallback in weather.py is a harmless no-op
    and keeps the code open for future WMO-based external sources.
    """

    datetime: str
    temperature: float | None = None
    humidity: float | None = None
    dew_point: float | None = None
    apparent_temperature: float | None = None
    precipitation_probability: int | None = None
    precipitation: float | None = None
    condition: str | None = None
    weather_code: int | None = None  # always None for HA-sourced entries
    cloud_cover: int | None = None
    wind_speed: float | None = None
    wind_direction: float | None = None
    wind_gusts: float | None = None
    uv_index: float | None = None
    # Derived from datetime hour (06–20 = day) when is_daytime is absent.
    is_day: bool = True


@dataclass
class ExternalWeatherDailyEntry:
    """One daily forecast slot from an external HA weather entity."""

    datetime: str
    condition: str | None = None
    weather_code: int | None = None  # always None for HA-sourced entries
    temperature_max: float | None = None
    temperature_min: float | None = None
    precipitation_sum: float | None = None
    precipitation_probability_max: int | None = None
    wind_speed_max: float | None = None
    wind_direction_dominant: float | None = None
    cloud_cover_mean: int | None = None
    uv_index_max: float | None = None


@dataclass
class ExternalWeatherData:
    """Aggregated data returned by HAWeatherClient."""

    hourly: list[ExternalWeatherHourlyEntry] = field(default_factory=list)
    daily: list[ExternalWeatherDailyEntry] = field(default_factory=list)
    # Cloud cover reported in the entity's current state attributes (0-100 %).
    current_cloud_cover: int | None = None
    # Attribution string from the weather entity, if any.
    attribution: str | None = None


def _is_day_from_hour(dt_str: str) -> bool:
    """Return True when the ISO datetime string falls within 06:00–20:59 local hour."""
    try:
        # datetime strings are either "YYYY-MM-DDTHH:MM:SS[+tz]" or "YYYY-MM-DDTHH:MM"
        hour = int(dt_str[11:13])
    except (IndexError, ValueError):
        return True  # default to daytime on parse failure
    else:
        return 6 <= hour <= 20


def _parse_hourly(forecast_list: list[dict[str, Any]]) -> list[ExternalWeatherHourlyEntry]:
    """Convert a list of HA forecast dicts to ExternalWeatherHourlyEntry objects."""
    entries: list[ExternalWeatherHourlyEntry] = []
    for fc in forecast_list:
        dt = fc.get("datetime", "")
        if not dt:
            continue
        # is_daytime is present in twice_daily forecasts; derive from hour otherwise.
        is_daytime = fc.get("is_daytime")
        is_day = bool(is_daytime) if is_daytime is not None else _is_day_from_hour(dt)

        entries.append(
            ExternalWeatherHourlyEntry(
                datetime=dt,
                temperature=fc.get("native_temperature"),
                humidity=fc.get("humidity"),
                dew_point=fc.get("native_dew_point"),
                apparent_temperature=fc.get("native_apparent_temperature"),
                precipitation_probability=fc.get("precipitation_probability"),
                precipitation=fc.get("native_precipitation"),
                condition=fc.get("condition"),
                cloud_cover=fc.get("cloud_coverage"),
                wind_speed=fc.get("native_wind_speed"),
                wind_direction=fc.get("wind_bearing"),
                wind_gusts=fc.get("native_wind_gust_speed"),
                uv_index=fc.get("uv_index"),
                is_day=is_day,
            )
        )
    return entries


def _parse_daily(forecast_list: list[dict[str, Any]]) -> list[ExternalWeatherDailyEntry]:
    """Convert a list of HA daily forecast dicts to ExternalWeatherDailyEntry objects."""
    entries: list[ExternalWeatherDailyEntry] = []
    for fc in forecast_list:
        dt = fc.get("datetime", "")
        if not dt:
            continue
        entries.append(
            ExternalWeatherDailyEntry(
                datetime=dt,
                condition=fc.get("condition"),
                temperature_max=fc.get("native_temperature"),
                temperature_min=fc.get("native_templow"),
                precipitation_sum=fc.get("native_precipitation"),
                precipitation_probability_max=fc.get("precipitation_probability"),
                wind_speed_max=fc.get("native_wind_speed"),
                wind_direction_dominant=fc.get("wind_bearing"),
                cloud_cover_mean=fc.get("cloud_coverage"),
                uv_index_max=fc.get("uv_index"),
            )
        )
    return entries


class HAWeatherClient:
    """Read forecast data from a Home Assistant weather entity."""

    def __init__(self, hass: HomeAssistant, entity_id: str) -> None:
        """Initialise the client for the given weather entity."""
        self._hass = hass
        self._entity_id = entity_id

    async def async_get_data(self) -> ExternalWeatherData | None:
        """Fetch current state and forecasts from the weather entity.

        Returns None when the entity does not exist or is unavailable.
        """
        state = self._hass.states.get(self._entity_id)
        if state is None or state.state in ("unavailable", "unknown"):
            _LOGGER.debug(
                "Weather entity %s is not available (state=%s)",
                self._entity_id,
                state.state if state else "missing",
            )
            return None

        attrs = state.attributes

        # Current cloud cover from the entity's attributes (may be absent).
        current_cloud: int | None = attrs.get("cloud_coverage")
        attribution: str | None = attrs.get("attribution")

        supported: int = attrs.get("supported_features", 0)

        hourly_entries: list[ExternalWeatherHourlyEntry] = []
        daily_entries: list[ExternalWeatherDailyEntry] = []

        # --- Hourly (prefer true hourly; fall back to twice-daily) ---
        if supported & _FORECAST_HOURLY:
            hourly_entries = await self._fetch_forecast("hourly")
        elif supported & _FORECAST_TWICE_DAILY:
            hourly_entries = await self._fetch_forecast("twice_daily")

        # --- Daily ---
        if supported & _FORECAST_DAILY:
            daily_entries = await self._fetch_daily()

        _LOGGER.debug(
            "External weather data fetched from %s: %d hourly, %d daily entries",
            self._entity_id,
            len(hourly_entries),
            len(daily_entries),
        )

        return ExternalWeatherData(
            hourly=hourly_entries,
            daily=daily_entries,
            current_cloud_cover=current_cloud,
            attribution=attribution,
        )

    async def _fetch_forecast(self, forecast_type: str) -> list[ExternalWeatherHourlyEntry]:
        """Call weather.get_forecasts and parse the response as hourly entries."""
        try:
            response: dict[str, Any] = await self._hass.services.async_call(
                WEATHER_DOMAIN,
                "get_forecasts",
                {"type": forecast_type},
                blocking=True,
                return_response=True,
                target={"entity_id": self._entity_id},
            )
        except Exception:  # noqa: BLE001
            # weather.get_forecasts is handled by arbitrary third-party
            # integrations that may raise any exception; catch broadly so a
            # misbehaving weather entity never crashes the coordinator.
            _LOGGER.debug(
                "Failed to fetch %s forecast from %s",
                forecast_type,
                self._entity_id,
                exc_info=True,
            )
            return []

        forecast_list: list[dict[str, Any]] = (
            response.get(self._entity_id, {}).get("forecast") or []
        )
        return _parse_hourly(forecast_list)

    async def _fetch_daily(self) -> list[ExternalWeatherDailyEntry]:
        """Call weather.get_forecasts for daily data and parse the response."""
        try:
            response: dict[str, Any] = await self._hass.services.async_call(
                WEATHER_DOMAIN,
                "get_forecasts",
                {"type": "daily"},
                blocking=True,
                return_response=True,
                target={"entity_id": self._entity_id},
            )
        except Exception:  # noqa: BLE001
            # Same broad-catch rationale as _fetch_forecast.
            _LOGGER.debug(
                "Failed to fetch daily forecast from %s",
                self._entity_id,
                exc_info=True,
            )
            return []

        forecast_list: list[dict[str, Any]] = (
            response.get(self._entity_id, {}).get("forecast") or []
        )
        return _parse_daily(forecast_list)
