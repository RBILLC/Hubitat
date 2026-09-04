# Hubitat CT (Tunable White) Light Driver Conventions

Research date: 2026-09-03. Scope: what existing Hubitat drivers for colour-temperature ("white ambient") lights expose, what Hubitat's own docs say a CT light must expose to be treated normally by Google Home / Maker API / dashboards / Rule Machine, and what a CT-only driver (e.g. "MoonHalo") should replicate.

Convention used below: **[DOC]** = stated in official Hubitat documentation (authoritative). **[EX]** = demonstrated only by an example or community driver (precedent, not authority). Where a fact could not be found in any consulted source, this is stated explicitly as "not documented in the sources consulted."

---

## 1. Anchor drivers (baseline convention set)

### 1.1 `virtualRGBW.groovy` (Hubitat, "Virtual RGBW Light")
Source: https://raw.githubusercontent.com/hubitat/HubitatPublic/master/examples/drivers/virtualRGBW.groovy

- Capabilities declared: `Actuator`, `Color Control`, `Color Temperature`, `Switch`, `Switch Level`, `Light`, `ColorMode` (lines 10-16).
- Commands: `on()`, `off()`, `setLevel(value, rate=null)`, `setColor(Map)`, `setHue(value)`, `setSaturation(value)`, `setColorTemperature(value, level=null, tt=null)` (lines 44-126). No `refresh()`, `configure()`, `ChangeLevel`, `flash`, or preset commands.
- `setLevel(0)` calls `off()` and returns — no level=0 event is separately emitted (lines 56-60).
- `setColorTemperature`/`setColor`/`setHue`/`setSaturation` all force the switch on if it is currently off (e.g. line 119: `if (device.currentValue("switch") != "on") on()`) — no pre-staging option exists in this driver.
- CT is clamped to **2000-6000 K** via `limitIntegerRange(value,2000,6000)` (line 118).
- `colorMode` attribute is set explicitly to `"RGB"` or `"CT"` by whichever setter last ran (lines 72-73, 120-121) — this is capability `ColorMode`'s only documented value set, `["CT","RGB","EFFECTS"]` **[DOC]** (§3).
- `colorName` is derived by two hand-written bucket tables, one for hue (RGB) and one for Kelvin (CT) — `setGenericTempName()` uses 12 named buckets: Sodium, Starlight, Sunrise, Incandescent, Soft White, Warm White, Moonlight, Horizon, Daylight, Electronic, Skylight, Polar (lines 129-145). No built-in Hubitat helper is called for this — see §7.
- Events are emitted **optimistically**, synchronously inside the command method itself (`eventSend()`, lines 37-42) — there is no device to confirm against since this is a virtual driver.
- Only preference: `txtEnable` (bool, default `true`) description-text logging (line 21). No debug-log toggle, no auto-off timer.

### 1.2 `GenericZigbeeRGBWBulb.groovy` (Hubitat, "Generic ZigBee RGBW Light")
Source: https://raw.githubusercontent.com/hubitat/HubitatPublic/master/examples/drivers/GenericZigbeeRGBWBulb.groovy

