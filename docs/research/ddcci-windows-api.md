# DDC/CI on Windows: VESA wire-level facts (from Didact) + Win32 Monitor Configuration API

Research document for the Hubitat DDC/CI Windows bridge. Nothing here was ported or executed —
Didact is a macOS/Swift app and cannot run on Windows; its source was read only to extract
documented facts about DDC/CI protocol behavior (VCP packing, timing, and a real vendor quirk)
that generalize to any DDC/CI implementation, including the Windows one we will call from Python.

Every claim below carries a citation. Where a source doesn't say something, this document says so
explicitly rather than guessing.

---

## Half 1 — Facts extracted from Didact (macOS, Swift; not run, not ported)

Repository: https://github.com/gingerbeardman/Didact (branch `main`). Files fetched via
`https://raw.githubusercontent.com/gingerbeardman/Didact/main/<path>`, plus a small number of
additional files not in the original reading list (`DDCListener.swift`, `DDCProbe.swift`,
`AppleSiliconDDC+Capabilities.swift`, `TeachWizardWindowController.swift`, `ControlTemplate.swift`,
`MonitorConfigBuilder.swift`) that were pulled in because they turned out to hold the actual
answers to specific questions below (noted inline). The full repo file tree was retrieved from
`https://api.github.com/repos/gingerbeardman/Didact/git/trees/main?recursive=1` to find these.

### 1. The DDC write: opcode, 16-bit value, byte order, and read-back verification

**Documented facts:**

