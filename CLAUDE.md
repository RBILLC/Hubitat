# Hubitat

Custom Hubitat Elevation drivers and their companion PC-side bridges.

- `Drivers/` — Groovy device drivers. One file per driver, `<Vendor>_<Device>_Driver.groovy`. Pasted into the Hubitat web console (Drivers Code) or imported via the raw GitHub URL in each driver's `importUrl`.
- `Bridges/<Name>/` — helper services that run on another machine when the hub cannot talk to a device directly (for example a Python HTTP bridge on a Windows PC).

## Conventions

- Drivers follow the house style of `Drivers/Tuya_TS0601_Soil_Sensor_Driver.groovy`: header comment block, `logEnable`/`txtEnable` preferences with a 30-minute `logsOff`, and a health attribute with values `unknown`/`online`/`offline`.
- Hubitat has no local test harness; keep driver logic small and put anything testable in the bridge, which is tested with plain `unittest`.

## Working rules

- **Official documentation first.** Before proposing an experiment, a workaround, or a theory about why something fails, find and read the primary source: the vendor's documentation (Hubitat docs2, Google Home developer docs, Microsoft Learn, a project's own README or source). Quote it. If the answer is not already in `docs/research/`, run a research pass and save the findings there. Experiments come after the docs, to confirm what they say, never to explore in their place. Anything not backed by a document is labelled as inference.
- **The Hubitat community forum is a primary source for this repo.** Hubitat's docs leave much undocumented (the async response object, the Google Home capability mapping, how helpers are installed); the answers usually exist at https://community.hubitat.com, often from Hubitat staff or well-known driver authors. Search it in every research pass. Read a thread as JSON with `https://community.hubitat.com/t/<topic-id>.json` when the HTML is heavy. Weight staff posts and posts that report a confirmed fix over speculation, and cite the thread URL.
- **Verify what agents report.** A subagent's summary can contradict the facts in its own findings file (one recommended UDP for a port the docs call TCP). Read the findings, not just the summary, before acting on them.

## Agent skills

### Issue tracker

Issues live in GitHub Issues for `RBILLC/Hubitat`, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default triage labels, unchanged (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
