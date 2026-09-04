# BenQ MoonHalo Bridge

## What this is

The Bridge is a small Python HTTP service that runs on the Windows PC the BenQ RD280UG monitor
is plugged into. It is the only piece of this project that speaks DDC/CI: it owns the VCP
register numbers, the way brightness and colour temperature are packed into one register, the
monitor's real ranges, and the rule that the MoonHalo always runs in 360 degree mode. The Hub
never talks to the monitor directly; it sends short HTTP requests to the Bridge, and the Bridge
turns each one into a Windows Monitor Configuration API call.

The Bridge has two faces: an HTTP API for the Hub (see below) and a command-line mode for
hands-on testing without the Hub. It keeps a small amount of state on disk (the last brightness
and colour steps, and the last on level) so that a change to one half of the shared register
never resets the other half, and so it can answer `/moonhalo/status` without touching the
monitor. It only answers callers in its allowlist, checked by IP and by MAC address resolved
through the PC's own ARP table.

## Prerequisites

- Windows, with the monitor connected over a cable that carries DDC/CI (most DisplayPort and
  HDMI cables do).
- Python 3.12 or later, installed so the `py` launcher works.
- The Bridge's Python dependencies, installed once per checkout.

```
py -m pip install -r requirements.txt
```

Run this from the `Bridges/BenQ_MoonHalo` folder.

## Configuration

Copy the example config and edit it for your network:

```
copy config.example.json config.json
```

`config.json` is read from next to this README by default; it is listed in `.gitignore` because
it carries your Hub's IP and MAC address. Every key below has a documented default, so a key
left out of `config.json` simply uses it.

| Key | Default | Meaning |
|---|---|---|
| `host` | `"0.0.0.0"` | Address the Bridge listens on. `0.0.0.0` means every interface. |
| `port` | `5000` | TCP port the Bridge listens on. |
| `default_on_level` | `50` | Level (1-100) used by `/moonhalo/on` when no level is given and none is remembered. |
| `monitor_selector` | `null` | Case-insensitive substring to match a monitor's device name or description, for a PC with more than one monitor. `null` selects the primary monitor. |
| `state_file` | `"state.json"` | Where remembered state is persisted. Relative paths resolve against the config file's own folder. |
| `log_file` | `null` | Where request log lines are written. `null` logs to stderr. |
| `default_brightness_step` | `5` | Brightness step (1-10) used the first time a colour-only write needs the "other half" of the register and no state can be read from the monitor. |
| `default_colortemp_step` | `4` | Colour step (1-7) used the first time a brightness-only write needs the "other half" and no state can be read. |
| `kelvin_min` | `2700` | Kelvin value for colour step 1 (warmest). |
| `kelvin_max` | `6500` | Kelvin value for colour step 7 (coolest). |
| `invert_colortemp` | `false` | Set `true` to flip the step-to-Kelvin direction if a firmware difference has warm and cool reversed. |
| `allowed_macs` | `[]` | MAC addresses allowed to call the Bridge (any format: colons, dashes, or dot groups). |
| `allowed_ips` | `[]` | IP addresses allowed to call the Bridge, checked before the MAC lookup. |
| `allow_loopback` | `true` | Allow `127.0.0.1` / `::1` regardless of the lists above, for local testing with `curl`. |

**Allowlist rules.** A caller is allowed if any of these hold, checked in order: it is loopback
and `allow_loopback` is true; both `allowed_macs` and `allowed_ips` are empty (see the warning
below); its IP is in `allowed_ips`; or its IP resolves, via the PC's ARP table, to a MAC in
`allowed_macs`. Anything else gets a 403. `/health` skips this check entirely so it is always
answerable for a local liveness check.

**Warning: `allowed_macs` and `allowed_ips` both empty means the Bridge is open to any caller on
the network that can reach its port.** The Bridge logs a startup warning when this is the case.
The example config carries the Hub's own MAC (`34:e1:d1:80:9c:62`) and IP (`192.168.86.73`) so a
copy made from it is restricted from the start; do not deploy with both lists empty.

