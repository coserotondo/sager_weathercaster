"""Open-Meteo API client for Sager Weathercaster."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
import logging
from typing import Any

import aiohttp

from .const import (
    OPEN_METEO_API_URL,
    OPEN_METEO_DAILY_PARAMS,
    OPEN_METEO_FORECAST_DAYS,
    OPEN_METEO_HOURLY_PARAMS,
    OPEN_METEO_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class OpenMeteoError(Exception):
    """Error communicating with Open-Meteo API."""


@dataclass
class OpenMeteoHourlyEntry:
    """Single hourly forecast entry from Open-Meteo."""

    datetime: str
    temperature: float | None = None
    humidity: float | None = None
    dew_point: float | None = None
    apparent_temperature: float | None = None
    precipitation_probability: int | None = None
    precipitation: float | None = None
    weather_code: int | None = None
    cloud_cover: int | None = None
    wind_speed: float | None = None
    wind_direction: float | None = None
    wind_gusts: float | None = None
    uv_index: float | None = None
    is_day: bool | None = None


@dataclass
class OpenMeteoDailyEntry:
    """Single daily forecast entry from Open-Meteo."""

    datetime: str
    weather_code: int | None = None
    temperature_max: float | None = None
    temperature_min: float | None = None
    precipitation_sum: float | None = None
    precipitation_probability_max: int | None = None
    wind_speed_max: float | None = None
    wind_direction_dominant: float | None = None
    cloud_cover_mean: int | None = None
    uv_index_max: float | None = None


@dataclass
class OpenMeteoData:
    """Parsed Open-Meteo API response."""

    hourly: list[OpenMeteoHourlyEntry] = field(default_factory=list)
    daily: list[OpenMeteoDailyEntry] = field(default_factory=list)
    current_cloud_cover: int | None = None
    latitude: float = 0.0
    longitude: float = 0.0
    elevation: float = 0.0
    timezone: str = "UTC"


class OpenMeteoClient:
    """Async client for the Open-Meteo free forecast API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        latitude: float,
        longitude: float,
    ) -> None:
        """Initialize the Open-Meteo client."""
        self._session = session
        self._latitude = latitude
        self._longitude = longitude

    async def async_get_forecast(self) -> OpenMeteoData:
        """Fetch hourly and daily forecast data from Open-Meteo.

        Raises:
            OpenMeteoError: On network or API errors.
        """
        params: dict[str, Any] = {
            "latitude": self._latitude,
            "longitude": self._longitude,
            "hourly": ",".join(OPEN_METEO_HOURLY_PARAMS),
            "daily": ",".join(OPEN_METEO_DAILY_PARAMS),
            "current": "cloud_cover",
            "timezone": "auto",
            "forecast_days": OPEN_METEO_FORECAST_DAYS,
        }

        try:
            async with self._session.get(
                OPEN_METEO_API_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=OPEN_METEO_TIMEOUT),
            ) as response:
                if response.status != 200:
                    text = await response.text()
                    raise OpenMeteoError(
                        f"API returned status {response.status}: {text[:200]}"
                    )
                data = await response.json()
        except TimeoutError as err:
            raise OpenMeteoError("Request timed out") from err
        except aiohttp.ClientError as err:
            raise OpenMeteoError(f"Connection error: {err}") from err

        return self._parse_response(data)

    def _parse_response(self, data: dict[str, Any]) -> OpenMeteoData:
        """Parse raw API JSON into structured data."""
        result = OpenMeteoData(
            latitude=data.get("latitude", 0.0),
            longitude=data.get("longitude", 0.0),
            elevation=data.get("elevation", 0.0),
            timezone=data.get("timezone", "UTC"),
        )

        # Parse current cloud cover
        current = data.get("current", {})
        if "cloud_cover" in current:
            with contextlib.suppress(ValueError, TypeError):
                result.current_cloud_cover = int(current["cloud_cover"])

        # Parse hourly data
        hourly = data.get("hourly", {})
        hourly_times = hourly.get("time", [])
        for i, time_str in enumerate(hourly_times):
            entry = OpenMeteoHourlyEntry(datetime=time_str)
            entry.temperature = _safe_float(hourly, "temperature_2m", i)
            entry.humidity = _safe_float(hourly, "relative_humidity_2m", i)
            entry.dew_point = _safe_float(hourly, "dew_point_2m", i)
            entry.apparent_temperature = _safe_float(hourly, "apparent_temperature", i)
            entry.precipitation_probability = _safe_int(
                hourly, "precipitation_probability", i
            )
            entry.precipitation = _safe_float(hourly, "precipitation", i)
            entry.weather_code = _safe_int(hourly, "weather_code", i)
            entry.cloud_cover = _safe_int(hourly, "cloud_cover", i)
            entry.wind_speed = _safe_float(hourly, "wind_speed_10m", i)
            entry.wind_direction = _safe_float(hourly, "wind_direction_10m", i)
            entry.wind_gusts = _safe_float(hourly, "wind_gusts_10m", i)
            entry.uv_index = _safe_float(hourly, "uv_index", i)
            is_day_val = _safe_int(hourly, "is_day", i)
            entry.is_day = bool(is_day_val) if is_day_val is not None else None
            result.hourly.append(entry)

        # Parse daily data
        daily = data.get("daily", {})
        daily_times = daily.get("time", [])
        for i, time_str in enumerate(daily_times):
            entry = OpenMeteoDailyEntry(datetime=time_str)
            entry.weather_code = _safe_int(daily, "weather_code", i)
            entry.temperature_max = _safe_float(daily, "temperature_2m_max", i)
            entry.temperature_min = _safe_float(daily, "temperature_2m_min", i)
            entry.precipitation_sum = _safe_float(daily, "precipitation_sum", i)
            entry.precipitation_probability_max = _safe_int(
                daily, "precipitation_probability_max", i
            )
            entry.wind_speed_max = _safe_float(daily, "wind_speed_10m_max", i)
            entry.wind_direction_dominant = _safe_float(
                daily, "wind_direction_10m_dominant", i
            )
            entry.cloud_cover_mean = _safe_int(daily, "cloud_cover_mean", i)
            entry.uv_index_max = _safe_float(daily, "uv_index_max", i)
            result.daily.append(entry)

        return result


def _safe_float(data: dict[str, Any], key: str, index: int) -> float | None:
    """Safely extract a float value from an array in the response."""
    values = data.get(key)
    if values is None or index >= len(values) or values[index] is None:
        return None
    with contextlib.suppress(ValueError, TypeError):
        return float(values[index])
    return None


def _safe_int(data: dict[str, Any], key: str, index: int) -> int | None:
    """Safely extract an int value from an array in the response."""
    values = data.get(key)
    if values is None or index >= len(values) or values[index] is None:
        return None
    with contextlib.suppress(ValueError, TypeError):
        return int(values[index])
    return None
