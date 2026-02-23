# Sager Weathercaster

A Home Assistant custom integration that produces a **locally-computed, sensor-driven weather forecast** using the [Sager Weathercaster algorithm](https://en.wikipedia.org/wiki/Sager_Weathercaster) — a 19th-century barometric forecasting wheel that remains surprisingly accurate for 12–48 hour predictions.

Sager is the **primary and authoritative** source for conditions. The free [Open-Meteo API](https://open-meteo.com/) enriches the forecast with precise temperatures, humidity, wind, and extends the outlook to 7 days and beyond 48 hours of hourly data. No API key is required. Open-Meteo can be disabled at any time to keep the integration fully local.

---

## Features

- **Weather entity** with full Home Assistant weather card support
  - **7-day daily forecast**: Days 1–2 from Sager (condition) + Open-Meteo (temperature); Day 3 blended; Days 4–7 from Open-Meteo
  - **Hourly forecast (48 h+)**: Sager-primary for 0–48 h, extended by Open-Meteo beyond 48 h
  - All standard weather fields: temperature, precipitation probability, wind speed & direction, cloud cover, humidity, dew point, UV index, apparent temperature
- **Sager forecast sensor** — translated semantic forecast text (e.g., "Fair", "Precipitation or showers followed by improvement within 12 hours")
- **Forecast reliability sensor** — percentage score based on how many critical sensors are configured and providing valid data
- **Zambretti algorithm cross-validation** — independent barometric forecast used to validate and adjust Sager confidence
- **Hemisphere and latitude-zone aware** — Northern/Southern Polar, Temperate, Tropical zones, using your HA home location automatically
- **Sky-irradiance auto-detection** — point the cloud cover field at a solar lux (`lx`) or solar irradiance (`W/m²`) sensor; the integration auto-detects the unit and converts to cloud cover % via the Kasten & Czeplak clear-sky model. Solar irradiance (W/m²) is the most accurate input as the model was designed for irradiance
- **Atmospheric turbidity correction** — when a dewpoint (or humidity + temperature) sensor is configured, the Hänel hygroscopic aerosol model adjusts the clear-sky baseline for local atmospheric moisture, improving accuracy on humid or Mediterranean days
- **Clear-sky auto-calibration** — when Open-Meteo reports ≤ 5 % cloud cover and sun elevation ≥ 15°, a site-specific calibration factor is learned via exponential moving average and applied to all subsequent conversions
- **Temperature-based precipitation refinement** — codes that indicate showers vs. flurries are automatically split based on your temperature sensor (threshold: 2 °C)
- **Optional Open-Meteo integration** — disable via the Configure button to run fully local with no cloud calls
- **Graceful degradation** — Open-Meteo errors fall back to stale data, then to local-only. The hourly tab never spins with a loading circle
- **No external Python dependencies** — uses `aiohttp` (already in HA) for Open-Meteo; no pip packages required

---

## How it works

### Forecast hierarchy

```
Sager algorithm  ──► Day 1 condition (authoritative)
                 ──► Day 2 condition (via FORECAST_EVOLUTION table)
                 ──► Hourly 0–48 h condition + wind trend + cloud level

Zambretti        ──► Cross-validates Sager → adjusts confidence score
                     (agree / close / diverge / conflict)

Open-Meteo API   ──► Day 1–2 temperature max/min (replaces sensor ± trend)
                 ──► Day 3 blended condition (40 % Sager, 60 % OM)
                 ──► Days 4–7 condition + all numerical fields
                 ──► Hourly 0–48 h: overlays temperature, wind, humidity,
                     cloud cover, UV, apparent temp, dew point on Sager slots
                 ──► Hourly 48 h+: pure Open-Meteo
```

### Sager algorithm inputs

The Sager Weathercaster uses five barometric observations to look up a forecast in a ~4 991-entry table (the full OpenHAB lookup table):

| # | Variable | Derived from |
|---|----------|-------------|
| 1 | Pressure level (1–8) | Current pressure in hPa |
| 2 | Wind direction (8-point) | Current wind direction |
| 3 | Wind trend (Steady / Veering / Backing) | Current vs. 6 h-ago wind direction |
| 4 | Pressure trend (Rising Rapidly → Decreasing Rapidly) | 6 h pressure change |
| 5 | Cloud level (Clear → Raining) | Cloud cover % or lux |

### Hourly forecast construction

When Open-Meteo is available, the hourly tab shows real API data enriching the Sager baseline. When unavailable (or disabled), a fully synthetic 48-slot forecast is generated from the Sager signals so the tab never shows a loading spinner:

- **Condition**: Sager day-1 code for h 0–24, day-2 evolved code for h 24–48
- **Temperature**: linear trend toward Sager's day-2 temperature target + ±3 °C diurnal curve (peak 14:00, trough 02:00)
- **Wind speed**: extrapolated from the current sensor reading by Sager's `wind_velocity_key` — Beaufort-level keys (`moderate_to_fresh`, `gale`, …) lerp toward their speed midpoint; relative keys (`probably_increasing`, `decreasing_or_moderate`) apply a 50 % change over 24 h
- **Cloud cover**: smooth transition current → Sager `cloud_level` % over 12 h, then to day-2 condition-implied % at h 24
- **Humidity**: same smooth transition pattern

---

## Installation

### Via HACS (recommended)

1. Open HACS in your Home Assistant instance.
2. Go to **Integrations** → **⋮** (three dots) → **Custom repositories**.
3. Add `https://github.com/coserotondo/sager_weathercaster` as an **Integration** repository.
4. Search for **Sager Weathercaster** and install it.
5. Restart Home Assistant.

### Manual

1. Download or clone this repository.
2. Copy the `custom_components/sager_weathercaster` folder to your HA `config/custom_components/` directory.
3. Restart Home Assistant.

---

## Removing the integration

1. Go to **Settings → Devices & Services**.
2. Find the **Sager Weathercaster** integration and click it.
3. Click the **⋮** (three dots) menu and select **Delete**.
4. Restart Home Assistant to ensure all entities are removed cleanly.

If you installed via HACS, also remove the integration from HACS:

1. Open HACS → **Integrations**.
2. Search for **Sager Weathercaster**, click it, and select **Remove**.

---

## Configuration

### Initial setup

Go to **Settings → Devices & Services → Add Integration** and search for **Sager Weathercaster**.

### Changing sensors or the name (Reconfigure)

Click the **⋮** (three dots) next to the integration entry and select **Reconfigure**. All sensor fields and the instance name can be changed here at any time. The integration reloads automatically on save.

### Behavioral options (Configure)

Click **Configure** on the integration card to open the options:

| Option | Default | Description |
|--------|---------|-------------|
| **Enable Open-Meteo integration** | On | Fetches hourly and 7-day data from open-meteo.com (free, no API key). Disabling makes the integration fully local — useful for air-gapped setups or to reduce cloud calls. |

---

### Required sensors

| Field | Description | Unit |
|-------|-------------|------|
| **Atmospheric pressure** | Current barometric pressure | hPa |
| **Wind direction** | Current wind direction (0–360 °, 0 = North) | ° |

### Recommended sensors (significantly improve accuracy)

| Field | Description | Unit |
|-------|-------------|------|
| **Historic wind direction** | Wind direction from 6 hours ago — needed for wind trend (Veering / Backing / Steady) | ° |
| **Pressure change** | Pressure change over the last 6 hours — needed for pressure trend | hPa |
| **Cloud cover** | Cloud cover **or** solar lux (see below) | % or lx |
| **Wind speed** | Current wind speed | km/h |

### Optional sensors

| Field | Description | Unit |
|-------|-------------|------|
| **Rain sensor** | Numeric (mm/h) → distinguishes rainy (≥ 0.1 mm/h) / pouring (≥ 7.5 mm/h); binary (`on`/`off`) → simple rain flag | mm/h or on/off |
| **Temperature** | Used for shower vs. flurry detection (< 2 °C → flurries) and weather entity current temperature | °C |
| **Humidity** | Current relative humidity shown on weather entity; used as fallback moisture input for turbidity correction when no dewpoint sensor is configured | % |
| **Dewpoint** | Dewpoint temperature — preferred atmospheric moisture input for the turbidity correction; more accurate than deriving moisture from separate T + RH sensors | °C |

### Cloud cover: sky-sensor auto-detection

The integration auto-detects the input type from the `unit_of_measurement` attribute of the configured entity:

| Unit | Behaviour |
|------|-----------|
| `%` | Used directly as cloud cover percentage |
| `lx` | Converted via the Kasten & Czeplak clear-sky illuminance model (coefficient 172 278 lx) |
| `W/m²` | Converted via the same model using the mean solar constant (1361 W/m²) — **most accurate** because the model was designed for irradiance |

For `lx` and `W/m²` inputs the conversion pipeline is:

1. Sun elevation is read from `sun.sun`
2. Theoretical clear-sky value is calculated for that elevation and input type
3. **Turbidity correction** scales the clear-sky estimate for local atmospheric moisture (see below)
4. **Site calibration factor** applies a learned site-specific offset (see below)
5. Cloud cover = `log(calibrated_clear_sky / measured) × 100`, clamped 0–100 %
6. At night / twilight (elevation ≤ 5°), falls back to Open-Meteo current cloud cover or 50 %

No separate configuration is needed — just point the cloud cover field at your sensor.

#### Atmospheric turbidity correction

Humid air and hygroscopic aerosols scatter sunlight before it reaches the sensor, making even a clear sky read "dimmer" than the standard model expects. The integration corrects for this using the Hänel (1976) aerosol growth model, applying a reduction factor of up to 40 % under very humid conditions.

Moisture input priority:

| Priority | Source | Notes |
|----------|--------|-------|
| 1 | **Dewpoint sensor** (`CONF_DEWPOINT_ENTITY`) | Most direct — single measurement, no drift accumulation |
| 2 | **Temperature + humidity** | Derives actual vapor pressure via the Alduchov-Eskridge formula |
| 3 | **Humidity only** | Normalized RH approximation |
| 4 | None | Turbidity factor = 1.0 (no correction) |

#### Clear-sky auto-calibration

Even after turbidity correction, site-specific factors (aerosol type, dust, altitude, sensor cosine response) introduce a residual offset. When Open-Meteo reports ≤ 5 % cloud cover and sun elevation ≥ 15°, the integration updates a site calibration factor via exponential moving average (α = 0.15). This factor persists in memory for the lifetime of the coordinator and converges after a handful of clear-sky readings.

### Sensor reliability and weights

The **Forecast reliability** sensor (0–100 %) reflects how completely the integration is fed:

| Sensor | Weight |
|--------|--------|
| Atmospheric pressure | 20 % |
| Historic wind direction | 20 % |
| Pressure change | 20 % |
| Wind direction | 15 % |
| Cloud cover | 15 % |
| Wind speed | 10 % |

---

## Sensor setup: Ecowitt PWS example

This section shows exactly which entities to configure for each field, using an **Ecowitt local PWS** (via the [Ecowitt](https://www.home-assistant.io/integrations/ecowitt/) integration) as the reference hardware. The same principles apply to any PWS — adapt entity IDs accordingly.

### Why some sensors need derived templates

Two of the five Sager inputs require **time-averaged or historically-queried** values that raw PWS sensors cannot provide directly:

| Input | Why a raw sensor is not enough |
|-------|-------------------------------|
| **Wind direction (current)** | Instantaneous readings jump with gusts; Ecowitt's built-in `_10m_avg` uses **scalar** angle averaging, which breaks near 0°/360° (e.g., wind between 350° and 10° gives 180° instead of 0°). You need **vector** (sin/cos) averaging. |
| **Historic wind direction (6 h ago)** | Standard entities only expose the current state. A SQL sensor reads the value that was stored in the HA database 6 hours ago. |
| **Pressure change (6 h)** | A `statistics` helper computes the change in pressure over a rolling 360-minute window. |
| **Wind speed (current)** | The vector-average speed (magnitude of the averaged sin/cos components) gives the sustained directional component, not noisy instantaneous gusts. |

### Package YAML — copy this into `packages/weather.yaml`

```yaml
template:
  - sensor:
      # Intermediate sin/cos components — used to build the vector average
      - name: "weather_wind_sin"
        unit_of_measurement: ""
        state: >
          {{ (float(states('sensor.pws_wind_speed'), 0)
              * sin(float(states('sensor.pws_wind_direction'), 0) * pi / 180))
             | round(4) }}
        availability: >
          {{ states('sensor.pws_wind_speed') | is_number
             and states('sensor.pws_wind_direction') | is_number }}

      - name: "weather_wind_cos"
        unit_of_measurement: ""
        state: >
          {{ (float(states('sensor.pws_wind_speed'), 0)
              * cos(float(states('sensor.pws_wind_direction'), 0) * pi / 180))
             | round(4) }}
        availability: >
          {{ states('sensor.pws_wind_speed') | is_number
             and states('sensor.pws_wind_direction') | is_number }}

      # Vector-averaged wind direction — mathematically correct circular mean
      - name: "Weather Wind Average Direction"
        unit_of_measurement: "°"
        state: >
          {% set s = states('sensor.weather_wind_sin_avg') | float(none) %}
          {% set c = states('sensor.weather_wind_cos_avg') | float(none) %}
          {% if s is not none and c is not none %}
            {{ ((atan2(-s, -c) * 180 / pi) + 180) | round(0) % 360 }}
          {% else %}
            unavailable
          {% endif %}
        availability: >
          {{ is_number(states('sensor.weather_wind_sin_avg'))
             and is_number(states('sensor.weather_wind_cos_avg')) }}

      # Vector-average wind speed — sustained directional component
      - name: "Weather Wind Average Speed"
        unit_of_measurement: "km/h"
        icon: mdi:weather-windy
        state: >
          {{ sqrt(float(states('sensor.weather_wind_sin_avg'), 0) ** 2
                  + float(states('sensor.weather_wind_cos_avg'), 0) ** 2)
             | round(1) }}

sensor:
  # 6-hour pressure change — rolling window of 360 minutes
  - platform: statistics
    name: "Weather Relative Pressure Change"
    entity_id: sensor.pws_relative_pressure
    state_characteristic: change
    max_age:
      minutes: 360

  # 5-minute rolling mean of sin/cos components
  - platform: statistics
    name: "weather_wind_sin_avg"
    entity_id: sensor.weather_wind_sin
    state_characteristic: mean
    max_age:
      minutes: 5
    precision: 4

  - platform: statistics
    name: "weather_wind_cos_avg"
    entity_id: sensor.weather_wind_cos
    state_characteristic: mean
    max_age:
      minutes: 5
    precision: 4

sql:
  # Historic wind direction: the vector-average value recorded 6 hours ago
  - name: weather_wind_average_direction_historic
    query: >
      SELECT states.state
      FROM states
      INNER JOIN states_meta
        ON states.metadata_id = states_meta.metadata_id
      WHERE states_meta.entity_id = 'sensor.weather_wind_average_direction'
        AND last_updated_ts <= strftime('%s', 'now', '-6 hours')
      ORDER BY last_updated_ts DESC
      LIMIT 1;
    column: "state"
```

> **Prerequisite**: the `sql` integration requires the [SQL](https://www.home-assistant.io/integrations/sql/) integration enabled and the `recorder` component writing to a SQLite database (the default).

### Integration configuration — field mapping

| Integration field | Ecowitt entity to use | Notes |
|-------------------|-----------------------|-------|
| **Atmospheric pressure** | `sensor.pws_relative_pressure` | Use **relative** (sea-level) pressure, not `pws_absolute_pressure` (station altitude would skew pressure-level classification) |
| **Wind direction** | `sensor.weather_wind_average_direction` | Vector-average template (see package above) |
| **Historic wind direction** | `sensor.weather_wind_average_direction_historic` | SQL sensor from package above |
| **Pressure change** | `sensor.weather_relative_pressure_change` | Statistics sensor from package above |
| **Cloud cover** | `sensor.pws_solar_radiation` (W/m²) **or** `sensor.pws_solar_lux` (lx) | Prefer the irradiance sensor when available — unit is auto-detected; at night / elevation ≤ 5° falls back to Open-Meteo |
| **Wind speed** | `sensor.weather_wind_average_speed` | Vector-average speed template (see package above) |
| **Rain sensor** | `sensor.pws_rain_rate_piezo` | Unit `mm/h` → integration distinguishes rainy (≥ 0.1 mm/h) vs. pouring (≥ 7.5 mm/h); binary sensors (`on`/`off`) are also supported |
| **Temperature** | `sensor.pws_outdoor_temperature` | Used for shower/flurry split (< 2 °C → flurries) and weather entity current temperature |
| **Humidity** | `sensor.pws_humidity` | Shown on weather entity; fallback moisture input for turbidity correction |
| **Dewpoint** | `sensor.pws_dewpoint` | Preferred moisture input for turbidity correction (more accurate than T + RH) |

### Why relative pressure, not absolute?

Sager maps current pressure to one of 8 levels (Very High → Extremely Low) calibrated to sea-level values (roughly 975–1030 hPa). `pws_absolute_pressure` is uncorrected station pressure — at 100 m altitude it reads ~12 hPa lower, which would permanently shift the pressure level down by one or two steps.

---

## Produced entities

### Weather entity

The main entity visible in the **weather card**. Provides:

- Current condition, temperature, pressure, humidity, wind speed & bearing
- **Daily forecast** (7 days when Open-Meteo is reachable or enabled, 3 days local-only)
- **Hourly forecast** (up to 7 days when Open-Meteo is reachable, 48 h synthetic local-only)

The attribution shown on the weather card reflects the active data sources:
- Open-Meteo enabled and live: *"Sager Weathercaster Algorithm; weather data by Open-Meteo (open-meteo.com)"*
- Open-Meteo disabled or unreachable: *"Sager Weathercaster Algorithm"*

Extra state attributes (visible in Developer Tools → States):

| Attribute | Description |
|-----------|-------------|
| `sager_forecast` | Raw Sager letter code (a–y with optional suffix) |
| `pressure_level` | Pressure level 1–8 |
| `wind_trend` | STEADY / VEERING / BACKING |
| `pressure_trend` | Rising Rapidly → Decreasing Rapidly |
| `cloud_level` | Clear / Partly Cloudy / Mostly Cloudy / Overcast / Raining |
| `confidence` | Algorithm confidence 30–99 % |
| `wind_velocity` | Predicted wind velocity category |
| `wind_direction` | Predicted wind direction quadrant |
| `latitude_zone` | Northern/Southern Polar/Temperate/Tropical |
| `cross_validation` | agree / close / diverge / conflict (Sager vs. Zambretti) |
| `zambretti_condition` | Zambretti HA condition |
| `zambretti_forecast` | Zambretti textual forecast key |
| `open_meteo_available` | Whether Open-Meteo data is current |
| `open_meteo_day1_agreement` | agree / differ — Sager vs. OM day-1 condition |
| `open_meteo_day1_condition` | Open-Meteo's day-1 condition for comparison |
| `current_wind_name` | Current wind name |
| `forecast_wind_name` | Forecast wind name |

### Sager forecast sensor

State: one of the translated forecast codes below.

Extra attributes mirror the weather entity plus `raw_data` (all sensor values) and `last_update` timestamp.

#### Forecast code reference

| Code | Description |
|------|-------------|
| `a` | Fair |
| `b` | Fair and warmer |
| `c` | Fair and cooler |
| `d` | Unsettled |
| `e` | Unsettled and warmer |
| `f` | Unsettled and cooler |
| `g` / `g1` / `g2` | Increasing cloudiness → precipitation / showers / flurries |
| `h` | Increasing cloudiness → precipitation or showers and warmer |
| `j` / `j1` / `j2` | Showers / Flurries |
| `k` / `k1` / `k2` | Showers/flurries and warmer |
| `l` / `l1` / `l2` | Showers/flurries and cooler |
| `m` | Precipitation |
| `n` | Precipitation and warmer |
| `p` | Precipitation, turning cooler; improvement likely in 24 h |
| `r` / `r1` / `r2` | Precipitation → improvement within 12 h |
| `s` / `s1` / `s2` | Precipitation → improvement within 12 h and cooler |
| `t` / `t1` / `t2` | Precipitation → improvement within 6 h |
| `u` / `u1` / `u2` | Precipitation → improvement within 6 h and cooler |
| `w` / `w1` / `w2` | Precipitation → fair within 6 h and cooler |
| `x` | Unsettled → fair |
| `y` | Unsettled → fair within 6 h and cooler |

Codes ending in `1` = showers (temperature ≥ 2 °C), `2` = flurries (temperature < 2 °C).

### Forecast reliability sensor

State: 0–100 % score.

Extra attributes show per-sensor status (`ok` / `unavailable` / `not configured`) for each of the six weighted inputs, plus Open-Meteo API status and `open_meteo_last_updated` timestamp.

| `open_meteo` attribute value | Meaning |
|------------------------------|---------|
| `available` | Last fetch succeeded and data is current |
| `stale` | Last fetch succeeded but the data is older than 30 min |
| `not_fetched` | Enabled but no successful fetch yet (e.g., just started) |
| `disabled` | Open-Meteo has been turned off in options |

---

## Update intervals

| Source | Interval |
|--------|----------|
| Sager + Zambretti algorithm | Every 10 minutes |
| Open-Meteo API | Every 30 minutes (when enabled) |

Open-Meteo data is cached between 30-minute fetches. On API failure, the last successful response is retained until a new fetch succeeds (stale data mode). If the API has never been reached, or if it is disabled, the integration runs in local-only mode.

---

## Open-Meteo API

This integration uses the [Open-Meteo public forecast API](https://open-meteo.com/en/docs):

- **Free for non-commercial use** — no API key, no registration
- Fetches `forecast_days=7`, hourly and daily parameters
- Hourly: temperature, humidity, dew point, apparent temperature, precipitation probability, precipitation, weather code (WMO), cloud cover, wind speed & direction, gusts, UV index, is_day
- Daily: weather code, temperature max/min, precipitation sum, precipitation probability max, wind speed max, wind direction dominant, cloud cover mean, UV index max
- All requests use your HA home coordinates (latitude / longitude)
- No new Python package dependency — uses `aiohttp` already shipped with Home Assistant
- Can be disabled via **Configure** to keep the integration fully local

---

## Latitude zone support

The integration adjusts the Sager wind direction mapping and the Zambretti backing/veering logic for your geographic zone:

| Zone | Latitude |
|------|----------|
| Northern Polar | ≥ 66.6 °N |
| Northern Temperate | 23.5 °N – 66.6 °N (standard Sager) |
| Northern Tropical | 0 – 23.5 °N |
| Southern Tropical | 0 – 23.5 °S |
| Southern Temperate | 23.5 °S – 66.6 °S |
| Southern Polar | ≥ 66.6 °S |

Your zone is detected automatically from the HA home location and shown in the `latitude_zone` attribute.

---

## Architecture notes (developer memory)

```
__init__.py         Entry point, sets up coordinator, forwards to SENSOR + WEATHER platforms
config_flow.py      SagerWeathercasterConfigFlow (user + reconfigure steps):
                      async_step_user()         initial setup — sensors + name
                      async_step_reconfigure()  update sensors + name at any time
                    SagerWeathercasterOptionsFlow (init step):
                      async_step_init()         Open-Meteo enable/disable toggle
coordinator.py      DataUpdateCoordinator (10 min):
                      _get_sensor_data()        reads all entities, sky→cloud conversion,
                                                binary + numeric rain detection
                      _sky_to_cloud_cover()     Kasten & Czeplak model for lx and W/m²
                                                inputs; applies turbidity + calibration
                      _local_turbidity_factor() Hänel aerosol model: dewpoint > T+RH >
                                                RH-only priority chain
                      _sager_algorithm()        ~4991-entry OpenHAB table lookup →
                                                forecast_code, wind_code
                      _zambretti_forecast()     independent barometric forecast
                      _cross_validate()         adjusts confidence based on Sager/Zambretti
                      _calculate_reliability()  0–100 % score from configured sensors
                      _async_fetch_open_meteo() 30-min interval, skipped when disabled,
                                                retry on failure, stale fallback
const.py            All constants: forecast tables, translation keys, WMO mapping,
                    sky-irradiance conversion coefficients (lux + W/m²),
                    Open-Meteo parameter lists
open_meteo.py       Lightweight aiohttp client → OpenMeteoData dataclass
                    (OpenMeteoHourlyEntry, OpenMeteoDailyEntry)
sager_table.py      Sager Weathercaster full forecast lookup table
sensor.py           SagerSensor (enum, forecast code), SagerReliabilitySensor (% score)
weather.py          SagerWeatherEntity (SingleCoordinatorWeatherEntity):
                      attribution           dynamic — credits Open-Meteo when live
                      condition             from rain sensor → cloud cover → OM fallback
                      _async_forecast_daily()
                        _generate_daily_forecast()   days 1–2 Sager+OM temp, day 3 blend,
                                                     days 4–7 OM
                      _async_forecast_hourly()
                        _generate_sager_hourly_forecast()   always available, 48 slots
                        _enrich_hourly_with_open_meteo()    overlay OM, extend beyond 48 h
translations/       en.json, it.json — all forecast codes, Zambretti keys, attribute names,
                    options flow strings
```

### Key design decisions

1. **Sager is always primary** — condition for days 1–2 and hours 0–48 h comes from Sager, never replaced by Open-Meteo
2. **OM enriches numerical fields** — temperature, wind, cloud, humidity, UV, dew point on the Sager slots; all these are more accurate from a numerical weather model than sensor extrapolation
3. **Hourly never spins** — `_generate_sager_hourly_forecast` always produces 48 slots from current sensor data, even with no internet
4. **Smooth transitions** — cloud cover and humidity transition from current sensor → Sager target over 12 h, then to day-2 target at h 24; prevents sudden jumps
5. **Wind extrapolation** — Beaufort-level keys (`moderate_to_fresh`, `gale`, …) lerp toward their speed midpoint (≤ 70 % of the way in 24 h); relative keys apply a ±50 % change
6. **No user-configurable polling intervals** — both intervals are integration-determined constants
7. **Sky-sensor auto-detection** — `unit_of_measurement` selects the conversion path: `lx` uses the luminance coefficient (172 278 lx), `W/m²` uses the solar constant (1361 W/m²); `%` is passed through unchanged; no separate config field needed
8. **Three-layer cloud-cover accuracy** — (1) physics-based turbidity factor from dewpoint / T+RH / RH; (2) Open-Meteo EMA site-calibration on confirmed clear-sky readings; (3) Kasten & Czeplak baseline with input-appropriate coefficient
9. **Hemisphere awareness** — backing/veering are reversed in the Southern Hemisphere
10. **Open-Meteo is optional** — disabled via options flow; coordinator skips all API calls, `open_meteo_result["disabled"]` propagates to sensor and weather entity; attribution reverts to local-only text
11. **Config flow separation** — sensor wiring goes in Reconfigure (updates `entry.data`); behavioral toggles go in Options flow (updates `entry.options`)

---

## Limitations

- Sager is a 19th-century empirical algorithm optimized for the **Northern Temperate** zone (roughly Europe and North America). Accuracy degrades at polar and tropical latitudes.
- The algorithm does not model fog, haze, thunderstorms, or local topographic effects.
- Forecast accuracy depends heavily on sensor quality, particularly pressure and its 6 h change.
- The Sager table covers ~4 991 combinations; uncommon inputs fall back to a default "Unstable" forecast with 60 % confidence.
- Hourly data beyond 48 h (Open-Meteo extension) is only as accurate as the underlying numerical weather model.

---

## Contributing

Pull requests and issues are welcome at [github.com/coserotondo/sager_weathercaster](https://github.com/coserotondo/sager_weathercaster).

---

## License

This project is licensed under the MIT License.

The Sager Weathercaster algorithm is in the public domain (originally published 1869).
Open-Meteo data is used under the [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) license.