## Running by hand

Start the Bridge in the foreground from the `Bridges/BenQ_MoonHalo` folder:

```
py -m moonhalo_bridge serve
```

This prints a line such as `MoonHalo Bridge serving on 0.0.0.0:5000 (dry_run=False)` and then
runs Flask's built-in development server in the foreground until you stop it (Ctrl+C). That
server is adequate for a single Hub talking to the Bridge over a home LAN; it is not meant to be
exposed beyond the LAN or to serve many concurrent clients.

Add `--dry-run` to exercise the Bridge without a real monitor: it installs an in-memory fake
port pre-loaded with the RD280UG's verified register values, so `serve`, `monitors`, `read`, and
`write` all work with no Windows API calls and no hardware attached.

```
py -m moonhalo_bridge --dry-run serve
```

Use `--config` to point at a config file anywhere else:

```
py -m moonhalo_bridge serve --config C:\path\to\config.json
```

Each request produces one log line, either on stderr or in `log_file`, naming the endpoint, the
VCP writes it produced, and the outcome, for example:

```
2026-09-04 00:00:00,000 endpoint=/moonhalo/on writes=[(215, 544), (217, 1029)] outcome=ok
```

(215 is decimal for VCP 0xD7, 217 for 0xD9; the values are the full 16-bit register writes.)

## HTTP API

Every endpoint is a GET request and returns JSON. A successful call returns
`{"ok": true, "state": {...}}`; a failed one returns `{"ok": false, "error": "..."}` with an
HTTP status of 400 (bad input), 403 (caller not in the allowlist), or 500 (DDC/CI failure).
`state` always has the same shape:

| Field | Meaning |
|---|---|
| `power` | `"on"`, `"off"`, `"auto"`, or `"unknown"`. |
| `level` | Brightness 0-100 (0 when off). |
| `brightnessStep` | Hardware brightness step, 1-10. |
| `colorTempStep` | Hardware colour step, 1-7 (1 warm). |
| `colorTemperature` | Colour temperature in Kelvin. |
| `monitor` | The selected monitor's description string. |

| Endpoint | Parameters | Notes |
|---|---|---|
| `GET /moonhalo/on` | `level` (query, optional, 1-100) | Turns the halo on at `level`, or the remembered last level, or `default_on_level`. |
| `GET /moonhalo/off` | none | Turns the halo off. Leaves the remembered level and colour step untouched. |
| `GET /moonhalo/brightness/<value>` | `<value>` 0-100 in the path | `0` is equivalent to `/moonhalo/off`. Otherwise turns the halo on first if it was off. |
| `GET /moonhalo/colortemp/<value>` | `<value>` in the path (1-7 hardware step, or >= 1000 Kelvin); `stage` (query, optional, `1` to pre-stage) | Turns the halo on first unless `stage=1`, in which case only the remembered colour step changes and no DDC write happens. |
| `GET /moonhalo/status` | none | Returns the remembered state; performs no DDC/CI call. |
| `GET /health` | none | `{"ok": true}`, no allowlist check, for a local liveness probe. |

Example: `GET /moonhalo/brightness/50` with the default colour step (4) replies

```json
{
  "ok": true,
  "state": {
    "power": "on",
    "level": 50,
    "brightnessStep": 5,
    "colorTempStep": 4,
    "colorTemperature": 4600,
    "monitor": "Generic PnP Monitor"
  }
}
```

## Command-line mode

Run these from the `Bridges/BenQ_MoonHalo` folder, with or without `--dry-run`:

```
py -m moonhalo_bridge monitors
py -m moonhalo_bridge read D9
py -m moonhalo_bridge write D7 544
```

`monitors` lists every attached physical monitor. `read <code>` reads a VCP register given as
hex (`D9` or `0xD9`) and prints its current and maximum value. `write <code> <value>` writes a
value (decimal or `0x`-hex) to a VCP register and reads it back to confirm.