- Capabilities: `Actuator`, `Color Control`, `Color Temperature`, `Configuration`, `Refresh`, `Switch`, `Switch Level`, `ChangeLevel`, `Light`, `ColorMode` (lines 43-52), plus a custom `updateFirmware` command (line 54) — **adds `Configuration`, `Refresh`, `ChangeLevel` versus the virtual anchor**.
- Preferences (lines 57-63): `transitionTime` (enum ms, default `1000`), `colorStaging` (bool, default `false`), `hiRezHue` (bool, default `false`), `logEnable` (bool, default `true`), `txtEnable` (bool, default `true`). `logsOff()` auto-disables debug logging after 1800 s (30 min) via `runIn(1800,logsOff)` (line 81).
- `colorStaging` preference is the key divergence from the virtual anchor: when the bulb is off and `colorStaging` is `false` (default), `setColor()`/`setColorTemperature()` turn the bulb on as part of applying the new color (lines 385-404, 491-513). When `colorStaging` is `true`, the same calls only pre-stage color/CT on the device without turning it on (lines 378-384, 493-500).
- `setColorTemperature(colorTemperature, level=null, tt=null)` (line 483) matches the 3-argument signature capability `ColorTemperature` documents **[DOC]** (§3).
- CT value is converted to/from the Zigbee "mireds" ("myred") unit via `1000000/kelvin` reciprocal math (lines 154, 486-487) — there is no hardcoded Kelvin clamp in this driver (unlike the virtual anchor's 2000-6000).
- Attribute events (`switch`, `level`, `hue`, `saturation`, `colorTemperature`, `colorMode`, `colorName`) are emitted from `parse()` **only after the device echoes back a Zigbee attribute report** (lines 84-182) — i.e. **confirmed, not optimistic**, unlike the virtual anchor.
- `startLevelChange(direction)` uses a hardcoded `unitsPerSecond = 100` (line 187) — not configurable.
- `colorName` uses the identical 12-bucket Kelvin table as the virtual anchor (lines 251-266), copy-pasted verbatim.

### How every other driver differs from these two anchors
See the per-driver notes in §2; the recurring axes of difference are: (a) whether `ColorMode`/`Light`/`ChangeLevel` are declared at all (CT-only real hardware tends to drop them), (b) whether events are optimistic or device-confirmed, (c) how CT range is bounded (hardcoded vs. discovered), (d) whether a "stage while off" preference exists, and (e) whether `setColorTemperature` implements all three documented parameters.

---

## 2. Other drivers read

### 2.1 `advancedZigbeeCTbulb.groovy` (Hubitat official example — CT-only, closest official analog to a CT-only driver)
Source: https://raw.githubusercontent.com/hubitat/HubitatPublic/master/examples/drivers/advancedZigbeeCTbulb.groovy (read in full, 660 lines)

- Capabilities: `Actuator`, `Switch`, `SwitchLevel`, `ChangeLevel`, `Bulb`, `Configuration`, `Color Temperature` (lines 80-86) — **no `Light`, no `ColorMode`** capability at all, unlike both anchors. This is the single most relevant divergence for a CT-only driver.
- Lines 87-88 contain `//capability "Level Preset"` and `//capability "Color Preset"` **commented out**, with the note "part of future capability Level Preset 1..100" (line 91). Instead the driver declares custom commands `flash` and `presetLevel(Number)` (lines 90-91) and an internal (non-capability) `presetColor(Map)` method (line 484). As confirmed against the live capability list (§3), **no `LevelPreset` or `ColorPreset` capability exists in Hubitat's documented capability list today** — this "future capability" apparently never shipped, or was retired; presetLevel/presetColor remain plain custom commands to this day.
- CT range is **not hardcoded** — `configure()` runs a multi-phase `runOptionTest()` state machine (lines 586-628) that queries the physical bulb for its actual min/max CT, falling back to `2700`-`6000` K only if the bulb doesn't report limits (lines 617-620).
- Extensive transition-time preferences, each independently configurable: `transitionTime` (level, default "1s"), `startLevelChangeRate` (default "Fast"), `onTransitionTime` (default "1s"), `offTransitionTime` (default "Use On transition time"), `ctTransitionTime` (default "Use Level transition time"), `minimumLevel` (default "5%"), `powerRestore` (default "On": on/off/last-state) (lines 121-129).
- `on()` explicitly restores the **driver-remembered** last level (`state.hexLevel.requested = state.hexLevel.current`, line 398) rather than relying on the device's own on/off memory — a stronger, software-side "restore last level" guarantee than either anchor provides.
- `setLevel(0)` while on fades the bulb to 1% and then powers off via a scheduled `switchOff()` once the transition completes (lines 537-540), rather than jumping straight to off.
- `setColorTemperature()` while off **turns the bulb on** (forces level+on before applying CT, lines 565-567) exactly like `GenericZigbeeRGBWBulb`'s `colorStaging=false` default; the *only* way to change CT/level without turning the bulb on is the separate `presetColor()`/`presetLevel()` commands, which set the attribute in software without touching the device when the switch is off (lines 525-527, 559-561).
- Events are emitted only after the device confirms (parse() driven), with explicit duplicate suppression (`if (rawValue == state.x.current) return`, lines 368, 388) — confirmed, non-optimistic, like `GenericZigbeeRGBWBulb`.
- `colorName` uses the same 12-bucket Kelvin table, expressed as a `Map` plus `.find{k,v -> temp < k}.value` idiom (lines 63-76, 377).
- `flash()` (lines 419-433) is a stateful toggle using the Zigbee Identify cluster (`FF FF` to start, `00 00` to stop) — it takes **no argument**, even though capability `Flash`'s documented `flash(rateToFlash)` command accepts an optional rate parameter (§3). This driver does not declare `capability "Flash"` at all; `flash` is a bare custom command (line 90).

### 2.2 `LifxColorBulbLegacy.groovy` (Hubitat official example — CT + RGB, LAN/cloud protocol)
Source: https://raw.githubusercontent.com/hubitat/HubitatPublic/master/examples/drivers/LifxColorBulbLegacy.groovy (read in full, 403 lines)

- Capabilities: `SwitchLevel`, `ColorTemperature`, `ColorControl`, `Switch`, `Refresh`, `Actuator`, `SignalStrength`, `Configuration`, `ColorMode`, `Polling` (lines 6-15) plus custom `command "flash"` (line 17). **Adds `SignalStrength` (rssi) and `Polling`** — a connectivity/health pair not present in either anchor, appropriate only for networked hardware.
- `pollInterval` preference (disabled/5/10/15/30/60 min, lines 21, 71-89) drives `poll()` → re-fetches actual device state on a timer, on top of any push-based updates.
- `setColorTemperature(Number temp, Number level=null, Number transitionTime=null)` (line 258) implements the full 3-parameter capability signature. Internally it forces `saturation = 0` (line 271) and sends one combined HSBK `SetColor` command, because LIFX represents CT and RGB in the same colour space — turns the bulb on afterward unless `colorStaging` is enabled (lines 275-277), same convention as §1.2/§2.1.
- `colorMode` is **inferred from the device's actual reported saturation** on state callback (`cmd.saturation > 0 ? RGB : CT`, lines 310-315) rather than being set procedurally by whichever setter ran last (contrast with the virtual anchor, which has no real device to ask).
- Events only sent via `eventProcess()` after an actual `LightState` device callback, and only if the value changed (lines 101-113) — confirmed, non-optimistic.
- `flash()` (lines 143-161) is implemented as an alternating `SetPower` on/off loop driven by a `flashRate` preference (default 750 ms, line 24) — a different mechanism from `advancedZigbeeCTbulb`'s Identify-cluster flash, but the same shape: no `capability "Flash"` declared, no argument accepted by the command itself (rate comes from a preference instead of the call).
- `colorName` again uses the identical 12-bucket Kelvin table (lines 337-352).

### 2.3 Other official example files checked and found not relevant
`genericComponentDimmer.groovy`, `genericComponentParentDemo.groovy`, `genericZWaveCentralSceneDimmer.groovy`, and `thirdRealityMatterNightLight.groovy` were inspected (`gh api repos/hubitat/HubitatPublic/contents/examples/drivers`); none declares `capability "ColorTemperature"`, so none is cited further. (`thirdRealityMatterNightLight.groovy` has `Color Control` but not `Color Temperature`.)

### 2.4 Community driver — RMoRobert "Virtual CT Bulb (Custom)" **[EX]**
Source: https://raw.githubusercontent.com/RMoRobert/Hubitat/master/drivers/virtual/virtual-ct-bulb-community.groovy (read in full, 131 lines). Author: Robert Morris, a well-known Hubitat community driver author.

- Capabilities: `Actuator`, `ColorTemperature`, `Switch`, `SwitchLevel`, `Light` — **no `ColorMode`, no `ChangeLevel`, no `Configuration`/`Refresh`** — the simplest possible CT-only driver among all sources read, and architecturally the closest precedent to a purely-virtual/software CT driver like MoonHalo (lines 26-33).
- `installed()` calls `setDefaultValues()` → `off()` then `setColorTemperature(2700,100)` (lines 41-45, 62-66) — establishes an explicit sensible default (2700 K, 100%) on first install rather than leaving attributes null.
- `setLevel`/`setColorTemperature` unconditionally turn the switch on if not already on (lines 86, 92, 100) — no pre-staging/`colorStaging` option at all, simpler than either anchor.
- Events are sent optimistically and immediately via `doSendEvent()` (lines 103-113); unlike the anchors, this driver does **not** skip re-sending an event when the value is unchanged — the "only if changed" check (line 105) governs only whether the description-text line is logged, not whether `sendEvent` fires.
- Same 12-bucket Kelvin `colorName` table, copied verbatim (lines 115-131).
- `logEnable`/`txtEnable` preferences (default both `true`) with the same 30-minute debug auto-off convention (lines 56-59).

### 2.5 Community driver — Inovelli "Bulb Multi-White LZW41" **[EX]**
Source: https://raw.githubusercontent.com/InovelliUSA/Hubitat/master/Drivers/inovelli-bulb-multi-white-lzw41.src/inovelli-bulb-multi-white-lzw41.groovy (read in full, 425 lines). Substantially rewritten by "bcopeland" — the same GitHub identity (Bryan Copeland) credited as author of the official `LifxColorBulbLegacy.groovy` anchor example, and matching the "bertabcd1234" community-author name given in the task.

- Capabilities: `SwitchLevel`, `ColorTemperature`, `Switch`, `Refresh`, `Actuator`, `Sensor`, `Configuration`, `ChangeLevel` (lines 70-77), plus an explicit `attribute "colorName", "string"` declaration (line 79) even though `ColorTemperature` already documents that attribute (§3) — redundant but harmless.
- Real hardware constraint: CT range is **hardcoded** `2700`-`6500` K (lines 97-98), represented internally as a warm-white/cold-white 0-255 channel ratio (Z-Wave `switchColorV2`, lines 103, 188-192, 278-293) — a two-channel LED architecture requiring its own conversion math, unlike the anchors' single Kelvin attribute.
- **Gap versus the documented capability**: `setColorTemperature(temp)` (line 278) implements only 1 of the 3 documented parameters (no `level`, no `transitionTime` argument) — calling it with 2 or 3 arguments as Rule Machine or Maker API might, per the capability's documented `setColorTemperature(colortemperature, level, transitionTime)` signature (§3), would fail with a missing-method error on this driver.
- `colorStaging` preference (default `false`) reproduces the "turn on unless staging" convention from §1.2/§2.1/§2.2 (lines 86, 288).
- Additional preferences not seen in the anchors: a Z-Wave "power fail load state restore" config parameter (bulb turns on vs. remembers last state, lines 93-94) — a genuine power-on-behaviour preference; `dimmingSpeed` (number, default 1, applied to both `on()`/`off()`/`setLevel()` durations, lines 88, 250-276); `eventFilter` (bool, default `false`, "Filter out duplicate events" — explicit, off-by-default de-dupe, line 89, 194-199).
- Events are emitted only after the actual Z-Wave `SwitchColorReport`/`SwitchMultilevelReport` is received (lines 211-248) — confirmed, non-optimistic.
- No `Light`, no `ColorMode`, no `flash` — reinforcing `advancedZigbeeCTbulb.groovy`'s pattern that CT-only devices commonly omit these.

### 2.6 Community driver — kkossev "Matter Advanced RGBW Light" **[EX]**
Source: https://raw.githubusercontent.com/kkossev/Hubitat/main/Drivers/Matter%20Advanced%20RGBW%20Light/Matter_Advanced_RGBW_Light.groovy (grepped/partially read; 1447 lines total, not read in full — RGBW+CT Matter driver, not CT-only, so treated as a secondary precedent).

- Declares `capability "ColorTemperature"` (line 55) among a larger RGBW capability set.
- `setColorTemperature(colortemperature, transitionTime=null)` (line 587) — again implements only **2 of the 3** documented parameters (missing `level`), the same gap pattern seen in the Inovelli driver (§2.5) — suggesting this is a common community shortcut, not a documented requirement.
- `colorName` again derived via a `.find{k,v -> x < k}.value` bucket-table idiom against a threshold map (lines 466-475), consistent with every other driver read.
- Notable preferences beyond anything in the official examples: `spammyReportsFilter` (enum) delays/coalesces rapid duplicate attribute reports before emitting a Hubitat event, to avoid flooding dashboards/automations with repeat events (lines 435-497); `healthCheckMethod`/`healthCheckInterval` (enum) drive device-offline detection (lines 87-88) — not a formal Hubitat capability, but a widespread community convention for reporting device health independent of any single command.

---

## 3. Capability reference (docs2.hubitat.com/en/developer/driver/capability-list)
Source: https://docs2.hubitat.com/en/developer/driver/capability-list (rendered via browser, since a plain fetch returns only the page title — full capability list retrieved 2026-09-03). **[DOC]**

- **`ColorTemperature`**: Attributes `colorName` (STRING), `colorTemperature` (NUMBER, unit `°K`). Commands: `setColorTemperature(colortemperature, level, transitionTime)` — `colortemperature` required NUMBER (Kelvin), `level` optional NUMBER, `transitionTime` optional NUMBER (seconds). No documented min/max Kelvin range, and no documented clamping behavior — every driver read (§1-§2) enforces its own range (2000-6000 hardcoded, 2700-6500 hardcoded, or device-discovered with a 2700-6000 fallback).
- **`SwitchLevel`**: Attribute `level` (NUMBER, unit `%`). Command `setLevel(level, duration)` — `level` required NUMBER (0-100), `duration` optional NUMBER (seconds).
- **`ChangeLevel`**: No attributes. Commands `startLevelChange(direction)` (`direction` required ENUM) and `stopLevelChange()`.
- **`LevelPreset`**: **Not present anywhere in the current capability list** as fetched. This corroborates `advancedZigbeeCTbulb.groovy`'s commented-out `//capability "Level Preset"` (§2.1) — there is no such capability to declare today; `presetLevel`/`presetColor` must be implemented as plain custom commands.
- **`Light`**: Attribute `switch` (ENUM `["on","off"]`). Commands `off()`, `on()` — functionally identical in shape to capability `Switch`. The docs do not explain why a driver would declare both `Light` and `Switch` together (as both anchors do); no documented distinction was found — see Open Questions.
- **`Flash`**: No attributes. Command `flash(rateToFlash)` — `rateToFlash` optional NUMBER, "Rate to flash in ms". **None of the drivers read (§1-§2) declare `capability "Flash"`** — all implement a bare custom `flash` command that takes no runtime argument (rate, if configurable, comes from a preference instead).
- **`ColorMode`**: Attribute `colorMode` — ENUM `["CT", "RGB", "EFFECTS"]`. No commands — this is a device/driver-reported attribute only, never a value Hubitat itself sets by calling into the driver.
- **`LightEffects`**: Attributes `effectName` (STRING), `lightEffects` (JSON_OBJECT). Commands `setEffect(effectnumber)`, `setNextEffect()`, `setPreviousEffect()`. Not implemented by any driver read (none of the sources support light effects) — not applicable to a plain CT bulb.
- **`colorName` attribute**: documented as a plain STRING under both `ColorControl` and `ColorTemperature` — **no enumerated vocabulary is specified by the docs**. The 12-name Kelvin bucket vocabulary (Sodium, Starlight, Sunrise, Incandescent, Soft White, Warm White, Moonlight, Horizon, Daylight, Electronic, Skylight, Polar) used identically by `virtualRGBW.groovy`, `GenericZigbeeRGBWBulb.groovy`, `advancedZigbeeCTbulb.groovy`, `LifxColorBulbLegacy.groovy`, and RMoRobert's community driver is purely a copy-pasted convention, not a documented standard.
- **No built-in `convertTemperatureToGenericColorName` helper was found or used anywhere in the sources consulted.** Every single driver read (official and community) hand-rolls the same if/else-if (or `Map.find`) bucket table rather than calling any such platform helper — if a helper by that name exists on the Hubitat platform, its use is not evidenced in any source read for this report.

---

## 4. Google Home integration
Source: https://docs2.hubitat.com/en/apps/google-home (rendered via browser 2026-09-03) **[DOC]**

- Documented, verbatim: "Google Home supports switches, dimmers, thermostats, RGB, RGBW and ColorTemperature bulbs." This is the only place the doc names `ColorTemperature` bulbs as a first-class supported category, confirming a CT-only driver is a legitimate, directly-supported device type (not merely tolerated as a fallback of RGBW).
- The rest of the page is a pairing/authorization walkthrough (Google Home mobile app → "Works with Google" → search "Hubitat" → sign in with the hub's administrator account → choose devices to authorize → assign each to a Google Home room) and notes that Google Home *reads from* Hubitat only (devices added directly in Google Home cannot be shared back to Hubitat), and that "Options should be left at default for device offline polling."
- **The page does not document which specific Hubitat capabilities, attributes, or commands Google Home inspects or calls** to decide how to present a device, nor what happens if a device declares `ColorTemperature` without `Switch`/`SwitchLevel`/`Light`/`ColorMode`. This is **not documented in the sources consulted** — see Open Questions.

## 5. Maker API
Source: https://docs2.hubitat.com/en/apps/maker-api (rendered via browser 2026-09-03; also fetched cleanly by plain WebFetch) **[DOC]**

- **Command invocation URL form**: `http://[hub_ip]/apps/api/[app_id]/devices/[device_id]/[command]/[secondary value]?access_token=[access_token]`. A single parameter is passed as `[secondary value]` directly in the path (e.g. `/devices/1/setLevel/50`). **Multiple scalar parameters are comma-separated** in that same path segment — the doc's own example: `/devices/1321/setCode/3,4321,Guest` for a 3-argument command. By this documented pattern, `setColorTemperature(colortemperature, level, transitionTime)` would be invoked as e.g. `/devices/1/setColorTemperature/2700,80,2` — **the docs do not show this exact example for `setColorTemperature`**, so this is an inference from the documented general multi-arg pattern, not a verbatim example; flagged accordingly.
- A special JSON-map calling convention exists, but is documented **only for `setColor`** (a `COLOR_MAP` capability parameter type): `/devices/[id]/setColor/{"hue":1,"saturation":100,"level":50}` (URL-encoded), with a Maker-API-specific extension allowing `{"hex":"FF0400"}` instead of HSB. Nothing analogous is documented for `setColorTemperature`, whose parameters are plain scalars, not a map.
- **Reading attributes**: `/devices/[device id]/attribute/[attribute name]` → `{"id":"123","attribute":"switch","value":"off"}`. Bulk reads are available via `/devices/[device id]` or `/devices/[device id]/all` (returns `capabilities`, `attributes`, and `commands` all together) and `/devices/[device id]/commands` (lists just the commands, e.g. `[{"command":"off"},{"command":"on"},{"command":"refresh"}]`).
- Explicit caution, quoted verbatim: *"There is a limited subset of allowed commands, so just because a command shows up in this list does not mean it will work via the API."* The doc does **not** enumerate which commands are excluded — **not documented in the sources consulted** whether custom commands like `presetLevel`/`presetColor`/`flash` are on the allowed list. Flagged as an open question below.
- Maker API surfaces whatever the driver declares (capabilities/attributes/commands, taken directly from the driver's own `metadata` block) — it does not add or require anything beyond what the driver's capabilities already expose.

---

## 6. Facts needed — consolidated

**Command set / capability that declares each**, across all drivers read:

| Command | Declaring capability [DOC] | Anchors | advancedZigbeeCTbulb | LifxColorBulbLegacy | RMoRobert virtual CT | Inovelli LZW41 | kkossev Matter RGBW |
|---|---|---|---|---|---|---|---|
| `on()`/`off()` | `Switch` or `Light` | both (both caps) | `Switch` only | `Switch` only | both (both caps) | `Switch` only | (part of larger set) |
| `setLevel(level, duration)` | `SwitchLevel` | yes | yes | yes | yes (duration ignored) | yes | yes |
| `setColorTemperature(ct, level, transitionTime)` | `ColorTemperature` | yes, full 3-arg | yes, full 3-arg | yes, full 3-arg | yes, full 3-arg (param named `rate`) | **partial: 1-arg only** | **partial: 2-arg, no `level`** |
| `startLevelChange`/`stopLevelChange` | `ChangeLevel` | GenericZigbeeRGBWBulb only | yes | not declared | not declared | yes | not confirmed |
| `presetLevel`/`presetColor` | not a capability (§3) | no | custom commands | no | no | no | no |
| `flash` | `Flash` capability exists [DOC] but unused | no | custom command, no arg | custom command, no arg | no | no | not confirmed |
| `refresh()` | `Refresh` | GenericZigbeeRGBWBulb only | yes | yes | no | yes | not confirmed |
| `configure()` | `Configuration` | GenericZigbeeRGBWBulb only | yes (+ auto-calibration) | yes | no | yes | not confirmed |
| `initialize()` | `Initialize` | not declared by any driver read | — | — | — | — | — |

**Attributes and value conventions**:
- `switch`: ENUM `on`/`off` [DOC, `Switch`/`Light`]. Universal.
- `level`: NUMBER 0-100, unit `%` [DOC, `SwitchLevel`]. Universal.
- `colorTemperature`: NUMBER, unit `°K` [DOC, `ColorTemperature`]. Kelvin range is undocumented at the capability level; every driver clamps independently (2000-6000 virtualRGBW; unconstrained/mireds-derived GenericZigbeeRGBWBulb; 2700-6000 discovered, else hardcoded fallback, advancedZigbeeCTbulb; 2700-6500 hardcoded Inovelli).
- `colorName`: STRING [DOC, both `ColorControl` and `ColorTemperature`], vocabulary undocumented; the 12-bucket Kelvin-name table is a copy-pasted convention, not a spec (§3).
- `colorMode`: ENUM `["CT","RGB","EFFECTS"]` [DOC, `ColorMode`]. Set procedurally by software in the two anchors and RMoRobert-style drivers; inferred from actual device state (`saturation`) in LifxColorBulbLegacy; not declared at all by CT-only official/community drivers (advancedZigbeeCTbulb, Inovelli LZW41) — precedent suggests `ColorMode` is optional for CT-only devices, though this is not stated as a rule anywhere in the docs.
- No driver read uses a `convertTemperatureToGenericColorName` helper (§3) — not documented in the sources consulted as existing at all.

**Common preferences and defaults**:
- Debug/description logging toggles (`logEnable`, `txtEnable`) with a 30-minute (`runIn(1800, ...)`) debug-log auto-off — present in `GenericZigbeeRGBWBulb`, `advancedZigbeeCTbulb`, `LifxColorBulbLegacy`, RMoRobert virtual CT, Inovelli LZW41. `virtualRGBW.groovy` has only `txtEnable`, no auto-off.
- Transition/duration preferences — `GenericZigbeeRGBWBulb`: single `transitionTime` (default 1000 ms). `advancedZigbeeCTbulb`: five independent transition-time preferences (level/on/off/CT/start-level-change-rate) plus `minimumLevel` (default 5%) and `powerRestore` (default "On"). `LifxColorBulbLegacy`: `colorTransition` (default 0 = ASAP), `flashRate` (default 750 ms), `pollInterval` (default disabled). Inovelli LZW41: `colorTransition` (default 0), `dimmingSpeed` (default 1).
- "Stage color/level while off without turning on" preference — `colorStaging` (bool, default `false`) in `GenericZigbeeRGBWBulb`, `LifxColorBulbLegacy`, and Inovelli LZW41; achieved via dedicated `presetLevel`/`presetColor` commands instead of a preference in `advancedZigbeeCTbulb`. Absent entirely (no staging option) in `virtualRGBW.groovy` and RMoRobert's virtual CT bulb.
- Power-on/restore behaviour — `powerRestore` enum (on/off/last-state, default "On") in `advancedZigbeeCTbulb`; a Z-Wave config parameter for "power fail load state restore" in Inovelli LZW41. Not present in either anchor or the virtual community driver (no physical power-loss concept for virtual devices).
- Duplicate-event / spammy-report filtering — `eventFilter` (bool, default `false`) in Inovelli LZW41; `spammyReportsFilter` (enum, delay window) in kkossev's Matter driver. Both anchors instead silently skip re-sending an unchanged value (`if (value == currentValue) return`) rather than exposing this as a preference.
- Health-check / offline detection — `healthCheckMethod`/`healthCheckInterval` enums in kkossev's Matter driver only; not present in any other source read.

**Behavioural facts**:
- `setLevel(0)`: turns the light off in `virtualRGBW.groovy` (explicit `off()` call) and, more elaborately, in `advancedZigbeeCTbulb.groovy` (fades to 1% then schedules a hardware off). `GenericZigbeeRGBWBulb.groovy` and Inovelli LZW41 simply forward `0`/`0xFF`-style values to the device and let the device (or its own report) resolve the resulting `switch` state.
- `on()` after dimming: `advancedZigbeeCTbulb.groovy` explicitly restores the **driver-remembered** last level in software (`state.hexLevel.requested = state.hexLevel.current`). The two anchors and the virtual community driver rely on the device (or, for virtual devices, on the `level` attribute simply never having changed) rather than any explicit "restore" logic.
- `setColorTemperature` while off: **every driver read turns the bulb on by default** (`virtualRGBW`, `GenericZigbeeRGBWBulb` with `colorStaging=false`, `advancedZigbeeCTbulb` via its private setter, `LifxColorBulbLegacy`, RMoRobert virtual CT, Inovelli LZW41 via `basicSet(0xFF)`) — the *only* opt-outs are the `colorStaging` preference (GenericZigbeeRGBWBulb, LifxColorBulbLegacy, Inovelli) or dedicated `presetColor`/`presetLevel` commands (advancedZigbeeCTbulb).
- Optimistic vs. confirmed events: purely virtual drivers (`virtualRGBW.groovy`, RMoRobert's virtual CT bulb) emit events **optimistically**, synchronously inside the command handler, since there is no physical device to wait on. Every driver that talks to real hardware (`GenericZigbeeRGBWBulb`, `advancedZigbeeCTbulb`, `LifxColorBulbLegacy`, Inovelli LZW41, kkossev's Matter driver) emits attribute events **only from its `parse()`/event-callback path**, i.e. after the device confirms the change — never directly from the command method.

**What Google Home and Maker API specifically rely on**:
- Google Home [DOC, §4]: relies only on the device being one of the named supported categories ("...ColorTemperature bulbs..."); the doc gives no further technical detail about which capabilities/attributes/commands it inspects. **Not documented in the sources consulted** beyond that top-level statement.
- Maker API [DOC, §5]: relies entirely on whatever capabilities/commands/attributes the driver's own `metadata` block declares — it exposes `/devices/.../[command]/[args]` for any command found via `/devices/[id]/commands`, and `/devices/.../attribute/[name]` for any attribute, but explicitly warns that not everything listed is guaranteed to work through the API, without saying which commands are affected.

---

## 7. Recommended for the MoonHalo Driver

### Must replicate
1. Declare `capability "Switch"`, `capability "SwitchLevel"`, and `capability "ColorTemperature"` as the minimum trio — Google Home's own doc names "ColorTemperature bulbs" as a directly supported category (https://docs2.hubitat.com/en/apps/google-home), and Maker API surfaces exactly the capabilities/commands the driver declares (https://docs2.hubitat.com/en/apps/maker-api) — every driver read declares this trio at minimum.
2. Implement the **full 3-argument `setColorTemperature(colortemperature, level, transitionTime)` signature** exactly as documented (https://docs2.hubitat.com/en/developer/driver/capability-list, `ColorTemperature` section) — two of six drivers read (Inovelli LZW41 §2.5, kkossev Matter RGBW §2.6) implement only a subset of these parameters, which is a documented gap risk, not a documented requirement, for callers (Rule Machine, Maker API) that pass all three arguments.
3. Emit `switch`, `level`, and `colorTemperature` events on every state change, since Maker API's `/devices/.../attribute/[name]` endpoint and dashboards/Rule Machine read these attributes directly (https://docs2.hubitat.com/en/apps/maker-api, "Device Endpoints" §); confirmed by every driver read (`virtualRGBW.groovy` lines 37-42; `GenericZigbeeRGBWBulb.groovy` lines 84-182; `advancedZigbeeCTbulb.groovy` lines 348-393).
4. Define and honor a consistent "turn on when a color/level command arrives while off" behaviour (optionally with a `colorStaging`-style opt-out) — universal convention across every driver read: `virtualRGBW.groovy` (line 119), `GenericZigbeeRGBWBulb.groovy` (colorStaging preference, lines 378-404), `advancedZigbeeCTbulb.groovy` (lines 565-567), `LifxColorBulbLegacy.groovy` (lines 275-277), RMoRobert virtual CT bulb (lines 86-100), Inovelli LZW41 (line 288).
5. Map `setLevel(0)` to an off state, and enforce/document a Kelvin range for `setColorTemperature` — capability `ColorTemperature` itself specifies no range (https://docs2.hubitat.com/en/developer/driver/capability-list), so precedent (`virtualRGBW.groovy` 2000-6000, `advancedZigbeeCTbulb.groovy` discovered-or-2700-6000-fallback) is the only guidance available; pick and clamp to an explicit range rather than leaving it unbounded.
6. Provide `refresh()` via `capability "Refresh"` so dashboards, Maker API, and Rule Machine can force a state read — present in `GenericZigbeeRGBWBulb.groovy`, `advancedZigbeeCTbulb.groovy`, and Inovelli LZW41 (all real-device drivers read); a purely virtual/software driver like RMoRobert's omits it, so this is "must replicate" only if MoonHalo fronts something with state that can drift (worth keeping regardless, for consistency with dashboards' generic refresh button).
7. Decide deliberately whether events are emitted optimistically or only after confirmation, and be consistent — every hardware-backed driver read confirms via its event/parse path before sending Hubitat events (§6); a purely virtual driver is the only case where optimistic (synchronous) emission is an established, sanctioned pattern (`virtualRGBW.groovy`, RMoRobert virtual CT bulb).

### Nice to have
1. `capability "ColorMode"` with the `colorMode` attribute — both anchors declare it, but CT-only drivers, official and community, commonly omit it (`advancedZigbeeCTbulb.groovy` §2.1, Inovelli LZW41 §2.5) since a CT-only device never needs to report `"RGB"`; add only if MoonHalo could ever need to distinguish CT vs. another mode.
2. `colorName` attribute populated with the conventional 12-bucket Kelvin vocabulary (Sodium…Polar) — not a documented requirement (capability-list only specifies STRING with no vocabulary, https://docs2.hubitat.com/en/developer/driver/capability-list), but used identically by `virtualRGBW.groovy`, `GenericZigbeeRGBWBulb.groovy`, `advancedZigbeeCTbulb.groovy`, `LifxColorBulbLegacy.groovy`, and RMoRobert's community driver, so replicating it maximizes look-alike consistency with other CT bulbs in dashboards.
3. `capability "ChangeLevel"` (`startLevelChange`/`stopLevelChange`) for press-and-hold dimming in dashboard tiles — present in `GenericZigbeeRGBWBulb.groovy`, `advancedZigbeeCTbulb.groovy`, and Inovelli LZW41.
4. Custom `presetLevel`/`presetColor` commands to stage a level/CT value while off without turning the bulb on, mirroring `advancedZigbeeCTbulb.groovy` (§2.1) — useful precedent given `LevelPreset`/`ColorPreset` do not exist as real capabilities today (§3).
5. A bare custom `flash` command (no formal `capability "Flash"` declared, matching every driver read even though the capability exists, https://docs2.hubitat.com/en/developer/driver/capability-list) — see `advancedZigbeeCTbulb.groovy` (§2.1) and `LifxColorBulbLegacy.groovy` (§2.2) for two different valid implementations.
6. A power-on-behaviour preference (on/off/last-state) — `advancedZigbeeCTbulb.groovy`'s `powerRestore` (§2.1) and Inovelli LZW41's power-fail config parameter (§2.5); relevant to MoonHalo only if it fronts something with its own power/reset semantics.
7. Independently configurable transition times for level vs. on vs. off vs. color-temperature changes — `advancedZigbeeCTbulb.groovy` (§2.1) is the richest precedent for this.
8. Debug/description logging toggles with a 30-minute debug auto-off — present in nearly every driver read except the bare `virtualRGBW.groovy` anchor (§1.1); a maintainability convention, not something Google Home/Maker API/Rule Machine observe.
9. Duplicate-event filtering / spammy-report delay preference (Inovelli's `eventFilter`, kkossev's `spammyReportsFilter`, §2.5-§2.6) if MoonHalo's upstream source can emit rapid repeat updates.
10. `SignalStrength`/`Polling` capabilities (`LifxColorBulbLegacy.groovy`, §2.2) — only relevant if MoonHalo talks to real networked hardware rather than being a purely local/virtual driver.

---

## 8. Open questions

1. Whether Google Home specifically requires `capability "Light"` and/or `capability "ColorMode"` in addition to `Switch`/`SwitchLevel`/`ColorTemperature`, or is satisfied by the minimal trio alone — not documented in the sources consulted (https://docs2.hubitat.com/en/apps/google-home names only supported device *categories*, not the underlying capability contract).
2. Whether Maker API's stated "limited subset of allowed commands" (https://docs2.hubitat.com/en/apps/maker-api, "Device Endpoints" §) would block custom, non-capability commands such as `presetLevel`/`presetColor`/`flash` — not documented; the doc does not enumerate which commands are excluded.
3. Whether Rule Machine has any capability-specific requirements or quirks beyond simply calling documented capability commands/reading documented attributes — out of scope of the sources this report was scoped to consult (Rule Machine's own documentation was not one of the listed sources and was not separately investigated); not documented in the sources consulted.
4. Whether the `LevelPreset`/`ColorPreset` capabilities implied by `advancedZigbeeCTbulb.groovy`'s commented-out declarations (§2.1) ever shipped under another name, or were dropped outright — the current capability-list page (fetched 2026-09-03) shows neither; not documented in the sources consulted whether this is a historical removal or the page was always incomplete.
5. What Kelvin range Google Home itself expects or enforces for a "ColorTemperature bulb" (e.g., whether it rejects/clips values outside some range before calling `setColorTemperature`) — not documented in the sources consulted; every driver read enforces its own, differing range (2000-6000 K, 2700-6500 K, or a per-device discovered range).
6. Exactly why both anchor drivers (and none of the CT-only drivers) declare `capability "Light"` alongside `capability "Switch"` when the two capabilities have byte-for-byte identical documented attributes/commands (§3) — no documented rationale was found in any source consulted.

---

## Sources read

- https://raw.githubusercontent.com/hubitat/HubitatPublic/master/examples/drivers/virtualRGBW.groovy
- https://raw.githubusercontent.com/hubitat/HubitatPublic/master/examples/drivers/GenericZigbeeRGBWBulb.groovy
- https://raw.githubusercontent.com/hubitat/HubitatPublic/master/examples/drivers/advancedZigbeeCTbulb.groovy
- https://raw.githubusercontent.com/hubitat/HubitatPublic/master/examples/drivers/LifxColorBulbLegacy.groovy
- https://raw.githubusercontent.com/hubitat/HubitatPublic/master/examples/drivers/genericComponentDimmer.groovy (checked, not relevant — no ColorTemperature)
- https://raw.githubusercontent.com/hubitat/HubitatPublic/master/examples/drivers/genericComponentParentDemo.groovy (checked, not relevant)
- https://raw.githubusercontent.com/hubitat/HubitatPublic/master/examples/drivers/genericZWaveCentralSceneDimmer.groovy (checked, not relevant)
- https://raw.githubusercontent.com/hubitat/HubitatPublic/master/examples/drivers/thirdRealityMatterNightLight.groovy (checked, not relevant — ColorControl but not ColorTemperature)
- https://docs2.hubitat.com/en/developer/driver/capability-list (rendered via browser)
- https://docs2.hubitat.com/en/apps/google-home (rendered via browser)
- https://docs2.hubitat.com/en/apps/maker-api (rendered via browser; also fetchable via plain WebFetch)
- https://raw.githubusercontent.com/RMoRobert/Hubitat/master/drivers/virtual/virtual-ct-bulb-community.groovy
- https://raw.githubusercontent.com/InovelliUSA/Hubitat/master/Drivers/inovelli-bulb-multi-white-lzw41.src/inovelli-bulb-multi-white-lzw41.groovy
- https://raw.githubusercontent.com/kkossev/Hubitat/main/Drivers/Matter%20Advanced%20RGBW%20Light/Matter_Advanced_RGBW_Light.groovy
- `gh api repos/hubitat/HubitatPublic/contents/examples/drivers` (directory listing, used to select which example files to read)
- `gh api search/code` queries against GitHub code search (used to locate the community drivers above)
