# Sager Weathercaster

A Home Assistant custom integration that produces a **locally-computed, sensor-driven weather forecast** using the [Sager Weathercaster algorithm](https://en.wikipedia.org/wiki/Sager_Weathercaster) — a 19th-century barometric forecasting wheel that remains surprisingly accurate for 12–48 hour predictions.

Sager is the **primary and authoritative** source for conditions. You can optionally connect any **Home Assistant weather entity** (Met.no, OpenWeatherMap, AccuWeather, etc.) to enrich the forecast with precise temperatures, humidity, wind data, and extend the outlook to 7 days and beyond 48 hours of hourly data. The external weather entity is fully optional — the integration runs entirely from local sensor data with no cloud calls when none is configured.

---

## Features

- **Weather entity** with full Home Assistant weather card support
  - **7-day daily forecast**: Days 1–2 from Sager (condition) + external weather entity (temperature); Day 3 blended; Days 4–7 from external weather entity
  - **Hourly forecast (48 h+)**: Sager-primary for 0–48 h, extended by external weather entity beyond 48 h
  - All standard weather fields: temperature, precipitation probability, wind speed & direction, cloud cover, humidity, dew point, UV index, apparent temperature
- **Sager forecast sensor** — translated semantic forecast text (e.g., "Fair", "Precipitation or showers followed by improvement within 12 hours")
- **Forecast reliability sensor** — percentage score based on how many critical sensors are configured and providing valid data
- **Zambretti algorithm cross-validation** — independent barometric forecast used to validate and adjust Sager confidence
- **Hemisphere and latitude-zone aware** — Northern/Southern Polar, Temperate, Tropical zones, using your HA home location automatically
- **Sky-irradiance auto-detection** — point the cloud cover field at a solar lux (`lx`) or solar irradiance (`W/m²`) sensor; the integration auto-detects the unit and converts to cloud cover % via the Kasten & Czeplak clear-sky model. Solar irradiance (W/m²) is the most accurate input as the model was designed for irradiance
- **Atmospheric turbidity correction** — when a dewpoint (or humidity + temperature) sensor is configured, the Hänel (1976) hygroscopic aerosol model adjusts the clear-sky baseline for local atmospheric moisture, improving accuracy on humid or Mediterranean days
- **Clear-sky auto-calibration** — when the external weather entity reports ≤ 5 % cloud cover and sun elevation ≥ 15°, a site-specific calibration factor is learned via exponential moving average and applied to all subsequent conversions
- **Temperature-based precipitation refinement** — codes that indicate showers vs. flurries are automatically split based on your temperature sensor (threshold: 2 °C)
- **Optional external weather entity** — select any existing HA weather entity via Configure; leave blank to run fully local with no cloud calls
- **Graceful degradation** — external weather errors fall back to stale data, then to local-only. The hourly tab never spins with a loading circle
- **No external Python dependencies** — reads data from already-configured HA weather entities via the standard `weather.get_forecasts` action; no additional pip packages required

---

## How it works

### Forecast hierarchy

```
Sager algorithm  ──► Day 1 condition (authoritative)
                 ──► Day 2 condition (via FORECAST_EVOLUTION table)
                 ──► Hourly 0–48 h condition + wind trend + cloud level

Zambretti        ──► Cross-validates Sager → adjusts confidence score
                     (agree / close / diverge / conflict)

External weather ──► Day 1–2 temperature max/min (replaces sensor ± trend)
entity (optional)──► Day 3 blended condition (40 % Sager, 60 % external)
                 ──► Days 4–7 condition + all numerical fields
                 ──► Hourly 0–48 h: overlays temperature, wind, humidity,
                     cloud cover, UV, apparent temp, dew point on Sager slots
                 ──► Hourly 48 h+: pure external weather
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

When an external weather entity is configured and available, the hourly tab shows its data enriching the Sager baseline. When unavailable (or not configured), a fully synthetic 48-slot forecast is generated from the Sager signals so the tab never shows a loading spinner:

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
| **Weather entity** | *(none)* | Select any `weather.*` entity already configured in HA (e.g., `weather.forecast_home` from Met.no, OWM, or AccuWeather). Its hourly and daily forecasts extend the Sager 48-hour window and calibrate the cloud-cover model during clear-sky periods. Leave blank to use Sager-only local data. |

---

### Required sensors

| Field | Description | Unit |
|-------|-------------|------|
| **Atmospheric pressure** | Current barometric pressure | hPa |
| **Wind direction** | Current wind direction (0–360 °, 0 = North) | ° |

> **No helper entities needed.** Wind trend and pressure trend are computed directly from your raw sensor history by the integration — it queries the HA recorder for the 6-hour historical values automatically. You no longer need any SQL, statistics, or template helpers.

### Recommended sensors (significantly improve accuracy)

| Field | Description | Unit |
|-------|-------------|------|
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
6. At night / twilight (elevation ≤ 5°), falls back to external weather entity cloud cover or 50 %

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

Even after turbidity correction, site-specific factors (aerosol type, dust, altitude, sensor cosine response) introduce a residual offset. When the external weather entity reports ≤ 5 % cloud cover and sun elevation ≥ 15°, the integration updates a site calibration factor via exponential moving average (α = 0.15). This factor is persisted to HA storage and survives restarts, converging after a handful of clear-sky readings.

### Sensor reliability and weights

The **Forecast reliability** sensor (0–100 %) reflects how completely the integration is fed:

| Input | Weight | Source |
|-------|--------|--------|
| Atmospheric pressure | 20 % | Configured sensor |
| Wind trend (6 h history) | 20 % | HA recorder (automatic after 6 h) |
| Pressure trend (6 h history) | 20 % | HA recorder (automatic after 6 h) |
| Wind direction | 15 % | Configured sensor |
| Cloud cover | 15 % | Configured sensor |
| Wind speed | 10 % | Configured sensor |

---

## Sensor setup: Ecowitt PWS example

This section shows exactly which entities to configure for each field, using an **Ecowitt local PWS** (via the [Ecowitt](https://www.home-assistant.io/integrations/ecowitt/) integration) as the reference hardware. The same principles apply to any PWS — adapt entity IDs accordingly.

### No helper entities required

The integration reads 6-hour historical values and computes vector-averaged wind directly from the HA recorder. You can point the wind direction field straight at your raw PWS sensor:

| What the integration computes automatically | How |
|---------------------------------------------|-----|
| **Wind trend** (Veering / Backing / Steady) | Queries the recorder for the wind direction state from 6 hours ago |
| **Pressure trend** (Rising Rapidly → …) | Queries the recorder for the pressure state from 6 hours ago |
| **Vector-averaged wind direction** | Circular mean of readings from the last 10 minutes via the recorder |
| **Vector-averaged wind speed** | Scalar mean of readings from the last 10 minutes via the recorder |

> **Prerequisite**: the HA `recorder` component must be running (it is on by default). The integration needs at least 6 hours of recorded history before wind trend and pressure trend become active; until then, they default to Steady / no change and the reliability score reflects the gap.

### Integration configuration — field mapping

| Integration field | Ecowitt entity to use | Notes |
|-------------------|-----------------------|-------|
| **Atmospheric pressure** | `sensor.pws_relative_pressure` | Use **relative** (sea-level) pressure, not `pws_absolute_pressure` (station altitude would skew pressure-level classification) |
| **Wind direction** | `sensor.pws_wind_direction` | Raw instantaneous sensor — the integration computes the vector average internally |
| **Cloud cover** | `sensor.pws_solar_radiation` (W/m²) **or** `sensor.pws_solar_lux` (lx) | Prefer the irradiance sensor when available — unit is auto-detected; at night / elevation ≤ 5° falls back to external weather entity cloud cover |
| **Wind speed** | `sensor.pws_wind_speed` | Raw instantaneous sensor — the integration computes the rolling mean internally |
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
- **Daily forecast** (7 days when an external weather entity is configured and available, 3 days local-only)
- **Hourly forecast** (up to 7 days when external weather is available, 48 h synthetic local-only)

The attribution shown on the weather card reflects the active data sources:
- External weather entity live: *"Sager Weathercaster forecast, enhanced by \<source attribution\>"*
- No external entity or data unavailable: *"Weather forecast from Sager Weathercaster Algorithm, based on local sensor data."*

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
| `external_weather_available` | Whether external weather entity data is current |
| `external_weather_day1_agreement` | agree / differ — Sager vs. external weather day-1 condition |
| `external_weather_day1_condition` | External weather entity's day-1 condition for comparison |
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

Extra attributes show per-sensor status (`ok` / `unavailable` / `not configured`) for each of the six weighted inputs, plus external weather status and `external_weather_last_updated` timestamp.

| `external_weather` attribute value | Meaning |
|------------------------------------|---------|
| `available` | Last fetch succeeded and data is current |
| `stale` | Last fetch succeeded but the data is older than 30 min |
| `not_fetched` | Configured but no successful fetch yet (e.g., just started) |
| `not_configured` | No weather entity has been selected in options |

---

## Update intervals

| Source | Interval |
|--------|----------|
| Sager + Zambretti algorithm | Every 10 minutes |
| External weather entity | Every 30 minutes (when configured) |

External weather data is cached between 30-minute fetches. On fetch failure, the last successful response is retained until a new fetch succeeds (stale data mode). If no external entity has ever been fetched, or if none is configured, the integration runs in local-only mode.

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
                      async_step_init()         external weather entity selector
coordinator.py      DataUpdateCoordinator (10 min):
                      _get_sensor_data()        reads all entities, sky→cloud conversion,
                                                binary + numeric rain detection
                      _async_query_history()    low-level recorder helper; runs
                                                state_changes_during_period in executor
                      _async_compute_pressure_change()  6 h pressure delta from recorder
                      _async_compute_wind_historic()    wind direction 6 h ago from recorder
                      _async_compute_vector_wind_avg()  circular mean of last 10 min of
                                                wind direction + speed from recorder
                      _sky_to_cloud_cover()     Kasten & Czeplak model for lx and W/m²
                                                inputs; applies turbidity + calibration
                      _local_turbidity_factor() Hänel aerosol model: dewpoint > T+RH >
                                                RH-only priority chain
                      _sager_algorithm()        ~4991-entry OpenHAB table lookup →
                                                forecast_code, wind_code
                      _zambretti_forecast()     independent barometric forecast
                      _cross_validate()         adjusts confidence based on Sager/Zambretti
                      _calculate_reliability()  0–100 % score from configured sensors
                      _async_fetch_external_weather()   30-min interval; reads any configured
                                                HA weather entity; stale fallback on failure
ha_weather.py       HAWeatherClient — reads weather.get_forecasts from a HA weather entity;
                    returns ExternalWeatherData (ExternalWeatherHourlyEntry,
                    ExternalWeatherDailyEntry dataclasses)
const.py            All constants: forecast tables, translation keys, WMO mapping,
                    sky-irradiance conversion coefficients (lux + W/m²)
sager_table.py      Sager Weathercaster full forecast lookup table
sensor.py           SagerSensor (enum, forecast code), SagerReliabilitySensor (% score)
weather.py          SagerWeatherEntity (SingleCoordinatorWeatherEntity):
                      attribution           dynamic — credits external weather entity when live
                      condition             from rain sensor → cloud cover → external fallback
                      _async_forecast_daily()
                        _generate_daily_forecast()   days 1–2 Sager+ext temp, day 3 blend,
                                                     days 4–7 external weather
                      _async_forecast_hourly()
                        _generate_sager_hourly_forecast()   always available, 48 slots
                        _enrich_hourly_with_ext_weather()   overlay ext data, extend beyond 48 h
translations/       en.json, it.json — all forecast codes, Zambretti keys, attribute names,
                    options flow strings
```

### Key design decisions

1. **Sager is always primary** — condition for days 1–2 and hours 0–48 h comes from Sager, never replaced by external weather data
2. **External weather enriches numerical fields** — temperature, wind, cloud, humidity, UV, dew point on the Sager slots; all these are more accurate from a numerical weather model than sensor extrapolation
3. **Hourly never spins** — `_generate_sager_hourly_forecast` always produces 48 slots from current sensor data, even with no internet or external entity
4. **Smooth transitions** — cloud cover and humidity transition from current sensor → Sager target over 12 h, then to day-2 target at h 24; prevents sudden jumps
5. **Wind extrapolation** — Beaufort-level keys (`moderate_to_fresh`, `gale`, …) lerp toward their speed midpoint (≤ 70 % of the way in 24 h); relative keys apply a ±50 % change
6. **No user-configurable polling intervals** — both intervals are integration-determined constants
7. **Sky-sensor auto-detection** — `unit_of_measurement` selects the conversion path: `lx` uses the luminance coefficient (172 278 lx), `W/m²` uses the solar constant (1361 W/m²); `%` is passed through unchanged; no separate config field needed
8. **Three-layer cloud-cover accuracy** — (1) physics-based turbidity factor from dewpoint / T+RH / RH; (2) external weather EMA site-calibration on confirmed clear-sky readings; (3) Kasten & Czeplak baseline with input-appropriate coefficient
9. **Hemisphere awareness** — backing/veering are reversed in the Southern Hemisphere
10. **External weather is optional** — selected via options flow (entity selector, `domain="weather"`); leaving it blank disables all external calls; `ext_weather_result["configured"]` propagates to sensor and weather entity; attribution reverts to local-only text
11. **Config flow separation** — sensor wiring goes in Reconfigure (updates `entry.data`); behavioral options go in Options flow (updates `entry.options`)
12. **Source-agnostic external data** — `HAWeatherClient` reads `weather.get_forecasts` from any HA weather entity (Met.no, OWM, AccuWeather, …); field names in `ExternalWeatherHourlyEntry` / `ExternalWeatherDailyEntry` use short unit-neutral names since the `native_` prefix is an HA entity concern, not a DTO concern
13. **Recorder-internalized time series** — wind trend and pressure trend are computed from raw sensor history via the HA recorder (`state_changes_during_period`); no SQL helpers, statistics helpers, or template helpers are required from the user; vector wind averaging over the last 10 minutes is also computed internally

---

## Limitations

- Sager is a 19th-century empirical algorithm optimized for the **Northern Temperate** zone (roughly Europe and North America). Accuracy degrades at polar and tropical latitudes.
- The algorithm does not model fog, haze, thunderstorms, or local topographic effects.
- Forecast accuracy depends heavily on sensor quality, particularly pressure and its 6 h change.
- The Sager table covers ~4 991 combinations; uncommon inputs fall back to a default "Unstable" forecast with 60 % confidence.
- Hourly data beyond 48 h (external weather extension) is only as accurate as the underlying numerical weather model of the selected entity.

---

## Contributing

Pull requests and issues are welcome at [github.com/coserotondo/sager_weathercaster](https://github.com/coserotondo/sager_weathercaster).

---

## License

This project is licensed under the MIT License.

The Sager Weathercaster algorithm is in the public domain (originally published 1869).