**Caution: `write` changes the monitor immediately, with no confirmation prompt.** Only the
values verified on the RD280UG on 2026-09-03 are known-good: `write D7 544` (0x0220, on at 360
degrees), `write D7 528` (0x0210, off), and `write D9 <value>` with `<value>` packed as
`(colour_step << 8) | brightness_step` for colour step 1-7 and brightness step 1-10 (for
example `write D9 1029` for colour step 4, brightness step 5). Do not write other VCP codes or
other D7/D9 values without first confirming them by hand.

## Running as a Windows service (NSSM)

**Recommended launch method: to be confirmed by the service verification; see the Hub setup
below.** _[Maintainer: fill in "service" or "logon scheduled task" here once the verification
in the map task has run, and note the reason if the service could not reach the display.]_

[NSSM](https://nssm.cc/download) manages the Bridge as a proper Windows service (automatic
start, restart on failure, stdout/stderr captured to files) without writing a service wrapper
by hand. It is not installed by default: download it from https://nssm.cc/download, then place
`nssm.exe` on your `PATH` or in `C:\Tools\nssm\`.

Find your Python executable once:

```
py -c "import sys; print(sys.executable)"
```

This prints a path such as `C:\Users\<you>\AppData\Local\Programs\Python\Python314\python.exe`.
Use that path (or `py.exe` if it is on `PATH`) as the service's Application below.

Install the service (adjust the Python path and the Bridge folder to match your machine):

```
nssm install MoonHaloBridge "C:\Users\<you>\AppData\Local\Programs\Python\Python314\python.exe" -m moonhalo_bridge serve
nssm set MoonHaloBridge AppDirectory "C:\Users\RBILLC\source\repos\Hubitat\Bridges\BenQ_MoonHalo"
nssm set MoonHaloBridge AppStdout "C:\Users\RBILLC\source\repos\Hubitat\Bridges\BenQ_MoonHalo\bridge-stdout.log"
nssm set MoonHaloBridge AppStderr "C:\Users\RBILLC\source\repos\Hubitat\Bridges\BenQ_MoonHalo\bridge-stderr.log"
nssm set MoonHaloBridge Start SERVICE_AUTO_START
```

Start it, check it, and stop or remove it later:

```
nssm start MoonHaloBridge
nssm status MoonHaloBridge
nssm stop MoonHaloBridge
nssm remove MoonHaloBridge confirm
```

**Session 0 caveat.** Windows services run in session 0, on a non-interactive window station.
Whether a service in session 0 can successfully call the Windows Monitor Configuration API used
here (`EnumDisplayMonitors`, `SetVCPFeature`, and related functions) is undocumented — Microsoft
Learn states the general session-0 restriction for services that show a user interface, but none
of the monitor-configuration API pages say whether session 0 can reach an attached display at
all. This is unresolved in this repository's research and must be confirmed by hand (see
`docs/research/ddcci-windows-api.md`, section 8). If the service cannot reach the monitor, use
the logon scheduled task fallback below instead.

**Verification steps (run these with the service installed and started):**

1. `nssm start MoonHaloBridge`, then `nssm status MoonHaloBridge` — confirm it reports running.
2. From the PC (or any machine on the LAN once the firewall rule below is in place), call:
   ```
   curl http://localhost:5000/moonhalo/brightness/100
   curl http://localhost:5000/moonhalo/brightness/10
   ```
3. Watch the MoonHalo: it should jump to full brightness on the first call and dim on the
   second.
4. Read the log file named in `AppStdout`/`AppStderr` (or `log_file` in `config.json`) and
   confirm a line for each request with `outcome=ok` and the expected VCP writes.
5. If the halo does not change but the log shows `ok` with the expected writes reaching a real
   `WindowsDdcPort` (not `dry_run=True`), the service likely cannot reach the display from
   session 0; stop and remove the service and use the logon scheduled task below instead.

## Logon scheduled task (fallback)

If the service cannot reach the display, run the Bridge from a scheduled task that starts in
your own logged-in session instead. This repository includes a launcher, `run_bridge.cmd`, next
to this README, which changes to its own folder before starting the Bridge so the task's own
working directory does not matter.

`schtasks /create` has no flag of its own for a task's working directory, which is why the
committed `run_bridge.cmd` launcher exists: it `cd`s to its own folder before starting the
Bridge, so `-m moonhalo_bridge` finds the package regardless of what directory the task starts
in. Point the task at the launcher:

```
schtasks /create /tn "MoonHaloBridge" /tr "\"C:\Users\RBILLC\source\repos\Hubitat\Bridges\BenQ_MoonHalo\run_bridge.cmd\"" /sc onlogon /ru "%USERNAME%" /rl LIMITED
```

`run_bridge.cmd` calls `py -m moonhalo_bridge serve %*`, which briefly shows a console window at
logon. For a windowless run, edit the launcher to call `pythonw` (the windowless interpreter
that sits next to `python.exe`) instead of `py`. Run the task once by hand to test, check its
status, and delete it if you switch back to the service:

```
schtasks /run /tn "MoonHaloBridge"
schtasks /query /tn "MoonHaloBridge"
schtasks /delete /tn "MoonHaloBridge" /f
```

The task only runs once you are logged into that session, so it will not start the Bridge
before you sign in, and it stops when you sign out — a trade-off against a service, which can
run without any interactive session.

## Windows Firewall rule

Open the Bridge's port only to your local subnet, not to the whole internet or every profile:

```
netsh advfirewall firewall add rule name="MoonHalo Bridge" dir=in action=allow protocol=TCP localport=5000 remoteip=192.168.86.0/24 profile=private
```

Remove it with:

```
netsh advfirewall firewall delete rule name="MoonHalo Bridge"
```

Adjust `localport` and `remoteip` if your Bridge port or subnet differ from the defaults.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `monitors` prints "No monitors found." or `write`/`read` fails with "No display monitors found" | The monitor is not attached, is asleep, or its cable does not carry DDC/CI. Check the cable and that the monitor is not in a low-power state. |
| A DDC/CI call fails with a large error code (formatted as a decimal, but corresponding to a hex value in the `0xC026xxxx` range) | This is a Windows Graphics Kernel DDC/CI channel error, often transient on this monitor. Reads already retry three times; a `write` is not retried, so simply try the command again. Persistent errors suggest a cable or connection problem rather than the Bridge. |
| `GET` requests get `{"ok": false, "error": "forbidden"}` with a 403 | The caller's IP is not in `allowed_ips`, and its MAC (resolved through the PC's ARP table with `arp -a <ip>`) is not in `allowed_macs`. Confirm the Hub's IP and MAC in `config.json`, and that the PC has recently exchanged traffic with the Hub so the OS ARP cache has an entry for it — a stale or absent entry resolves to no MAC and is denied. `/health` is exempt from this check and always answers. |
| `serve` fails to start, e.g. "port in use" / `OSError: [WinError 10048]` | Another process (perhaps a previous `serve` still running, or the NSSM service) is already bound to `config.json`'s `port`. Stop it first (`nssm stop MoonHaloBridge`, or find and end the other `python.exe`/`pythonw.exe` process), or change `port` in `config.json`. |
| The service (or task) starts and requests return `ok` with the expected writes, but the halo does not visibly change | Most likely the session-0 caveat above: the process cannot actually reach the display even though the Windows API calls report success. Switch to the logon scheduled task. If that also does not change the halo, verify the same write works from an interactive `py -m moonhalo_bridge write D7 544` first. |

## Tests

Run the full suite from the `Bridges/BenQ_MoonHalo` folder:

```
py -m unittest
```

The tests need no monitor: they drive the Flask app over HTTP with a fake DDC port that records
every write, the same way the spec's testing decisions describe.