- `AppleSiliconDDC.write` takes a `UInt8` command and a `UInt16` value and builds a 3-byte payload
  where the value is split into explicit high/low bytes:
  ```swift
  static public func write(service: IOAVService?, command: UInt8, value: UInt16, ...) -> Bool {
    var send: [UInt8] = [command, UInt8(value >> 8), UInt8(value & 255)]
    ...
  }
  ```
  (`Didact/AppleSiliconDDC.swift`, line 96-97,
  https://raw.githubusercontent.com/gingerbeardman/Didact/main/Didact/AppleSiliconDDC.swift)
  So the wire packet after the VCP opcode byte is `[highByte, lowByte]` — big-endian / MSB-first,
  which matches the VESA DDC/CI "Set VCP Feature" command layout (opcode, value-high, value-low).
- The read path decodes the reply the same way (big-endian): `max = reply[6]*256 + reply[7]`,
  `current = reply[8]*256 + reply[9]` (`Didact/AppleSiliconDDC.swift`, lines 87-88).
- **No automatic value read-back after a write.** `write()` passes an *empty* `reply` array to
  `performDDCCommunication` (line 98: `var reply: [UInt8] = []`), and inside
  `performDDCCommunication` the I2C read-and-checksum step is gated on `if !reply.isEmpty` (line
  115) — so for a write call that block never runs. A write's "success" is solely whether the I2C
  write transaction itself acknowledged (`success = IOAVServiceWriteI2C(...) == 0`, line 113), not
  a subsequent VCP value read-back. (`Didact/AppleSiliconDDC.swift`, lines 102-127)
- **`noVerify` handling.** The field is declared on `Control` as
  `var noVerify: Bool? = nil   // monitor lies on read-back after a write`
  (`Didact/MonitorConfig.swift`, line 109,
  https://raw.githubusercontent.com/gingerbeardman/Didact/main/Didact/MonitorConfig.swift) and is
  set `true` on both D7 sub-controls in the shipped BenQ profile (see §3). Searching the fetched
  files for actual *consumers* of `.noVerify` (not just the declaration) turned up **no branch in
  the DDC transport (`AppleSiliconDDC.swift`) or in the write path (`DisplayController.swift`)** —
  neither file references `noVerify` at all. The only place the flag is consumed is UI/wizard logic
  in `Didact/TeachWizardWindowController.swift` (not in the original file list; fetched to resolve
  this), which uses it purely to change wizard copy and skip an automated confirmation step:
  ```swift
  if item.template.noVerify || item.template.noRead {
      guidance += " This setting can't be read back, so watch the monitor as you test — if nothing changes, click Skip; your monitor may not have it."
  }
  ```
  (`Didact/TeachWizardWindowController.swift`, lines 662-664,
  https://raw.githubusercontent.com/gingerbeardman/Didact/main/Didact/TeachWizardWindowController.swift)
  and again at line 753 to decide whether to trust a curated option list over observed values
  during the learning flow. **Conclusion: `noVerify` is an app-level "don't trust a post-write
  read for this control" flag consumed only by the Teach Wizard's UX; it does not alter the DDC
  transport's write behavior, which never did a value read-back to begin with.**

### 2. Timing and retries

**Documented facts** (`Didact/AppleSiliconDDC.swift`, `performDDCCommunication`, lines 102-127,
https://raw.githubusercontent.com/gingerbeardman/Didact/main/Didact/AppleSiliconDDC.swift):

```swift
for _ in 1 ... (numOfRetryAttemps ?? 4) + 1 {                 // line 110: 5 attempts by default
  for _ in 1 ... max((numOfWriteCycles ?? 2) + 0, 1) {         // line 111: 2 write cycles by default
    usleep(writeSleepTime ?? 10000)                            // line 112: 10ms before each write
    success = IOAVServiceWriteI2C(...) == 0                    // line 113
  }
  if !reply.isEmpty {
    usleep(readSleepTime ?? 50000)                             // line 116: 50ms before the read
    if IOAVServiceReadI2C(...) == 0 { success = checksum(...) == reply[...] }  // lines 117-119
  }
  if success { return success }                                // line 121-123
  usleep(retrySleepTime ?? 20000)                               // line 124: 20ms between retry attempts
}
```
- Default write sleep: 10,000 µs (10 ms) before each I2C write.
- Default write cycles per attempt: 2 (the same write is sent twice).
- Default read settle time: 50,000 µs (50 ms) before reading back a reply (reads only; writes skip
  this since their `reply` is empty).
- Default retry-attempt sleep: 20,000 µs (20 ms) between full retry attempts.
- Default retry attempts: `numOfRetryAttemps ?? 4`, and the loop runs `+ 1` times, i.e. **5 total
  attempts** by default.

**The ~70 ms throttle in `DisplayController.swift`.** This is not a DDC-transport constant — it is
an *app-level UI debounce* for slider (range) controls, so a fast-dragged slider doesn't flood the
DDC bus with a write per pixel of drag:
```swift
func set(_ control: Control, to value: Int, throttle: Bool = false) {
    cache[control.stateKey] = value
    persistIfNeeded(control, value: value)
    if throttle {
        let key = control.stateKey
        throttleWork[key]?.cancel()
        let work = DispatchWorkItem { [weak self] in self?.performWrite(control, value: value) }
        throttleWork[key] = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.07, execute: work)
    } else {
        performWrite(control, value: value)
    }
}
```
(`Didact/DisplayController.swift`, lines 126-139, especially line 135,
https://raw.githubusercontent.com/gingerbeardman/Didact/main/Didact/DisplayController.swift).
There is no comment in the source naming this "70ms" explicitly — the file header comment only
says DDC I/O "can sleep tens of milliseconds with retries" (lines 6-7) — the exact figure is the
literal `0.07` (seconds) passed to `asyncAfter`.

- **No delay is added after a write before a subsequent read** in `performWrite` itself — when a
  packed/masked register write needs the current register value first, it *reads before writing*
  (see §3), not after. The only "after write" behavior is the general
  `performDDCCommunication` retry-sleep (20 ms) if the write attempt itself failed and is retried
  (line 124), which applies uniformly to all DDC calls, not specifically post-write-then-read.
- Listen mode's polling loop (`DDCListener.swift`, not in the original file list but fetched to
  understand read timing) explicitly documents *why* it keeps the transport's default settle time
  rather than shaving it: "Reliable polling: keep the library's default ~50ms read-settle and
  retries so slow codes (e.g. the multiplexed Moon Halo register) are never dropped — aggressive
  timing silently skipped exactly the codes we care about." (`Didact/DDCListener.swift`, lines
  111-117, https://raw.githubusercontent.com/gingerbeardman/Didact/main/Didact/DDCListener.swift)

### 3. MoonHalo on the BenQ RD280UG — packed vs. channel schemes

**Verbatim JSON** for the D7 and D9 entries (`Didact/Monitors/BenQ-RD280UG.json`, lines 9-22,
https://raw.githubusercontent.com/gingerbeardman/Didact/main/Didact/Monitors/BenQ-RD280UG.json):

```json
    { "kind": "cycle", "label": "Moon Halo", "vcp": "d7", "valueMask": "0x00ff", "noRead": true, "noVerify": true,
      "options": [
        { "value": "0x30", "label": "Auto" },
        { "value": "0x20", "label": "On" },
        { "value": "0x10", "label": "Off" }
      ] },
    { "kind": "range", "label": "Brightness", "vcp": "d9", "byte": "low", "min": 1, "max": 10,
      "disableWhen": { "vcp": "d7", "equals": "0x30" } },
    { "kind": "range", "label": "Color Temperature", "vcp": "d9", "byte": "high", "min": 1, "max": 7 },
    { "kind": "cycle", "label": "Moon Halo Light Mode", "vcp": "d7", "valueMask": "0xff00", "noVerify": true,
      "options": [
        { "value": "0x0100", "label": "270°" },
        { "value": "0x0200", "label": "360°" }
      ] },
```

**The Control schema defines three distinct "shared register" mechanisms** (`Didact/MonitorConfig.swift`,
lines 88-93, 141-152, 179-188):

- **`valueMask` scheme** (bit-mask over a shared raw register). Two or more `Control`s point at the
  *same* `vcp` code; each carries its own `valueMask` (e.g. `0x00ff`, `0xff00`). On write,
  `performWrite`'s `valueMask` branch reads the current register (from cache or from hardware),
  then for every sibling control sharing that VCP code and having a `valueMask`, recombines:
  ```swift
  reg = (reg & ~siblingMask) | (v & siblingMask)
  ```
  (`Didact/DisplayController.swift`, lines 144-161, specifically line 156) before writing the whole
  16-bit register back with one `AppleSiliconDDC.write` call. On read, `Control.byteValue` extracts
  a control's own bits with `raw & mask` (`Didact/MonitorConfig.swift`, line 185).
- **`byte: high/low` scheme** ("packed" 16-bit register split into two 8-bit halves). Two controls
  share one `vcp` code, one tagged `"byte": "high"`, the other `"byte": "low"`. `performWrite`'s
  `byte` branch does the analogous read-modify-write, but with a *byte* selector instead of an
  arbitrary mask:
  ```swift
  switch sibling.byte {
  case .high: reg = (reg & 0x00FF) | ((v & 0xFF) << 8)
  case .low:  reg = (reg & 0xFF00) | (v & 0xFF)
  case nil: break
  }
  ```
  (`Didact/DisplayController.swift`, lines 162-186, specifically lines 177-181). This is the exact
  "rebuild a 16-bit register from a sibling control's cached value" behavior asked about — the
  sibling's value comes from `cacheSnapshot[sibling.stateKey] ?? sibling.byteValue(reg)` (line 176):
  the in-memory cache if we have it, otherwise decoded from a hardware read of the current register.
  On read, `Control.byteValue` does `(raw >> 8) & 0xFF` for `.high` or `raw & 0xFF` for `.low`
  (`Didact/MonitorConfig.swift`, lines 180-182).
- **`channel` scheme** (high byte selects a channel; write encodes `(channel << 8) | value`). This
  is a *separate*, third mechanism defined in the schema:
  ```swift
  var channel: HexValue? = nil // high byte for channel-multiplexed writes (chan<<8 | value)
  ...
  var channelByte: UInt8? { channel.map { UInt8($0.value & 0xFF) } }
  ```
  (`Didact/MonitorConfig.swift`, line 90 and line 142), consumed in `performWrite`'s final
  `else if` branch:
  ```swift
  } else if let channel = control.channelByte {
      payload = (UInt16(channel) << 8) | UInt16(value & 0xFF)
  }
  ```
  (`Didact/DisplayController.swift`, lines 187-188). Unlike the `valueMask`/`byte` branches, this
  branch does **not** read the current register first — the previous channel's value simply gets
  overwritten by whichever channel is written last, which is exactly the multiplexed-read caveat
  discussed in §4.

**D7 power values.** `0x10` = Off, `0x20` = On, `0x30` = Auto — present verbatim in the shipped
JSON's `options` array quoted above (`Didact/Monitors/BenQ-RD280UG.json`, lines 11-13). Confirmed:
task's stated mapping (0x10=off/0x20=on/0x30=auto) matches the source exactly.

**D7 light-mode high-byte values.** `0x0100` = 270°, `0x0200` = 360° — present verbatim in the
"Moon Halo Light Mode" `options` array (`Didact/Monitors/BenQ-RD280UG.json`, lines 20-21), and that
control's `valueMask` is `"0xff00"` (line 18), i.e. these two option values occupy only the high
byte of the D7 register, consistent with 0x0100/0x0200 being high-byte-only values. Confirmed.

**Which scheme does the SHIPPED RD280UG profile actually use for d7/d9?**
Grepping the shipped `Didact/Monitors/BenQ-RD280UG.json` for the literal string `"channel"` finds
**zero matches** — the `channel` field is never used anywhere in this profile. The shipped profile
uses:
- **D7** (Moon Halo power + light mode): the **`valueMask`** scheme — `"valueMask": "0x00ff"` for
  power (On/Off/Auto) and `"valueMask": "0xff00"` for light-mode angle, both on the *same* `vcp:
  "d7"` code.
- **D9** (Moon Halo brightness + color temperature): the **`byte: high/low`** packed scheme —
  `"byte": "low"` for Brightness and `"byte": "high"` for Color Temperature, both on the *same*
  `vcp: "d9"` code.
- The **`channel`** mechanism (chan<<8|value) is defined in the `Control` schema and is exercised
  by `performWrite`'s code, but is **not used by the shipped BenQ RD280UG JSON for d7 or d9, or for
  any other control in that file.**

**Discrepancy worth flagging: the README's own prose contradicts the shipped JSON.** The
project's `README.md` field-reference table and prose describe d9 as using the `channel` scheme:
> "**Multiplexed registers**: some BenQ features share one VCP code, selected by the high byte.
> Moon Halo brightness and colour temperature both live on `d9` (`channel: "0x01"` and `channel:
> "0x07"`); Didact writes `(channel << 8) | value`."
(`README.md`, lines 94-96, https://raw.githubusercontent.com/gingerbeardman/Didact/main/README.md)
This does not match the actual shipped `Didact/Monitors/BenQ-RD280UG.json`, which uses `"byte":
"low"`/`"byte": "high"` for d9, not `channel`, as quoted above. This is a plain textual
inconsistency between the README (likely written for an earlier iteration of the profile or as a
simplified illustrative example) and the file actually shipped in the same commit. Documented here
as observed, not resolved by any source.

### 4. Reading a multiplexed register: `readChannels` and `byteValue`

**The exact name `readChannels` does not exist anywhere in the Swift source** (confirmed by
grepping the full text of `Didact/MonitorConfig.swift`, `Didact/DisplayController.swift`, and
`Didact/AppleSiliconDDC.swift` — no match). **It does exist as a documented field name in
`README.md`'s field-reference table**, which is the source of the exact wording the task
description uses:
> "`readChannels` | range/cycle/toggle | High byte(s) that identify this control's value on
> **read** (a multiplexed read returns only the last-touched channel). Defaults to `channel`."
(`README.md`, line 87, https://raw.githubusercontent.com/gingerbeardman/Didact/main/README.md)

This is a **discrepancy between documentation and shipped code**: the `Control` struct in
`Didact/MonitorConfig.swift` (the actual schema the JSON decoder uses) has no `readChannels`
property at all — only `channel` (write-side) exists (`Didact/MonitorConfig.swift`, line 90). The
closest real equivalent to "read a multiplexed register" is `Control.byteValue(_:)`:
```swift
func byteValue(_ raw: Int) -> Int {
    switch byte {
    case .high: return (raw >> 8) & 0xFF
    case .low: return raw & 0xFF
    case nil:
        if channelByte != nil { return raw & 0xFF }
        if let mask = valueMask?.value { return raw & mask }
        return raw
    }
}
```
(`Didact/MonitorConfig.swift`, lines 179-188). For a channel-multiplexed control
(`channelByte != nil`), this unconditionally returns the **low byte** of whatever raw value was
read — it does **not** check that the high byte (the channel selector) in the read reply actually
matches this control's expected channel. In other words, the code's actual behavior is consistent
with the README's stated caveat ("a multiplexed read returns only the last-touched channel"): a
read of a multiplexed VCP code returns whichever channel's value was *last written* (the monitor's
internal state), and Didact's `byteValue` trusts that without verifying the channel byte on read.
This is corroborated independently by `Tools/dump.swift`'s decode helper, which explicitly decodes
the high byte as "channel" and the low byte as "value" only when describing/labeling a read result
for a human, not when a `Control` decides its own value:
```swift
if controls.contains(where: { $0.channelByte != nil }) {
    let channel = UInt8((raw >> 8) & 0xFF)
    let value = raw & 0xFF
    if let label = controls.first(where: { $0.channelByte == channel })?.label {
        return "\(label)=\(value)"
    }
    return String(format: "ch 0x%02X=%d", channel, value)
}
```
(`Tools/dump.swift`, lines 88-95, https://raw.githubusercontent.com/gingerbeardman/Didact/main/Tools/dump.swift;
identical logic appears in `Didact/DDCListener.swift`, lines 146-153).

**Note:** the shipped BenQ RD280UG profile doesn't actually exercise the `channel`/`channelByte`
path at all (see §3), so this multiplexed-read caveat is documented behavior/schema design in
Didact generally, not something the shipped profile currently relies on for D7/D9.

### 5. Out-of-range values and `disableWhen`

**Documented facts:**
- Nothing in the fetched Didact source validates or clamps a value *before* sending it to the
  monitor on write — `performWrite`'s branches mask/pack/shift the value but never check it against
  `min`/`max` before calling `AppleSiliconDDC.write` (`Didact/DisplayController.swift`, lines
  141-196). Range clamping (`clampedRange`) exists only for **interpreting a value read back**, not
  for validating a value about to be written:
  ```swift
  private func clampedRange(_ v: Int) -> Int {
      guard kind == .range else { return v }
      let lo = min ?? 0
      let hi = max ?? v
      return Swift.min(Swift.max(v, lo), hi)
  }
  ```
  (`Didact/MonitorConfig.swift`, lines 195-200, used by `interpretRead`, lines 190-193). Nothing in
  the fetched files describes the monitor itself refusing or ignoring out-of-range values — Didact
  simply doesn't send values outside a slider's configured `min`/`max` in normal UI use, and no
  comment in the source discusses monitor-side rejection behavior. **Not documented in the sources
  consulted**: what the BenQ RD280UG actually does if sent an out-of-range VCP value.
- The `disableWhen` rule for the shipped Moon Halo Brightness control:
  ```json
  { "kind": "range", "label": "Brightness", "vcp": "d9", "byte": "low", "min": 1, "max": 10,
    "disableWhen": { "vcp": "d7", "equals": "0x30" } },
  ```
  (`Didact/Monitors/BenQ-RD280UG.json`, line 16) — i.e. Moon Halo Brightness (on d9) is disabled
  whenever d7's power sub-register equals `0x30` (Auto). This is consumed by:
  ```swift
  func isDisabled(_ control: Control) -> Bool { control.disableWhen.map(matches) ?? false }
  private func matches(_ cond: Control.Condition) -> Bool {
      if cond.system == "hdr", isHDREnabled { return true }
      guard let vcp = cond.vcp else { return false }
      let prefix = "\(vcp.value)/\(cond.channel?.value ?? -1)/"
      let values = cache.compactMap { key, value in key.hasPrefix(prefix) ? value : nil }
      guard !values.isEmpty else { return false }
      if let equals = cond.equals, values.contains(equals.value) { return true }
      ...
  }
  ```
  (`Didact/DisplayController.swift`, lines 68-82). This is purely a **UI-layer read-only/greyed-out
  state** — it renders the control disabled in the menu; it does not prevent a `SetVCPFeature`-style
  write from being attempted at the DDC layer if one were issued programmatically. No source file
  describes the monitor firmware itself enforcing this rule.

---

## Half 2 — Windows Monitor Configuration API (Microsoft Learn)

### 6. Exact signatures, DLLs, and error retrieval

All function-level facts below are quoted from each function's "Syntax" and "Requirements"
sections on Microsoft Learn.

| Function | Signature (from MS Learn "Syntax") | Return / errors | DLL |
|---|---|---|---|
| `EnumDisplayMonitors` | `BOOL EnumDisplayMonitors([in] HDC hdc, [in] LPCRECT lprcClip, [in] MONITORENUMPROC lpfnEnum, [in] LPARAM dwData);` | "If the function succeeds, the return value is nonzero. If the function fails, the return value is zero." (page does not mention `GetLastError` for this function) | **User32.dll** — Requirements table: "**Library** \| User32.lib", "**DLL** \| User32.dll" |
| `MONITORENUMPROC` (callback type) | `BOOL Monitorenumproc(HMONITOR unnamedParam1, HDC unnamedParam2, LPRECT unnamedParam3, LPARAM unnamedParam4)` — "return **TRUE**" to continue enumeration, "return **FALSE**" to stop | n/a (callback, not exported) | n/a — defined in `winuser.h`; page's Requirements table lists Header only, no Library/DLL row |
| `GetMonitorInfoW` | `BOOL GetMonitorInfoW([in] HMONITOR hMonitor, [out] LPMONITORINFO lpmi);` | "If the function succeeds, the return value is nonzero. If the function fails, the return value is zero." | **User32.dll** — "**Library** \| User32.lib", "**DLL** \| User32.dll" |
| `GetNumberOfPhysicalMonitorsFromHMONITOR` | `BOOL GetNumberOfPhysicalMonitorsFromHMONITOR([in] HMONITOR hMonitor, [out] LPDWORD pdwNumberOfPhysicalMonitors);` | "If the function succeeds, the return value is **TRUE**. If the function fails, the return value is **FALSE**. To get extended error information, call **GetLastError**." | **Dxva2.dll** — "**Library** \| Dxva2.lib", "**DLL** \| Dxva2.dll" |
| `GetPhysicalMonitorsFromHMONITOR` | `BOOL GetPhysicalMonitorsFromHMONITOR([in] HMONITOR hMonitor, [in] DWORD dwPhysicalMonitorArraySize, [out] LPPHYSICAL_MONITOR pPhysicalMonitorArray);` | same GetLastError pattern as above | **Dxva2.dll** |
| `PHYSICAL_MONITOR` (struct) | `typedef struct _PHYSICAL_MONITOR { HANDLE hPhysicalMonitor; WCHAR szPhysicalMonitorDescription[PHYSICAL_MONITOR_DESCRIPTION_SIZE]; } PHYSICAL_MONITOR, *LPPHYSICAL_MONITOR;` — "A physical monitor description is always an array of 128 characters." | n/a (struct) | n/a — header-only (`physicalmonitorenumerationapi.h`); Requirements table lists no Library/DLL row for the struct itself |
| `SetVCPFeature` | `BOOL SetVCPFeature([in] HANDLE hMonitor, [in] BYTE bVCPCode, [in] DWORD dwNewValue);` | "If the function succeeds, the return value is **TRUE**. If the function fails, the return value is **FALSE**. To get extended error information, call **GetLastError**." | **Dxva2.dll** — "**Library** \| Dxva2.lib", "**DLL** \| Dxva2.dll" |
| `GetVCPFeatureAndVCPFeatureReply` | `BOOL GetVCPFeatureAndVCPFeatureReply([in] HANDLE hMonitor, [in] BYTE bVCPCode, [out] LPMC_VCP_CODE_TYPE pvct, [out] LPDWORD pdwCurrentValue, [out] LPDWORD pdwMaximumValue);` | same GetLastError pattern | **Dxva2.dll** |
| `GetCapabilitiesStringLength` | `BOOL GetCapabilitiesStringLength([in] HANDLE hMonitor, [out] LPDWORD pdwCapabilitiesStringLengthInCharacters);` | same GetLastError pattern | **Dxva2.dll** |
| `CapabilitiesRequestAndCapabilitiesReply` | `BOOL CapabilitiesRequestAndCapabilitiesReply([in] HANDLE hMonitor, [out] LPSTR pszASCIICapabilitiesString, [in] DWORD dwCapabilitiesStringLengthInCharacters);` | same GetLastError pattern | **Dxva2.dll** |
| `DestroyPhysicalMonitors` | `BOOL DestroyPhysicalMonitors([in] DWORD dwPhysicalMonitorArraySize, [in] LPPHYSICAL_MONITOR pPhysicalMonitorArray);` | same GetLastError pattern | **Dxva2.dll** |

Sources (one per row, matching the order above):
https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-enumdisplaymonitors ,
https://learn.microsoft.com/en-us/windows/win32/api/winuser/nc-winuser-monitorenumproc ,
https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getmonitorinfow ,
https://learn.microsoft.com/en-us/windows/win32/api/physicalmonitorenumerationapi/nf-physicalmonitorenumerationapi-getnumberofphysicalmonitorsfromhmonitor ,
https://learn.microsoft.com/en-us/windows/win32/api/physicalmonitorenumerationapi/nf-physicalmonitorenumerationapi-getphysicalmonitorsfromhmonitor ,
https://learn.microsoft.com/en-us/windows/win32/api/physicalmonitorenumerationapi/ns-physicalmonitorenumerationapi-physical_monitor ,
https://learn.microsoft.com/en-us/windows/win32/api/lowlevelmonitorconfigurationapi/nf-lowlevelmonitorconfigurationapi-setvcpfeature ,
https://learn.microsoft.com/en-us/windows/win32/api/lowlevelmonitorconfigurationapi/nf-lowlevelmonitorconfigurationapi-getvcpfeatureandvcpfeaturereply ,
https://learn.microsoft.com/en-us/windows/win32/api/lowlevelmonitorconfigurationapi/nf-lowlevelmonitorconfigurationapi-getcapabilitiesstringlength ,
https://learn.microsoft.com/en-us/windows/win32/api/lowlevelmonitorconfigurationapi/nf-lowlevelmonitorconfigurationapi-capabilitiesrequestandcapabilitiesreply ,
https://learn.microsoft.com/en-us/windows/win32/api/physicalmonitorenumerationapi/nf-physicalmonitorenumerationapi-destroyphysicalmonitors

**MONITORINFOEXW / MONITORINFOF_PRIMARY.** `MONITORINFO` (the base struct) is:
```cpp
typedef struct tagMONITORINFO {
  DWORD cbSize;
  RECT  rcMonitor;
  RECT  rcWork;
  DWORD dwFlags;
} MONITORINFO, *LPMONITORINFO;
```
with `dwFlags` documented as: "A set of flags that represent attributes of the display monitor. The
following flag is defined. | Value | Meaning | \| MONITORINFOF_PRIMARY | This is the primary
display monitor. |"
(https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-monitorinfo).
`MONITORINFOEXW` is a superset adding one field:
```cpp
typedef struct tagMONITORINFOEXW : tagMONITORINFO {
  WCHAR szDevice[CCHDEVICENAME];
} MONITORINFOEXW, *LPMONITORINFOEXW;
```
(https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-monitorinfoexw). Both
struct pages list only a Header requirement (`winuser.h`), no Library/DLL row (structs, not
exported functions). `GetMonitorInfoW`'s Remarks: "You must set the **cbSize** member of the
structure to sizeof(MONITORINFO) or sizeof(MONITORINFOEX) before calling the **GetMonitorInfo**
function. Doing so lets the function determine the type of structure you are passing to it."
(https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getmonitorinfow).

### 7. Does `SetVCPFeature` take a full-width value in one call? Documented range limits?

**Yes** — `dwNewValue` is declared as `DWORD` (32-bit), not a 16-bit or byte type:
```cpp
BOOL SetVCPFeature(
  [in] HANDLE hMonitor,
  [in] BYTE   bVCPCode,
  [in] DWORD  dwNewValue
);
```
Parameter description: "`[in] dwNewValue` — Value of the VCP code."
(https://learn.microsoft.com/en-us/windows/win32/api/lowlevelmonitorconfigurationapi/nf-lowlevelmonitorconfigurationapi-setvcpfeature)
So a Windows caller passes the entire (up to 16-bit, per MCCS) VCP value in one `SetVCPFeature`
call via a single `DWORD` — there is no separate high/low-byte split at this API layer (that
splitting, per Half 1, happens inside the DDC/CI wire protocol itself, which the OS driver handles
internally).

**Documented value-range limits:** none beyond the implicit DWORD width and the parameter
description above. The same page's Warning banner (present verbatim on every low-level function
page fetched) is the closest thing to a caveat about values:
> "The physical monitor configuration functions work using the VESA Monitor Control Command Set
> (MCCS) standard over an I²C interface. Many monitors don't fully implement that standard; so your
> use of these commands might result in undefined monitor behavior. We don't recommend using these
> functions for arbitrary monitors without physically validating that they work as intended."
No page states a hard numeric ceiling (e.g. "must be ≤ 0xFFFF") for `dwNewValue` — **not documented
in the sources consulted** beyond "value of the VCP code" and the MCCS-conformance warning.

### 8. Service / interactive-desktop requirement — documented or not?

**Direct statement about these monitor APIs and services: none found.** None of the fetched pages —
`EnumDisplayMonitors`, `GetMonitorInfoW`, `GetNumberOfPhysicalMonitorsFromHMONITOR`,
`GetPhysicalMonitorsFromHMONITOR`, `SetVCPFeature`, `GetVCPFeatureAndVCPFeatureReply`,
`GetCapabilitiesStringLength`, `CapabilitiesRequestAndCapabilitiesReply`, `DestroyPhysicalMonitors`,
"Monitor Configuration", "About Monitor Configuration", "Using Monitor Configuration", or "Using
the Low-Level Monitor Configuration Functions" — contains any sentence mentioning services,
session 0, window stations, or "interactive desktop" requirements. None of their Requirements
tables list a desktop/session restriction (only OS-version, header, library, DLL rows appear, as
quoted in §6).

**Related-but-not-identical general guidance exists** on Microsoft Learn's "Interactive Services"
page (this is the general Windows-services doc, not a monitor-API-specific one):
> "Services cannot directly interact with a user as of Windows Vista. Therefore, the techniques
> mentioned in the section titled Using an Interactive Service should not be used in new code."
> ...
> "By default, services use a noninteractive window station and cannot interact with the user."
> ...
> "All services run in Terminal Services session 0. Therefore, if an interactive service displays a
> user interface, it is visible only to the user who connected to session 0."
(https://learn.microsoft.com/en-us/windows/win32/services/interactive-services). This page never
mentions `EnumDisplayMonitors`, GDI, `HMONITOR`, or the DDC/CI monitor-configuration APIs at all —
its scope is windows/dialogs/message boxes and window stations generally, not display enumeration
or DDC/CI specifically.

**Plain statement:** Whether a Windows service (running in Session 0, on the non-interactive
window station) can successfully call `EnumDisplayMonitors` and the physical-monitor / VCP
functions at all is **undocumented** in the Microsoft Learn pages checked — there is no direct
statement either way. `EnumDisplayMonitors` and `GetMonitorInfoW` are GDI/USER32 calls, which
generically depend on a window station/desktop association per the general session-0 guidance
above, but no monitor-configuration-specific page confirms or denies this for a service context.
Any conclusion about whether the planned Windows bridge can run as a service is therefore an
**inference**, not a documented fact — see "Open questions" below.

### 9. Documented timing guidance

**Documented facts, quoted verbatim, all from the low-level function reference pages' Remarks
sections:**
- `SetVCPFeature`: "This function takes about 50 milliseconds to return."
  (https://learn.microsoft.com/en-us/windows/win32/api/lowlevelmonitorconfigurationapi/nf-lowlevelmonitorconfigurationapi-setvcpfeature)
- `GetVCPFeatureAndVCPFeatureReply`: "This function takes about 40 milliseconds to return."
  (https://learn.microsoft.com/en-us/windows/win32/api/lowlevelmonitorconfigurationapi/nf-lowlevelmonitorconfigurationapi-getvcpfeatureandvcpfeaturereply)
- `GetCapabilitiesStringLength`: "This function usually returns quickly, but sometimes it can take
  several seconds to complete."
  (https://learn.microsoft.com/en-us/windows/win32/api/lowlevelmonitorconfigurationapi/nf-lowlevelmonitorconfigurationapi-getcapabilitiesstringlength)
- `CapabilitiesRequestAndCapabilitiesReply`: "This function usually returns quickly, but sometimes
  it can take several seconds to complete."
  (https://learn.microsoft.com/en-us/windows/win32/api/lowlevelmonitorconfigurationapi/nf-lowlevelmonitorconfigurationapi-capabilitiesrequestandcapabilitiesreply)
- All four low-level function pages carry the identical Warning banner: "The physical monitor
  configuration functions work using the VESA Monitor Control Command Set (MCCS) standard over an
  I²C interface. Many monitors don't fully implement that standard; so your use of these commands
  might result in undefined monitor behavior. We don't recommend using these functions for
  arbitrary monitors without physically validating that they work as intended." (same four URLs as
  above)

**Not documented in the sources consulted:** none of the fetched pages (including "Using the
Low-Level Monitor Configuration Functions",
https://learn.microsoft.com/en-us/windows/win32/monitor/using-the-low-level-monitor-configuration-functions,
and "About Monitor Configuration",
https://learn.microsoft.com/en-us/windows/win32/monitor/about-monitor-configuration) contain any
statement about thread-safety, concurrent calls from multiple threads/processes, or a recommended
minimum delay between successive calls. The "Using the Low-Level..." page's only content is the
8-step call sequence (EnumDisplayMonitors → GetNumberOfPhysicalMonitorsFromHMONITOR →
GetPhysicalMonitorsFromHMONITOR → GetCapabilitiesStringLength →
CapabilitiesRequestAndCapabilitiesReply → parse → GetVCPFeatureAndVCPFeatureReply →
SetVCPFeature), reproduced faithfully; it does not discuss concurrency at all.

### 10. Python ctypes facts for calling this API from 64-bit Python

Source: https://docs.python.org/3/library/ctypes.html (Python 3 `ctypes` docs), plus the actual
`ctypes.wintypes` module source for its exact contents (the prose docs page does not enumerate
`wintypes`' contents, so the module source itself — the authoritative reference — was read
directly: https://raw.githubusercontent.com/python/cpython/3.12/Lib/ctypes/wintypes.py, cross-checked
against the 3.9 branch at the same path to confirm the fact is not version-specific).

- **`WinDLL` + `use_last_error=True`.** ctypes docs: "Functions in these libraries use the `stdcall`
  calling convention." and "The *use_last_error* parameter, when set to true, enables the same
  mechanism for the Windows error code which is managed by the `GetLastError()` and
  `SetLastError()` Windows API functions" (https://docs.python.org/3/library/ctypes.html). Usage:
  `dxva2 = ctypes.WinDLL("dxva2", use_last_error=True)`.
- **`ctypes.get_last_error()`**: "Returns the current value of the ctypes-private copy of the
  system `LastError` variable in the calling thread." (same page) — this is what a Python wrapper
  calls immediately after a `BOOL`-returning Win32 call returns `FALSE`, to surface the
  `GetLastError()` value documented in §6's table for every low-level/physical-monitor function.
- **`WINFUNCTYPE`** for the `MONITORENUMPROC` callback: "ctypes.WINFUNCTYPE(*restype*, *\*argtypes*,
  *use_errno=False*, *use_last_error=False*) — The returned function prototype creates functions
  that use the `stdcall` calling convention." (same page). `MONITORENUMPROC`'s actual signature
  (from §6) is `BOOL (HMONITOR, HDC, LPRECT, LPARAM)`, so the Python type is
  `WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, wintypes.LPRECT, wintypes.LPARAM)`.
- **`.argtypes` / `.restype`**: "By default functions are assumed to return the C int type. Other
  return types can be specified by setting the `restype` attribute of the function object." with
  example usage `printf.argtypes = [c_char_p, c_char_p, c_int, c_double]` and
  `libc.time.restype = c_time_t` (https://docs.python.org/3/library/ctypes.html). Every function in
  §6's table needs both set explicitly (Win32 `BOOL` return, and its declared parameter types) since
  ctypes cannot infer them from the DLL alone.
- **`ctypes.wintypes` contents** — confirmed directly from CPython's own source
  (`Lib/ctypes/wintypes.py`, both the 3.9 and 3.12 branches):
  - `BYTE = ctypes.c_ubyte`, `DWORD = ctypes.c_ulong`, `WCHAR = ctypes.c_wchar`,
    `HANDLE = ctypes.c_void_p`, `HDC = HANDLE`, `HWND = HANDLE`.
  - `LPARAM` is defined conditionally on pointer size (signed `LONG_PTR`): the module comment reads
    "LPARAM is defined as LONG_PTR (signed type)", with `LPARAM = ctypes.c_long` on 32-bit and
    `LPARAM = ctypes.c_longlong` on 64-bit builds.
  - `RECT` is defined as a `ctypes.Structure` with four `LONG` fields.
  - **`HMONITOR` is defined**: `HMONITOR = HANDLE` (line 82 of `wintypes.py` in both the 3.9 and
    3.12 branches checked). **This corrects a common assumption**: the task brief for this
    document anticipated that HMONITOR "often isn't predefined" in `ctypes.wintypes` — that is not
    the case for the CPython versions checked; `HMONITOR` has been present in `wintypes.py`
    alongside the other `H*` handle aliases for a long time. A bridge implementation can `from
    ctypes.wintypes import HMONITOR` directly rather than defining it manually.
  - What genuinely is **not** in `wintypes.py` and must be hand-declared: `PHYSICAL_MONITOR` (a
    `physicalmonitorenumerationapi.h`-specific struct with a fixed-size `WCHAR` array field, not a
    generic Windows GDI/USER type) and `MC_VCP_CODE_TYPE` (an enum specific to
    `lowlevelmonitorconfigurationapi.h`). These have no `ctypes.wintypes` equivalents and must be
    defined as a `ctypes.Structure` / `ctypes.c_int`-based enum by the bridge code itself.
- **`ctypes.Structure` subclass**: "Structures and unions must derive from the `Structure` and
  `Union` base classes which are defined in the `ctypes` module. Each subclass must define a
  `_fields_` attribute. `_fields_` must be a list of *2-tuples*, containing a *field name* and a
  *field type*." (https://docs.python.org/3/library/ctypes.html) — this is exactly the mechanism
  needed to declare `PHYSICAL_MONITOR` in Python:
  ```python
  class PHYSICAL_MONITOR(ctypes.Structure):
      _fields_ = [("hPhysicalMonitor", wintypes.HANDLE),
                  ("szPhysicalMonitorDescription", wintypes.WCHAR * 128)]
  ```
  (128 comes from `PHYSICAL_MONITOR_DESCRIPTION_SIZE`, per §6's quoted Remarks: "A physical monitor
  description is always an array of 128 characters.").
- **Arrays of structures**: "The recommended way to create array types is by multiplying a data
  type with a positive integer: `TenPointsArrayType = POINT * 10`"
  (https://docs.python.org/3/library/ctypes.html) — directly applicable to allocating the
  `pPhysicalMonitorArray` buffer that `GetPhysicalMonitorsFromHMONITOR` fills:
  `arr = (PHYSICAL_MONITOR * n)()`.
- **`ctypes.byref`**: "Returns a light-weight pointer to *obj*, which must be an instance of a
  ctypes type." with the note: "If you just want to pass a pointer to an object to a foreign
  function call, you should use `byref(obj)` which is much faster [than `pointer(obj)`]."
  (https://docs.python.org/3/library/ctypes.html) — used for every `[out]` `DWORD`/struct parameter
  in §6's table (e.g. `byref(num_monitors)` for `GetNumberOfPhysicalMonitorsFromHMONITOR`).

---

## Proposed DDC module interface

Signatures only — no implementation. Each states which documented Win32 call(s) it wraps (all from
§6/§9 above).

```python
def list_monitors() -> list[MonitorInfo]:
    """Wraps: EnumDisplayMonitors + MONITORENUMPROC callback, then for each HMONITOR:
    GetMonitorInfoW (MONITORINFOEXW, for szDevice / MONITORINFOF_PRIMARY),
    GetNumberOfPhysicalMonitorsFromHMONITOR, GetPhysicalMonitorsFromHMONITOR."""

def close_monitors(monitors: list[MonitorInfo]) -> None:
    """Wraps: DestroyPhysicalMonitors. Must be called on every PHYSICAL_MONITOR handle
    obtained from GetPhysicalMonitorsFromHMONITOR to avoid a handle leak (per that
    function's documented Remarks)."""

def get_capabilities(monitor: PhysicalMonitorHandle) -> str:
    """Wraps: GetCapabilitiesStringLength, then CapabilitiesRequestAndCapabilitiesReply."""

def read_vcp(code: int, monitor: PhysicalMonitorHandle) -> tuple[int, int, int]:
    """Wraps: GetVCPFeatureAndVCPFeatureReply. Returns (current_value, max_value, vcp_code_type)."""

def write_vcp(code: int, value: int, monitor: PhysicalMonitorHandle) -> None:
    """Wraps: SetVCPFeature. Raises on GetLastError() when the BOOL return is FALSE."""

def get_last_error_message() -> str:
    """Wraps: ctypes.get_last_error() (paired with WinDLL(..., use_last_error=True)) and
    FormatMessage-style translation of the Win32 error code, for error reporting after
    any of the above returns FALSE."""
```

## Open questions

- **Session 0 / service question — unresolved by documentation.** As found in §8, no Microsoft
  Learn page directly states whether a Windows service (Session 0, non-interactive window station)
  can successfully call `EnumDisplayMonitors` / the physical-monitor and VCP functions. This is the
  single most decision-relevant open question for a Hubitat bridge that might need to run as a
  service rather than an interactive-user process, and it can only be resolved empirically (running
  the bridge as a service on the target machine and observing whether these calls succeed) — not by
  further documentation search, since the sources consulted here simply do not address it.
- **Undocumented timing numbers.** The 40 ms / 50 ms figures in §9 are Microsoft's own stated
  averages for `GetVCPFeatureAndVCPFeatureReply` / `SetVCPFeature`; no equivalent number is given
  for `EnumDisplayMonitors`, `GetMonitorInfoW`, `GetNumberOfPhysicalMonitorsFromHMONITOR`, or
  `GetPhysicalMonitorsFromHMONITOR` (these are not DDC/CI wire operations, so a fast in-process
  return is expected, but this is inference, not a documented number). No documented recommendation
  exists for how long to wait between a `SetVCPFeature` write and a subsequent `GetVCPFeatureAndVCPFeatureReply`
  read-back if the bridge wants to verify a write landed — Half 1's Didact findings (10 ms pre-write,
  50 ms pre-read, 20 ms between retries, as documented facts about a *different* implementation of
  the same underlying DDC/CI protocol) are the only concrete numbers found anywhere in the sources
  consulted, and are offered only as a plausible starting point, not as Windows-API-documented
  guidance.
- **Vendor-specific quirks (e.g. a BenQ-style multiplexed/packed register) are entirely outside MS
  Learn's scope.** The Windows API treats every VCP code as an opaque `BYTE` code + `DWORD` value;
  nothing in the Win32 documentation says anything about packed 16-bit sub-registers, channel
  multiplexing, or a monitor "lying" on read-back after a write (Didact's `noVerify` concept, §1).
  If the Hubitat bridge needs to support a monitor with this kind of vendor quirk, that knowledge
  will have to come from a per-model profile (analogous to Didact's JSON profiles) layered on top
  of the generic `read_vcp`/`write_vcp` primitives proposed above — Microsoft's API surface has no
  concept of this at all.
- **The README/shipped-JSON discrepancy in Didact (§3, §4)** was documented as observed but not
  resolved — it's unclear from the sources whether the README is stale (describing an earlier
  version of the RD280UG profile that did use `channel` for d9) or aspirational. It does not affect
  the Windows bridge design, since the bridge will define its own profile format, but it means the
  Didact README's field-reference table should not be treated as ground truth for what the shipped
  code does — the JSON and `.swift` files are the ground truth used throughout Half 1.
- **Monitor-side out-of-range behavior** (does the BenQ RD280UG, or DDC/CI monitors generally,
  clamp/ignore/error on an out-of-range `SetVCPFeature`/write?) is not documented in either the
  Didact source or the Microsoft Learn pages consulted — see §5 and §7. This would need either
  vendor documentation (MCCS spec, BenQ's own docs) or empirical testing against the actual target
  hardware.

---

## Verification

- Output written to exactly `C:\Users\RBILLC\source\repos\Hubitat\docs\research\ddcci-windows-api.md`.
- No other file in the repository was created or modified; all intermediate downloads (raw Didact
  source files, a CPython `wintypes.py` copy) were written only to the session scratchpad directory
  outside the repository, purely to get exact line numbers for citation and were not copied into
  the repo.
- Every numbered fact (1-10) above carries at least one URL citation, and Didact-sourced claims
  additionally carry a file path + line reference. Every place where the underlying code/docs
  diverged from the task's assumed facts (`noVerify`'s actual consumer, the `readChannels`/README
  vs. shipped-JSON discrepancy, the `channel`-vs-actual-scheme question, and `HMONITOR`'s actual
  presence in `ctypes.wintypes`) is called out explicitly rather than silently corrected or ignored.
- Inference/interpretation is confined to the "Proposed DDC module interface" and "Open questions"
  sections (and the small number of explicitly labeled inference notes above, e.g. in §7-§9); the
  rest of the document reports only what the sources say.
