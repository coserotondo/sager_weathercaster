# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development environment

This integration is developed inside the Home Assistant core dev-container. The component under active development lives at:

```
config/custom_components/sager_weathercaster/   ← live, loaded by HA
config/custom_components_repo/sager_weathercaster/   ← github repo root, needed structure for HACS, additional files like README.me, hacs.json, ... (automatically in sync: same filesystem on the host, different bind mount in the container)
config/custom_components_repo/sager_weathercaster/custom_components/sager_weathercaster/   ← same as config/custom_components/sager_weathercaster/
```

When editing, work in `config/custom_components/sager_weathercaster/` so Home Assistant picks up changes on restart; the repo copy is automatically in sync, no action needed.

### Linting and type checking

From the HA core root (`/workspaces/home-assistant-core`):

```bash
# Lint only this integration
pylint config/custom_components/sager_weathercaster

# Type-check only this integration
mypy config/custom_components/sager_weathercaster

# Run all linters on staged files
prek run

# Run all linters on all files
prek run --all-files
```

### Running tests

Tests live at `custom_components/sager_weathercaster/tests/`. To run them from the HA core root:

```bash
PYTHONPATH=/workspaces/home-assistant-core/config \
  python -m pytest tests/components/sager_weathercaster/ --timeout=10 -q
# or run a single test file
PYTHONPATH=/workspaces/home-assistant-core/config \
  python -m pytest tests/components/sager_weathercaster/test_config_flow.py --timeout=10
```

## Architecture

### Data flow

```
HA sensor entities
    └─► Coordinator._get_sensor_data()        reads + validates all configured entities
            └─► _get_cloud_cover()            unit-aware conversion: % | lx | W/m²
                    ├─► _local_turbidity_factor()   Hänel aerosol model (dewpoint > T+RH > RH)
                    └─► _sky_to_cloud_cover()        Kasten & Czeplak + EMA site-calibration
    └─► _sager_algorithm()                    5-variable → 4-char key → SAGER_TABLE lookup
    └─► _zambretti_forecast()                 independent barometric forecast
    └─► _cross_validate()                     adjusts Sager confidence by Zambretti agreement
    └─► _calculate_reliability()              0–100 % score from configured sensors
    └─► _async_fetch_external_weather() (30 min)  reads ext HA weather entity; calibrates clear-sky

Result dict consumed by:
    SagerSensor            state = forecast code (a–y + 1/2 suffix)
    SagerReliabilitySensor state = reliability %
    SagerWeatherEntity     daily (7-day) + hourly (48 h Sager + external weather extension)
```

### Key files

| File | Responsibility |
|------|---------------|
| `const.py` | All constants: Sager table keys, WMO→condition mapping, latitude zones, cloud-cover coefficients, forecast-code translation keys |
| `coordinator.py` | `DataUpdateCoordinator` — all algorithms live here: Sager, Zambretti, cross-validation, cloud-cover pipeline, turbidity correction, external weather calibration |
| `config_flow.py` | User + Reconfigure steps (sensor wiring); Options step (external weather entity selector). Unit validation for pressure and cloud cover happens here. |
| `sensor.py` | Two sensors: forecast code (enum device class) and reliability score (diagnostic) |
| `weather.py` | `SagerWeatherEntity` — daily and hourly forecast construction with Sager-primary, external-weather-numerical blend |
| `ha_weather.py` | `HAWeatherClient`: reads forecasts from an existing HA `weather.*` entity via `weather.get_forecasts`; returns `ExternalWeatherData` with typed `ExternalWeatherHourlyEntry` / `ExternalWeatherDailyEntry` dataclasses |
| `sager_table.py` | `SAGER_TABLE` dict: 4-char key → 3/4-char value encoding forecast + velocity + direction |
| `wind_names.py` | Regional named-wind database keyed by lat/lon bounding boxes; most-specific region wins |

### Sager algorithm (coordinator.py `_sager_algorithm`)

Five inputs are derived from sensors and encoded into a 4-character lookup key:

