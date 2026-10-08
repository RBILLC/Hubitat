# Plan: MoonHalo 1.0.0 release

Ticket: [#38](https://github.com/RBILLC/Hubitat/issues/38). Written 2026-09-08 late evening so the next
session can pick this up without the conversation that produced it. Update it as steps close.

## Where things stand (2026-09-08, 23:30)

- The MoonHalo effort under map #1 is complete: specs #13 and #30 and tickets #31-#37 are closed, and
  `feature/benq-moonhalo` was merged to `main` as 6718af7. `main` is the branch to work on now.
- On the hub: Driver **0.0.11** (importUrl serves it from `main`), preference **Default transition (ms)**
  at its default 300. On the PC: Bridge **0.0.6** running from the `MoonHaloBridge` logon scheduled
  task with `config.json` `transition_seconds` 0.3; the Bridge announces 192.168.86.115:5000 to the hub
  at 192.168.86.73.
- The pace that looked best on the real halo, judged by the user: writes back-to-back at the monitor's
  ~60 ms bus pace with fewer steps for a shorter sweep. 0.3 s (six of the nine steps) read as smooth;
  spacing writes 80 ms apart read as stepping. This is why the default is 0.3 and why a Sweep time
  below 0.54 s drops steps rather than slowing (amendment 2 on #30).
- Glossary: `CONTEXT.md` (Transition, Ramp, Sweep time, Target state, Applied state). The Bridge's
  timing rules live in one place, `Pacing.schedule` in `moonhalo_bridge/model.py`.

## Step 1: morning hub test

What to exercise on the hub with Driver 0.0.11 at the 300 ms default, watching the halo:

- A short slider move (two or three steps): should finish in well under a quarter second.
- A full slider sweep and off/on from the device page: six writes, about 0.3 s each, no flash on relight.
- A Google Home voice command and slider (they send setLevel then on): one move, no stutter.
- A rule or Maker API call with a rate, for example `setLevel(20, 3)`: still takes 3 s (explicit rate
  is total time and wins over the preference).
- Change the preference (240 gives five writes, 120 gives three, 0 snaps) and confirm the next command
  changes pace with nothing touched on the PC.

How to read what happened: `Bridges/BenQ_MoonHalo/bridge.log` has one line per request with
`transition=<planned seconds>s steps=<writes>` and a `ramp complete ... elapsed=` line per Ramp.
`py tools/ramp_probe.py brightness` (from `Bridges/BenQ_MoonHalo`, Bridge idle) prints every write with
its timing against the real monitor.

Operating notes learned this session:

- Restart the Bridge after any Bridge code or config change:
  `Stop-ScheduledTask -TaskName MoonHaloBridge; Start-ScheduledTask -TaskName MoonHaloBridge`, then
  `curl http://localhost:5000/health` and check the version. `Invoke-RestMethod` against the Bridge
  hangs from PowerShell; use curl.
- Driving the Bridge from the PC with curl (`/moonhalo/brightness/100?sweep=0.3` and so on) is the
  quickest way to compare paces; loopback is allowed by the access policy.
- A Hubitat `decimal` preference with `range: "0..60"` would not accept values under 1.0 on the device
  page; that is why the preference is whole milliseconds on a `number` input (research note, section 11
  of `docs/research/hubitat-driver-facilities.md`).

## Step 1b: Bridge 0.0.8, pick the monitor by identity (#40, added 2026-09-16)

A second monitor (BenQ PD2700U) became Windows' primary display and the Bridge, selecting the
primary when `monitor_selector` is null, wrote the MoonHalo registers to it while every link read
healthy. Ticket [#40](https://github.com/RBILLC/Hubitat/issues/40) makes the Bridge detect the
RD280UG by the `model(...)` in its capabilities string, with a D9 probe as fallback and tie-breaker,
and report `failed` when it is absent. Done before Step 2, which touches the same README rows.

Status 2026-09-16 evening: Bridge 0.0.8 implemented on `main` (detection in `moonhalo_bridge/ddc.py`,
`monitor_model` config key, `state.monitor` now `RD280UG on \\.\DISPLAY1`, `py -m moonhalo_bridge
monitors` prints the selection, `--monitor` CLI selector, README "What the Bridge assumes"). The
live config's `monitor_selector` workaround was set back to `null` and the task restarted. PC check
passed the same evening (hub command moves the halo; cable unplugged gives `monitorLink failed`
naming the missing model, plugged back in recovers with no restart); the check found and fixed a
30 s miss cooldown (each miss cost a 2.8 s capabilities read and detection ran on every call, which
outlasted the Driver's request timeout). Shipped as 443c791, #40 closed. Step 1b done.
Related facts recorded in `docs/research/rd280ug-d6-power-mode.md`: the RD280UG's button standby is
invisible to DDC/CI (writes succeed, D6 reads 0x60 on and off), so no `standby` value is possible.

## Step 2: code clean-up before announcing

Two tickets, filed 2026-09-16, both ready-for-agent, one Driver version each so each ships and is
reviewed on its own: [#42](https://github.com/RBILLC/Hubitat/issues/42) first (Driver 0.0.13:
`monitorLink` gains a fourth value, `unreachable`, set when `bridgeLink` goes offline and restored by
the first Bridge reply; options set aside: `unknown`, keep the last word, a `monitorLinkAt` timestamp),
then [#41](https://github.com/RBILLC/Hubitat/issues/41) (Driver 0.0.15 since #43 took 0.0.14: the items below plus a Monitor
detection glossary entry for #40's rule names), blocked by #42 on GitHub. The 1.0.0 bump is a separate
step after the review pass.

Status 2026-09-16 night: #42 shipped as 4118c84 (Driver 0.0.13) and closed after the hub check passed
(task stopped: `bridgeLink offline` and `monitorLink unreachable` together; task started: restored on
the next poll). The check raised two points, decided the same evening:

- [#43](https://github.com/RBILLC/Hubitat/issues/43) (ready-for-agent, Driver 0.0.14 / Bridge 0.0.9):
  every Bridge reply carries `version` next to `monitor`, and the Driver keeps it as a `bridgeVersion`
  state variable, so the hub shows which Bridge it talks to once users manage both pieces. The Driver
  also carries the minimum Bridge version it needs (0.0.9) and shows a too-old or missing version in
  place (`0.0.8 (Driver needs 0.0.9 or later)`) with one warning; newer is never flagged, and the
  minimum moves only when the Driver reads something an older Bridge does not send. Options set aside:
  the Driver polling `/health`; checking against the latest release; an attribute (Google Home typing).
- The `monitorLinkError`/`monitorLinkErrorAt` state is history by design (kept across recovery) and
  stays; the names are the problem, so #41 renames them to `lastMonitorError`/`lastMonitorErrorAt`.

Status 2026-09-16 late night: #43 shipped as 9e9a518 (Bridge 0.0.9 / Driver 0.0.14) and closed after
the hub check passed (Driver 0.0.14 against Bridge 0.0.8 showed `unknown (Driver needs 0.0.9 or later)`
with one warning; the task restarted on 0.0.9 showed `0.0.9` with one info line within a poll; stop and
start of the task left it at `0.0.9`). During the check the RD280UG's DDC/CI link stuck after a cable
replug (every call on DISPLAY1 failed with 0xC0262582, the 09-14 error) and the Bridge reported it as
`unreadable` without trying the D9 probe; that gap and the evidence are
[#44](https://github.com/RBILLC/Hubitat/issues/44) (needs-triage), a Bridge-only change that does not
collide with #41. A research pass on monitor identity without DDC/CI (EDID via WMI or EnumDisplayDevices)
feeds #44 before it is grilled.

Order, decided by the user 2026-09-16 late night: #44 first (research, then grilling, then a ticket edit and
/implement), #41 last (Driver 0.0.15; the clean-up closes the code, so nothing lands after it), then the
1.0.0 bump.

Status 2026-10-08: nothing shipped since 09-16; Bridge 0.0.9 and Driver 0.0.14 have run three weeks with
the Monitor link ok. The user reports the halo is slow to answer the first command after the monitor is
turned on. `bridge.log` explains it: a monitor in standby drops out of the display enumeration, so every
wake re-runs detection, and the capabilities reads cost 5.15 s (RD280UG) and 2.91 s (PD2700U), 7.9 s in
all, past the Driver's 5 s request timeout (one 408 and a one-cycle `bridgeLink` offline per wake). The
research note shows the EDID identity is free from `EnumDisplayDevices`, so #44 is now the fix for both
the slowness and the stuck-link reporting; its scope is restated in a comment on the ticket. Next:
/grill-with-docs on #44, then /implement as Bridge 0.0.10, hub check; then #41; then 1.0.0.

Status 2026-10-08 evening: #44 grilled (`/grill-with-docs`) and edited into a ready-for-agent ticket, Bridge
0.0.10, Bridge-only. Decisions: identify by EDID identity read from the registry EDID cache located through
`EnumDisplayDevices` (option B; `QueryDisplayConfig` set aside because it has no serial); new config key
`monitor_product` (default `BNQ80BB`), `monitor_model` retired, the label is the EDID name (`BenQ RD280UG on
\\.\DISPLAY1`); no DDC/CI on the detection path (capabilities read, D9 probe and sanity check go; rules
`edid`, `selector`, `first-of-ambiguous`, `none`); no miss cooldown, misses logged once per reason, display-set
cache kept; error texts `identified by EDID; DDC/CI not answering: ...` (hex next to the decimal) and
`is not attached: asleep, off or unplugged; attached: ...`; `monitors` prints product, name and serial per
display; no Driver change. Glossary entries EDID identity, Attached, Monitor detection added to `CONTEXT.md`.
No public BenQ product-code cross-reference exists (BenQ never registered `BNQ` with UEFI); the monitor's own
EDID name is the cross-reference, which `monitors` prints. Several RD280UGs on one PC is
[#45](https://github.com/RBILLC/Hubitat/issues/45) (needs-triage, later). Next: /implement #44, restart the
task, hub check (first command after a wake inside the 5 s timeout); then #41; then 1.0.0.

Status 2026-10-08 night: #44 implemented as Bridge 0.0.10 on main (`/implement`, Bridge-only, Driver
untouched). New `moonhalo_bridge/edid.py` (EDID parser, tested against the RD280UG's and PD2700U's real
registry bytes), `ddc.py` detection rewritten around `EnumDisplayDevices` + the registry EDID cache
(rules `edid`, `selector`, `first-of-ambiguous`, `none`; no DDC/CI on the detection path; no miss cooldown;
misses logged once per reason; `DdcError` prints the hex next to the decimal; failures on the identified
monitor carry `identified by EDID; DDC/CI not answering:`), `monitor_product` replaces `monitor_model`,
README and `config.example.json` updated. 362 tests pass; `py -m moonhalo_bridge monitors` on this PC
answers in 88 ms with both displays' product, name and serial and `selected: BenQ RD280UG on \\.\DISPLAY1
(by edid)`. Left to the user: restart the MoonHaloBridge task, the two hub checks on #44 (first command
after a wake inside the 5 s timeout; standby reads not-attached and recovers with no restart), `/health`
0.0.10 on the device page; then close #44, then #41, then 1.0.0.

Status 2026-10-08 midday: #44 CLOSED after the hub check. Task restarted on 0.0.10 (`schtasks /end` then
`/run`; the hub logged `Bridge version 0.0.10` with no warning). Standby forced per monitor with
`DisplaySwitch.exe /internal` (the RD280UG leaves the desktop and sleeps) and `/extend` to bring it back;
a PowerShell display-off message is no use here, both monitors woke at once. While asleep: `monitorLink`
failed with the not-attached text, `state.monitor` unknown. On wake: detection `by edid` and the first
command 67 ms apart, the hub logged `Monitor link ok` with no 408 and no `bridgeLink` offline. Side finding
[#46](https://github.com/RBILLC/Hubitat/issues/46) (needs-triage): an off sent during standby writes nothing,
the monitor relights its halo by itself on wake, and the next off snaps instead of dimming out (model
bookkeeping since #35, not #44). Next: #41 (Driver 0.0.15, last before 1.0.0), then the 1.0.0 bump and
Steps 3 to 5; #45, #46, #26 later.

Status 2026-10-08 evening (Step 2, #41): Driver 0.0.15 implemented on main (`/implement`, Bridge
behaviour untouched, Bridge stays 0.0.10). Preferences `requestTimeoutSec`, `warmKelvin`, `coolKelvin`,
`pollIntervalMin` (the old settings removed on save with `device.removeSetting`); state
`lastMonitorError`/`lastMonitorErrorAt` (the old keys' values carried over on save, then removed);
every Driver comment one or two lines, the explanations moved to the Bridge README (`/moonhalo/on`
row, "Letting the Hub find the Bridge"); `CONTEXT.md` gains **Pacing** and "duration" is gone from
`model.py`, `http.py` and the Bridge README; `.gitignore` confirmed (`probe_state.json` ignored);
362 tests pass. Left to the user: import 0.0.15, save once, check the renamed preferences hold their
retyped values and the old settings and state keys are gone; then close #41 and bump to 1.0.0.

Status 2026-10-08 afternoon: #41 CLOSED after the hub check (commit a59a307 pushed; the raw import URL
served the CDN-cached 0.0.14 for minutes after the push, so the Driver was pasted in). First save after
the import showed the four defaults, the retyped values held on the next save; `lastMonitorError`/
`lastMonitorErrorAt` carried the 2026-10-07 value, old keys gone; a save with debug on logged no
`could not remove setting` line. Step 2 is complete. Next: the 1.0.0 bump (Driver changelog line and
Version line, Bridge `__version__`, README `/health` example; restart the task, re-import), then Steps
3 to 5.

Status 2026-10-08 late (Step 2, #47, added by the `/codebase-design` pass): Bridge 0.0.11 implemented on
main as 111ca9f (`/implement`, Bridge-only, Driver stays 0.0.15 with minimum Bridge 0.0.9). The DDC/CI
capabilities-string path is gone: `capabilities.py` and its tests, `DdcPort.read_capabilities` with the
Windows and fake primitives, the fake's capabilities knobs, the `capabilities` command; the port is two
primitives again and the serving path is untouched. README: command-line mode lists `monitors`, `read`,
`write`; one pointer at `docs/research/rd280ug-capabilities.md`; the 0xC0262582 row says reads and
writes fail alike; version examples 0.0.11. 342 tests pass (362 minus the 21 deleted plus one parser
test). Left to the user: restart the task on 0.0.11, `py -m moonhalo_bridge monitors` still selects
`by edid`, the hub shows `Bridge version 0.0.11` with no warning; then close #47 and bump to 1.0.0.

Status 2026-10-08 night: #47 CLOSED after the PC check. The task restarted on 0.0.11 at 15:15 (`schtasks /end` then `/run`): `/health` reported 0.0.11, `monitors` selected `BenQ RD280UG on \\.\DISPLAY1 (by edid)`, `bridge.log` showed detection by edid and the announcement; the hub logged `Bridge version 0.0.11` once at 15:17:02 and the device page showed it after a reload (the State Variables block is a page-load snapshot, not live). `/code-review` found nothing to fix. The 1.0.0 bump is PARKED by the user until they say so; nothing is queued. #45, #46, #26 later.

Status 2026-10-08 night (#46): Bridge 0.0.12 implemented on main as 785df2e (`/implement`, Bridge-only, Driver
stays 0.0.15). Target power `unknown` is resolved by one D7 read (low byte `0x1x` dark; anything else, or a
failed read, lit); an off from a lit halo with no Ramp in flight probes D9 first, so one sent while the monitor
sleeps (or the link is stuck) is refused with a 500 and the switch stays on; a dim-out whose D7 off never lands
sets Target power `unknown` and forgets the Applied state. 355 tests pass; `/code-review` found no standards
breach, its judgement calls applied (`_halo_lit_locked` renamed `_resolve_lit_locked`; no D7 read for an
explicit `transition=0`). Twelve of thirteen acceptance boxes ticked; the notes are in the ticket comment. Left to
the user: restart the task on 0.0.12 (`schtasks /end` then `/run`, `/health` reports 0.0.12), then the PC check
in the last box: off while asleep (hub log `Bridge rejected off`, switch stays on), button wake, off dims out
from full (a stuck link right after the button wake refuses that off too; the next one dims out), then a normal
dim-out, sleep, wake, halo stays dark, off writes the lone D7 off; then close #46. 1.0.0 stays PARKED. #45, #26
later.

Status 2026-10-08 evening: #46 CLOSED after a partial PC check, at the user's word. Task restarted on 0.0.12 at
16:52 (`/health` 0.0.12, device page Bridge Version 0.0.12, Monitor Link ok). Seen on the real halo: on from a
confirmed off relights and rises; off dims out and confirms; after `DisplaySwitch /internal` with the halo lit,
the wake (`/extend` plus the button) relit the halo by firmware and the next off dimmed out from the Applied step
10 (nine writes then D7 off), where 0.0.11 wrote a lone D7 off. Not run: the refusal while asleep (the hub's off
never reached the Bridge, cause on the hub side not established) and a confirmed off surviving sleep and wake;
both covered by tests only, the closing comment says so. 1.0.0 stays PARKED; nothing is queued. #45, #26 later.

Status 2026-10-08 evening, later (#48, from a preference audit the user asked for): Driver 0.0.16 implemented on
main as 0e9fd96 (`warmKelvin`/`coolKelvin` dropped and removed on save, the Bridge owns the Kelvin range;
every preference described, `(initial)` gone from the address titles; the Driver file and the root README
American throughout, the Bridge README and CONTEXT.md unchanged). Five boxes ticked; left to the user: import
0.0.16, save once, no Kelvin preferences on the device page, `setColorTemperature(3000)` still works; then close
#48. The 1.0.0 bump stays PARKED; when it comes, the Driver changelog starts from 0.0.16. #45, #26 later.

Status 2026-10-08 evening, last: #48 CLOSED after the hub check (0.0.16 imported and saved; the Preferences tab
shows the nine preferences with the new text and no Kelvin ones; hub default transition is 500 ms). Hub runs
Driver 0.0.16, PC runs Bridge 0.0.12; main is pushed and clean. Nothing queued. NEXT when the user says so: the
1.0.0 bump (Step 2 tail), then Steps 3 to 5 under #38. #45, #26 later.

- Driver comments: the user wants them terse, like classic Hubitat drivers (one or two lines per method,
  short header bullets). The 0.0.10 and 0.0.11 comments are; the older header "Behaviour" bullets and the
  `on()`, `setBridgeAddress`, announcement and purge comments are still long. Move anything worth keeping
  into the Bridge README or `model.py` docstrings, which is where explanations live.
- Glossary sweep: "duration" appears in `model.py` (Transition and Pacing docstrings), `http.py` and the
  Bridge README although `CONTEXT.md` lists it under Transition's avoid list; "Pacing" is used throughout
  the Bridge with no glossary entry. Either add the entries or reword.
- `.gitignore`: the `tools/probe_state.json` pattern did not match `Bridges/BenQ_MoonHalo/tools/` (fixed
  alongside this plan); confirm the file no longer shows as untracked.
- Driver preference renames, decided 2026-09-14 after #39 shipped (Driver 0.0.12): `timeoutSec` ->
  `requestTimeoutSec` (it sits next to `announceTimeoutSec`), `ctMinKelvin` -> `warmKelvin` and
  `ctMaxKelvin` -> `coolKelvin` (the titles already say warm and cool; "ct" is used nowhere else),
  `pollMinutes` -> `pollIntervalMin` (the unit-suffix style of the other timed preferences). Kept:
  `bridgeIp`/`bridgePort` (the state pair is `announcedIp`/`announcedPort` since 0.0.12),
  `announceTimeoutSec`, `colorStaging`, `defaultTransitionMs`, `logEnable`/`txtEnable`. A renamed
  preference is a new setting, so the value is retyped once and the old setting lingers: purge the four
  old names on save with `device.removeSetting(name)` (Device Object page, next to `clearSetting` and
  `updateSetting`) alongside `purgeStaleAttributes`. Update `updated()`'s log lines, the header comment
  and the root README preference list. Ship as Driver 0.0.13 with a changelog line, before the 1.0.0
  bump so only this hub pays the retype.
- Versions: Driver header says "1.0.0 on public announcement". Bump the Driver to 1.0.0 with a changelog
  line, the Bridge `__version__` to 1.0.0, the README `/health` example, and the Driver's "Version" line;
  restart the Bridge task and re-import the Driver on the hub.
- Review pass with `/code-review` against `main` before the bump; run `py -m unittest` from
  `Bridges/BenQ_MoonHalo` (289 tests as of tonight).

## Step 3: Hubitat community post

- Draft it in `docs/forum/` like the existing `google-home-colorsetting-request.md` (status line, suggested
  category, then the post). Category: **Custom Apps and Drivers** (the Google Home post targets Feedback).
- Content: what it is (BenQ RD280UG MoonHalo as a CT bulb through a small Python Bridge on the PC, DDC/CI
  over the Windows Monitor Configuration API, no third-party executable), how to install (import URL,
  Bridge README), what it does (on/off, level, colour temperature, transitions with a Sweep time, Google
  Home through the community integration since the built-in one gives CT-only devices no temperature
  control), known limits (ten brightness levels and seven colour steps in hardware; Windows only; the
  Bridge must run in the logged-on session because of session 0).
- Link the raw Driver URL and `Bridges/BenQ_MoonHalo/README.md`. The user posts it.

## Step 4: GitHub page clean-up

- The root `README.md` is the landing page: keep the driver list, install steps, the full preference list
  (including **Default transition (ms)**) and the pointer to the Bridge README. Check it against the
  Driver's actual preferences after the clean-up.
- Repository description and topics (hubitat, benq, ddc-ci, moonhalo) if not set.
- Confirm `docs/research/` and `docs/forum/` read as reference material, and that nothing refers to the
  dropped ControlMyMonitor approach as current.

## Step 5: website update

- The user maintains a website outside this repo; the content should match the forum post. Ask the user
  for the site and what it currently says about the MoonHalo before drafting.

## After this plan

- #26, Matter light from the PC, is the only other open issue and starts a new wayfinder round.
