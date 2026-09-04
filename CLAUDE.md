# Hubitat

Custom Hubitat Elevation drivers and their companion PC-side bridges.

- `Drivers/` — Groovy device drivers. One file per driver, `<Vendor>_<Device>_Driver.groovy`. Pasted into the Hubitat web console (Drivers Code) or imported via the raw GitHub URL in each driver's `importUrl`.
- `Bridges/<Name>/` — helper services that run on another machine when the hub cannot talk to a device directly (for example a Python HTTP bridge on a Windows PC).

## Conventions

- Drivers follow the house style of `Drivers/Tuya_TS0601_Soil_Sensor_Driver.groovy`: header comment block, `logEnable`/`txtEnable` preferences with a 30-minute `logsOff`, and a health attribute with values `unknown`/`online`/`offline`.
- Hubitat has no local test harness; keep driver logic small and put anything testable in the bridge, which is tested with plain `unittest`.

## Agent skills

### Issue tracker

Issues live in GitHub Issues for `RBILLC/Hubitat`, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default triage labels, unchanged (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
