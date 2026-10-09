# Release checklist: BenQ MoonHalo Bridge

The verification run before a release is tagged. Run it top to bottom on the real Hub, PC and
monitor, with the Driver and Bridge versions that are about to ship. Every line names what to do,
where to look and what passing looks like. A failing line is a bug ticket: fix it, re-run the
line, then carry on. Record the run in the sign-off block at the end.

Agreed with the user on 2026-10-09 (issue #50). Three points are still open and are decided when
the first run is signed off; they are listed before the sign-off block.

## Before you start

- The halo has seven color steps, and `colorTemperature` shows the step it landed on, not the
  number you typed: 2971, 3514, 4057, 4600, 5143, 5686 or 6229 with the default 2700 to 6500
  range. `level` shows the Level as commanded, and reads 0 while the halo is off.
- `monitorLink` reads `unknown` from a Bridge start until the first command that writes to the
  monitor. A Refresh does not write, so it cannot turn `unknown` into `ok`.
- **Current States** on the device page updates live. **State Variables** is a snapshot from
  when the page loaded, so reload the page before reading it.
- `bridge.log` is in `Bridges\BenQ_MoonHalo`. Each command is one `endpoint=...` line with
  `transition=<seconds>s steps=<writes>`, followed by a `ramp complete ... elapsed=` line.
- Restart the Bridge task with `schtasks /end /tn MoonHaloBridge`, then
  `schtasks /run /tn MoonHaloBridge`.
- Note the time you start. Line 22 reads both logs from that time on.

## A. PC (Bridge)

| # | Do | Where to look | Passing |
|---|---|---|---|
| 1 | Run `py -m unittest` from `Bridges\BenQ_MoonHalo`. | The last lines on the console. | `Ran <n> tests` and `OK`, with no `skipped` and no `FAILED`. |
| 2 | Run `py -m moonhalo_bridge monitors` from the same folder. | The last line on the console. | `selected: BenQ RD280UG on \\.\DISPLAYn (by edid)`. |
| 3 | Open `http://localhost:5000/health` in a browser on the PC. | The page. | `"ok": true` and `"version"` equal to the Bridge version being released. |
| 4 | Restart the Bridge task. | The new lines at the end of `bridge.log`. | A `monitor BenQ RD280UG on \\.\DISPLAYn by edid; candidates: ...` line, then an `announced Bridge address <PC ip>:5000 to hub <hub ip>` line, in that order. No traceback. |

## B. Hub device page, one command at a time

| # | Do | Where to look | Passing |
|---|---|---|---|
| 5 | Click **Refresh**, then reload the page. | Current States and State Variables. | `bridgeLink` `online`, `bridgeAddress` the PC's `ip:5000`, `monitorLink` `ok` (or `unknown` when no command has run since the restart in line 4; it must read `ok` after line 6), `bridgeVersion` the Bridge version being released with no "Driver needs" text. |
| 6 | Click **On**. | The halo and Current States. | The halo lights and rises to the level it had before it was last turned off. `switch` `on`. |
| 7 | **Set Level** 20, then 100, with no duration. | The halo, Current States and `bridge.log`. | Each move sweeps through the steps at the Default transition pace, with no jump and no flash. `level` reads 20, then 100. |
| 8 | **Set Level** 50 with duration 5. | The halo, a clock and `bridge.log`. | The move takes about five seconds. `level` reads 50. The log line shows `transition=5.0s`. |
| 9 | **Set Color Temperature** 2700, then 6500. | The halo and Current States. | The halo turns warm, then cool. `colorTemperature` reads 2971, then 6229, and `colorName` changes with it. |
| 10 | With **Enable color pre-staging** off: **Off**, then **Set Color Temperature** 4000. Then turn pre-staging on and save, click **Off**, then **Set Color Temperature** 6500. Set the preference back afterward. | The halo and Current States. | Pre-staging off: the halo turns on and `colorTemperature` reads 4057. Pre-staging on: the halo stays dark, `switch` stays `off`, and `colorTemperature` reads 6229. |
| 11 | Click **On**, set a level, then click **Off**. Click **On** again. | The halo and Current States. | Off dims the halo out through its steps, then it goes dark and `switch` reads `off`. The second On returns to the level you set. |

## C. Automation

| # | Do | Where to look | Passing |
|---|---|---|---|
| 12 | Run a Rule Machine rule that dims the device over time, for example to 20 over 5 seconds. | The halo, a clock and `bridge.log`. | The move takes the rule's time. The log line shows that time as `transition=`. |
| 13 | Put the device on a dashboard as a bulb tile and use on, off, the level slider and the color temperature slider. | The halo and the tile. | All four act on the halo and the tile shows the result. |

## D. Google Home, through the Google Home Community app

| # | Do | Where to look | Passing |
|---|---|---|---|
| 14 | Open the device card in the Google Home app and move the white-temperature slider. | The card and the halo. | The card has the slider. The halo changes color, and the slider settles on the nearest of the seven steps. |
| 15 | Say "set <device> to 40 percent", then "make <device> warmer". | The halo. | Both commands act on the halo. |

## E. Resilience

| # | Do | Where to look | Passing |
|---|---|---|---|
| 16 | With the halo on, stop the Bridge task (`schtasks /end /tn MoonHaloBridge`) and wait for the announce timeout, 200 seconds by default. | Current States and the hub log. | `bridgeLink` `offline`, `monitorLink` `unreachable`, one warning in the hub log, and `switch` and `level` unchanged. |
| 17 | Start the task (`schtasks /run /tn MoonHaloBridge`). Touch nothing on the Hub. | Current States. | Within a minute `bridgeLink` `online`. `monitorLink` leaves `unreachable` at the next status poll (the Poll interval, 5 minutes by default, or a Refresh) and reads `unknown` until the next command, then `ok`. See the open points. |
| 18 | Put the monitor in standby (`DisplaySwitch.exe /internal` when a second display is attached; otherwise however the PC puts it to sleep), then click **On**. Wake it (`DisplaySwitch.exe /extend` and the monitor's button), then click **On**. | Current States, State Variables and the hub log. | Asleep: the command is refused with `Bridge rejected on` in the hub log, `monitorLink` `failed`, `lastMonitorError` says `is not attached: asleep, off or unplugged`, and `switch` is unchanged. Awake: On works and `monitorLink` returns to `ok` with no task restart. |

## F. Fresh install

| # | Do | Where to look | Passing |
|---|---|---|---|
| 19 | Add a new virtual device of type BenQ MoonHalo Bridge. Type the PC's IP and port, save, and click **Refresh**. Do not add it to the Maker API. Delete the device afterward. | The new device's Current States. | `bridgeLink` goes `online` and `monitorLink` `ok` with no announcement received. |

## G. Public links

| # | Do | Where to look | Passing |
|---|---|---|---|
| 20 | Open the raw import URL and the repository URL in a private browser window. | The two pages. | Both load without a login. The raw file's Version line is the Driver version being released. |
| 21 | On the Hub, open the Driver in **Drivers Code**, click **Import**, paste the raw URL, import and **Save**. | The editor. | The import succeeds and the save shows no error. The raw URL can lag a push by a few minutes. |

- Raw import URL: `https://raw.githubusercontent.com/RBILLC/Hubitat/main/Drivers/BenQ_MoonHalo_Bridge_Driver.groovy`
- Repository: `https://github.com/RBILLC/Hubitat`

## H. Logs

| # | Do | Where to look | Passing |
|---|---|---|---|
| 22 | Read the hub log for the device and `bridge.log` from the time the run started. Leave debug logging on from a save and look again 30 minutes later. | Hub **Logs** filtered to the device, `bridge.log`, and the **Enable debug logging** preference. | No errors in either log apart from the ones lines 16 and 18 cause on purpose. After 30 minutes the hub log shows `debug logging disabled...` and the preference is off. |

## Open points

Decide these when ticking, and record the decision in the sign-off block.

- Whether the user's own app, driving the device through the Maker API, is a line of this checklist.
- Whether line 18 also covers the monitor switched off at its button.
- Line 17 was agreed as "within a minute online and ok with no action on the hub". The code gives
  `bridgeLink` `online` within a minute, but `monitorLink` waits for the next poll and then reads
  `unknown` until a command writes to the monitor. Decide whether that is accepted as written
  above, or a ticket.

## Sign-off

Copy this block for each run, newest first.

```
Date:
Run by:
Driver version:
Bridge version:
Hub model and platform version:
Lines passed:            of 22
Failed lines and their tickets:
Open point, Maker API app as a line:
Open point, line 18 with the monitor off at its button:
Open point, line 17 monitorLink after a Bridge start:
Result:
```
