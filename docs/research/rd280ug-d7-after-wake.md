# RD280UG: what D7 and D9 read after the monitor sleeps and wakes

Measured 2026-10-08, 15:38 to 15:48, for issue #46 (Bridge 0.0.11 serving, Driver 0.0.15). Reads
are `py -m moonhalo_bridge read D7` / `read D9` from the Bridge folder, each one
`GetVCPFeatureAndVCPFeatureReply` on `\\.\DISPLAY1`. Sleep is `DisplaySwitch.exe /internal` (the
RD280UG leaves the desktop), wake is `DisplaySwitch.exe /extend` plus the monitor's own button: the
extend alone did not bring the monitor back either time; it came back within seconds of the button.

## Why

Issue #46: an off that arrived while the monitor slept wrote nothing, the firmware relit the halo
at wake, and the Bridge's bookkeeping said off. The fix needs to know whether a D7 read can tell a
lit halo from a dark one after the firmware has restored it, given that issue #29 measured D7
reading its last written value (`0x0210`) while the halo was visibly lit from a D9 relight.

## Measurements

| Time | State of the halo (seen by the user) | Bridge Target | D7 read | D9 read | Notes |
|---|---|---|---|---|---|
| 15:22 | Lit, level 100, colour step 1 (set by the Bridge) | on | `0x0220` | `0x010A` | baseline, before any sleep |
| 15:39 | Dark during standby (not Attached) | on | not Attached | not Attached | `monitors`: `selected: none (... not attached ...)` |
| 15:40:17 | Relit by the firmware at wake, full brightness, no command sent | on | `0xC0262582` x 11 | `0xC0262582` | link stuck from the button wake until a button power-cycle |
| 15:43:17 | Lit (after the power-cycle; link answered 15 s after it) | on | **`0x0221`** | `0x010A` | the firmware's restore sets bit 0; the Bridge never wrote `0x0221` |
| 15:43:54 | Paced off through the Bridge: nine D9 writes then D7 off, 0.64 s | off | | | `ramp complete ... power_off=True` |
| 15:43:57 | Dark (1 s after the last write) | off | `0x0210` | `0x0101` | reads already current, not stale |
| 15:44:02 / 15:44:12 | Dark | off | `0x0210` | `0x0101` | unchanged at 5 s and 15 s |
| 15:47 | Dark during standby | off | not Attached | not Attached | |
| 15:48:07 | Still dark after the button wake | off | **`0x0211`** | `0x0101` | link answered on the first read this time |

## What this establishes

- **A D7 read reports the register the firmware restores from, not the last Bridge write.** After
  a wake the low byte carries an extra bit: `0x21` where the Bridge wrote `0x20`, `0x11` where it
  wrote `0x10`. Its meaning is undocumented (Didact's profile lists only `0x10` off, `0x20` on,
  `0x30` auto). A lit-or-dark decision must therefore mask it: the halo is dark when the low byte is
  `0x1x`, lit for anything else.
- **The wake-restore is visible in D7.** In the #46 case (D7 off never written) the register still
  says on, so a D7 read resolves the Bridge's "unknown" correctly.
- **A confirmed off survives sleep and wake.** With D7 off written, the halo stayed dark through
  standby and the button wake, and D7 read `0x0211`. The firmware restores the last register state.
- **Reads were current one second after a write**, so the staleness #29 saw lasts under a second.
  The Applied state is still trusted when known; a fresh read is a probe and a fallback.
- **The DDC/CI link can be stuck right after a button wake** (`0xC0262582` on every read for over
  a minute, cleared by a button power-cycle, answering 15 s later), or answer at once; both were seen
  within ten minutes. A failed D7 read is a real path, not a corner case, and counts as lit.
- **The standby recipe needs the button.** `DisplaySwitch.exe /extend` alone left the monitor
  asleep both times; it attached within seconds of the button press.

## Open

- The meaning of bit 0 in D7's low byte after a wake.
- Standby at the front button with the halo lit (the monitor stays Attached and writes succeed):
  what the halo and D7 do at button-on. Not measured; out of #46's scope.