```
letter  = wind direction + wind trend  (A–Y, 25 zone-aware letters; Z = calm)
digit2  = pressure level 1–8          (from HPA_LEVELS constant)
digit3  = pressure trend 1–5          (Rising Rapidly → Decreasing Rapidly)
digit4  = cloud level 1–5             (Clear → Raining)
```

The table value is a 3–4-char string: `forecast_letter + velocity_letter + direction_digit(s)`. Temperature < 2 °C converts shower codes to flurry variants (suffix `"2"` instead of `"1"`).

### Cloud-cover conversion pipeline

`_get_cloud_cover()` routes by `unit_of_measurement`:
- `%` → direct passthrough
- `lx` → `_sky_to_cloud_cover(value, LUX_CLEAR_SKY_COEFFICIENT, "lux")`
- `W/m²` / `W/m2` → `_sky_to_cloud_cover(value, IRRADIANCE_CLEAR_SKY_COEFFICIENT, "W/m²")`

`_sky_to_cloud_cover` applies three layers in order:
1. `_local_turbidity_factor()` — Hänel hygroscopic aerosol correction (vapor-pressure S-curve, factor range 0.60–1.0); moisture priority: dewpoint → T+RH → RH-only
2. EMA site-calibration (`_sky_calibration_factor`) — updated when the external weather entity reports ≤ 5 % cloud and elevation ≥ 15°, α = 0.15, bounds 0.4–1.4
3. `ln(calibrated_clear_sky / measured) × 100` clamped to 0–100 %

Night/twilight fallback (elevation ≤ 5°): external weather entity `current_cloud_cover` or 50 %.

### Forecast hierarchy (weather entity)

- **Days 1–2:** Sager condition + external weather temperature
- **Day 3:** 40 % Sager / 60 % external weather condition blend
- **Days 4–7:** Pure external weather (falls back to Sager-only through day 3)
- **Hourly 0–48 h:** Sager condition (authoritative); external weather overlays temperature, wind, humidity, UV, dew point, precipitation
- **Hourly 48 h+:** Pure external weather extension

### Adding a new optional sensor

1. Add `CONF_<NAME>_ENTITY` constant in `const.py`
2. Add `vol.Optional(CONF_<NAME>_ENTITY)` selector in `config_flow.py → _build_sensor_schema()`
3. Read the entity state in `coordinator.py → _get_sensor_data()` (follow the existing pattern: check unavailable/unknown, range-validate, default to `None`)
4. Add `"<name>_entity"` label strings to both `translations/en.json` steps (`user` and `reconfigure`) — `data` and `data_description` blocks
5. Mirror in `translations/it.json`

### Hemisphere and latitude zone awareness

Wind trend (veering vs. backing) and the Sager wind-direction letter mapping are flipped in the Southern Hemisphere. Zone detection is automatic from `hass.config.latitude`. Constants `ZONE_DIRECTIONS_NT/NP/ST/SP` in `const.py` hold the per-zone wind-letter tables; `_get_zone_name()` and the `zone_directions` field on the coordinator drive the lookup.

## Translations

After editing any `strings.json` or translation file, regenerate from the HA core root:

```bash
python -m script.translations develop --all
```

Both `translations/en.json` and `translations/it.json` must be kept in sync for every new field.

## README.md

`README.md` is the user-facing documentation and should be kept in sync with code changes. Update it when:

- A new optional sensor is added (optional sensors table + cloud-cover section if relevant)
- The cloud-cover pipeline changes (the "Sky-sensor auto-detection" section)
- New coordinator methods are added or renamed (Architecture notes code block + key design decisions list)
- The Ecowitt PWS field mapping changes

Sections most likely to drift out of date:
- **Features** list (top of README)
- **Optional sensors** table
- **Cloud cover: sky-sensor auto-detection** (conversion pipeline, turbidity table, calibration explanation)
- **Integration configuration — field mapping** (Ecowitt example)
- **Architecture notes** (`coordinator.py` method list, `const.py` description, key design decisions)
