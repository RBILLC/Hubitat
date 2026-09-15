# RD280UG VCP D6 (Power Mode): can the Bridge tell on from standby from unplugged?

Research for the 1.0.0 clean-up (issue #38), prompted by the 2026-09-15 observation that with the
RD280UG switched off at its front button every `SetVCPFeature` write to D7 and D9 returned success
and the Bridge's Ramp completed normally, but the halo did not light. Question: can the Bridge
distinguish a monitor in standby (button off, DDC/CI controller still answering) from one that is
on, and from one whose cable is unplugged, using VCP D6 or anything else documented?

**Status:** research complete, experiment not yet run.
**Date:** 2026-09-15
**Method:** documentation only. No DDC/CI call was made in this pass. The MCCS and DDC/CI spec
text was read from PDF copies (see Sources for which copy) after `pdftotext` extraction; the
ddcutil source was read from the project's GitHub master; Microsoft Learn pages were read live.
Nothing in this document was verified against the RD280UG itself; the experiment in §8 is what
does that.

---

## 1. What VESA MCCS 2.2a says about D6h

The RD280UG's capabilities string declares `mccs_ver(2.2)` (`docs/research/rd280ug-capabilities.md`
§3). The VESA MCCS PDF is not published free by VESA; the copy read here is the file at
https://milek7.pl/ddcbacklight/mccs.pdf, whose title page reads "VESA Monitor Control Command Set
Standard, Version 2.2a, 13 January 2011" and whose footer reads "VESA MCCS Standard, Reproduction
Prohibited, Version 2.2a". It is a copy of the spec, not a paraphrase.

Table 8-9 "Display Control VCP Codes", page 69 of 131, the D6h row, verbatim from the extracted
text (column layout flattened):

```
D6h  Power Mode  R/W  NC  Power Mode - DPM & DPMS standards are supported along with other
                          power function(s).
                          Byte: SL     DPM     DPMS
                          00h  Reserved, must be ignored
                          01h  On      On
                          02h  Off     Standby
                          03h  Off     Suspend
                          04h  Off     Off
                          Item(s) below are not part of the DPM or DPMS standards
                          05h  Power off the display - functionally equivalent to
                               turning off power using the "power button"
                          06h  Reserved, must be ignored
                          NOTE:
                          - Following a MCCS command with a value of 01h - 04h, the
                            display must respond to the appropriate DPM (or DPMS)
                            protocols.
                          - Following a MCCS command with a value of 05h, user
                            intervention at the display (pressing / toggling the power
                            switch) may be required to restore operation.
```

Documented facts from this:

- D6h is named **Power Mode**, type **NC** (non-continuous), access **R/W**. (The extracted text
  also carries a stray `RO` token on the `Byte: SL` line; its column placement is ambiguous after
  PDF extraction. The code's own access column says R/W, ddcutil's table derived from the same
  spec says `DDCA_RW` (§4), and DDC/CI 1.1 Appendix B speaks of both `GetVCP(0xD6)` and `SetVCP()`
  on it (§2), so R/W is taken as the reading.)
- The standard values are **01h On, 02h Standby, 03h Suspend, 04h Off** (DPMS names; DPM knows
  only On for 01h and Off for 02h-04h), plus **05h "power off, equivalent to the power button"**,
  which is outside DPM/DPMS and may need a hand on the button to undo.
- Section 4.3.2 (page 21): "The non-continuous controls accept only specific values. ...
  Non-continuous controls can be 'read and write', 'read-only' or 'write-only'."
- The spec does **not** say what a display should answer to a Get VCP Feature on D6 while it is in
  a low-power state, and does not say whether the DDC/CI controller must stay powered in states
  02h-05h. Searching the extracted text for "standby", "DPM" and "power" found only the table
  above, the glossary and the references list.

## 2. What VESA DDC/CI 1.1 says about power states and replies

Source: VESA "Display Data Channel Command Interface Standard, Version 1.1, October 29, 2004",
PDF at https://glenwing.github.io/docs/VESA-DDCCI-1.1.pdf (a copy of the VESA document, title page
and VESA footer intact).

- §6.7.1 Power Management (page 30): "If display power management can be controlled over DDC/CI,
  it shall be handled by using the MCCS VCP code. ... However, if the host supports both MCCS and
  DPM, both methods must be used by the OS to notify the display of any change in the requested
  power management level."
- §6.7.3 Capability String: "vcp() Mandatory. If MCCS power management is supported, the
  corresponding VCP code shall be reported." The RD280UG reports D6, so by this clause it claims
  MCCS power management.
- **Appendix B, "DPM (DPMS) and MCCS Power Management"** (page 39; the spec itself says "Appendixes
  are NOT part of the standard"): "In a display supporting both DPM and MCCS, the recommended rules
  are: A. The GetVCP(power management) always returns the current physical monitor power state. B.
  By default, the DPM solution is used. ..." and: "When the display uses the DPM mode by default,
  using 'GetVCP(0xD6)' will then report the Display Current power management level, regardless of
  the power management request's source. As such, if the monitor enters into a safety mode (X-Ray
  protect, for example), Power Off mode will automatically follow. If the host then sends
  GetVCP(0xD6), the display will naturally respond 00."
  This is the only VESA text found that says a D6 read reflects the monitor's *actual* power state
  rather than the last value written. It is a recommendation in a non-normative appendix.
- §6.4 NULL message (page 28): a display answers with a NULL message "To tell the host that the
  display does not have any answer to give to the host (not ready or not expected)". And §7 (page
  32): "If the DDC/CI slave address is not acknowledged after 'trial and error recovery' attempts,
  the host shall consider that the DDC/CI function is no longer available (detached)."
- Get VCP Feature reply (page 21): the reply carries a result code `RC`, "00h NoError, 01h
  Unsupported VCP Code". A Set VCP Feature has **no reply message** in the protocol; nothing in
  the standard reports whether the display acted on a set. This matters for §6.

## 3. What the RD280UG's own D6 value list means (50 60 90 A0)

The capabilities string advertises `D6 (50 60 90 A0)` (`docs/research/rd280ug-capabilities.md` §4).
None of those four values is in the MCCS table above (01h-05h). Search results for the literal
value list, for BenQ DDC/CI documentation and for a Display Pilot / Display Pilot 2 command
reference found **nothing public**: BenQ's Display Pilot pages describe the software and say only
that DDC/CI must be enabled in the OSD (System > Advanced > DDC/CI > ON), with no VCP reference
(https://www.benq.com/en-us/monitor/software/display-pilot-2/spec.html). For comparison, another
BenQ model's published capabilities string (BL2420PT, in a ddccontrol issue) lists the standard
`D6 (01 04)` (https://github.com/ddccontrol/ddccontrol/issues/8), so BenQ does use the standard
values elsewhere; the RD280UG's list is model- or generation-specific.

**Not documented anywhere consulted:** what 50h, 60h, 90h and A0h mean on the RD280UG, whether
they are the values the monitor *reports* on a read or only the values it *accepts* on a write, or
whether a read in standby returns one of them. ddcutil's author notes generally that "for some VCP
codes [a monitor] may implement values not defined in the spec" and that the capabilities string
is "a hint, not a guarantee" (§4). **Inference:** the four values look like a 4-bit field in the
high nibble (0101, 0110, 1001, 1010) rather than the spec's 1-5 sequence, which is consistent with
BenQ re-encoding D6 the way it re-purposed D7 (`docs/research/rd280ug-capabilities.md` §6); this is
speculation and only a read in each state (§8) can attach meanings to them.

## 4. What ddcutil documents about D6 and monitors in standby

ddcutil is the reference open-source DDC/CI implementation on Linux; its feature table quotes the
MCCS values and its issue tracker holds first-hand reports from its author.

- Feature table, `src/vcp/vcp_feature_codes.c`
  (https://raw.githubusercontent.com/rockowitz/ddcutil/master/src/vcp/vcp_feature_codes.c): 0xD6
  "Display power mode", flags `DDCA_RW | DDCA_SIMPLE_NC`, values
  `{0x01, "DPM: On, DPMS: Off"}, {0x02, "DPM: Off, DPMS: Standby"}, {0x03, "DPM: Off, DPMS:
  Suspend"}, {0x04, "DPM: Off, DPMS: Off"}, {0x05, "Write only value to turn off display"}`.
  0xD7 is "Auxiliary power output", `{0x01, "Disable auxiliary power"}, {0x02, "Enable Auxiliary
  power"}` (the code BenQ reuses for MoonHalo).
- Issue #482 (Samsung S24C31x on a Raspberry Pi, 2024-12-27), the author's reply of 2025-01-02
  (https://github.com/rockowitz/ddcutil/issues/482): "after running `ddcutil setvcp d6 4`, the
  display is turned off. However, depending on the display, the EDID may or may not be readable
  when the display is turned off. ... `ddcutil detect` finds the display, but marks it invalid ...
  since DDC communication fails." And: "you've found if you put the display into standby
  (`ddcutil setvcp d6 2`) as opposed to turning it off (`ddcutil setvcp d6 4`), it remains
  responsive to ddcutil commands. Again, whether a display responds to DDC commands when it is in
  standby mode depends on the display implementation." And on writes: "That DDC reports success
  for the setvcp operation only means that the display has successfully received the request
  packet." The reporter also found that ddcutil's post-write verification read woke the display:
  "`ddcutil setvcp D6 02` without the --noverify option, caused a brief turn off of the display,
  which suddenly re-turned on, each time."
- Issue #36 (Dell U2715H touch monitor, 2017-10-20/21)
  (https://github.com/rockowitz/ddcutil/issues/36): the reporter switched the monitor off with
  `setvcp D6 x05`, and while "off" could still change its input source over DDC/CI and turn it
  back on with `setvcp D6 x01`; `getvcp D6` afterwards read `0x01`. The author: "Consider the
  output of capabilities to a hint, not a guarantee. ... a given monitor need not implement all
  possible values, and for some VCP codes may implement values not defined in the spec." He
  attributed the verification failure after wake to "it takes a while after 'ddcutil setvcp d6
  x01' for the monitor to properly initialize."
- ddcutil does not trust a DDC read to discover that a monitor is asleep; it asks the OS. From
  the CHANGELOG (https://raw.githubusercontent.com/rockowitz/ddcutil/master/CHANGELOG.md): 2.0.0
  (2023-09-25): "If using X11, terminate immediately if a DPMS sleep mode is active." 2.1.0
  (2024-01-16): hotplug detection "Can detect physical connection/disconnection and DPMS sleep
  status changes, but the effect of turning a monitor on or off is monitor dependant and cannot
  reliably be detected", with new status codes `DDCRC_DISCONNECTED` ("display has been
  disconnected") and `DDCRC_DPMS_ASLEEP` ("display is in a DPMS sleep mode",
  `src/public/ddcutil_status_codes.h`). `src/ddc/ddc_displays.c` sets
  `DREF_DPMS_SUSPEND_STANDBY_OFF` from `dpms_check_drm_asleep(businfo)`, i.e. from the kernel's
  DRM connector state, not from D6. The release notes for 2.0.0 add: "Warn that output may be
  inaccurate if the monitor appears to be in a sleep mode" (https://www.ddcutil.com/release_notes/).

Taken together, ddcutil's documented position is: whether a monitor answers DDC/CI in standby, and
what it answers, is **monitor-specific**; a successful write proves only that the packet was
received; the effect of the power button "cannot reliably be detected"; and the project's own
sleep detection uses the host graphics stack, not D6.

## 5. What Microsoft Learn documents for the Monitor Configuration API

All pages carry the same warning: "Many monitors don't fully implement that standard; so your use
of these commands might result in undefined monitor behavior."

- `SetVCPFeature`: "This function corresponds to the 'Set VCP Feature' command from the [DDC/CI]
  standard. This function takes about 50 milliseconds to return." Return value is TRUE/FALSE with
  `GetLastError`. **Nothing** about the monitor's power state, and nothing that says success means
  the monitor applied the value (consistent with §2: the DDC/CI Set has no reply).
  (https://learn.microsoft.com/en-us/windows/win32/api/lowlevelmonitorconfigurationapi/nf-lowlevelmonitorconfigurationapi-setvcpfeature)
- `GetVCPFeatureAndVCPFeatureReply`: "Vendor-specific VCP codes can be used with this function.
  This function takes about 40 milliseconds to return." `pdwMaximumValue`: "If bVCPCode specifies
  a non-continuous VCP code, the value received in this parameter is undefined." Nothing about
  power state.
  (https://learn.microsoft.com/en-us/windows/win32/api/lowlevelmonitorconfigurationapi/nf-lowlevelmonitorconfigurationapi-getvcpfeatureandvcpfeaturereply)
- `GetPhysicalMonitorsFromHMONITOR`: returns "a handle and a text description for each physical
  monitor" for an HMONITOR from `EnumDisplayMonitors`. Nothing about monitors that are off,
  asleep or disconnected.
  (https://learn.microsoft.com/en-us/windows/win32/api/physicalmonitorenumerationapi/nf-physicalmonitorenumerationapi-getphysicalmonitorsfromhmonitor)
- The high-level API has **no power-state query**. `GetMonitorCapabilities` lists every
  `MC_CAPS_*` flag (brightness, contrast, colour temperature, degauss, display area, technology
  type, RGB drive/gain, factory defaults); none concerns power. `GetMonitorTechnologyType` returns
  an `MC_DISPLAY_TECHNOLOGY_TYPE` (CRT, LCD, ...) and nothing else.
  (https://learn.microsoft.com/en-us/windows/win32/api/highlevelmonitorconfigurationapi/nf-highlevelmonitorconfigurationapi-getmonitorcapabilities ,
  https://learn.microsoft.com/en-us/windows/win32/api/highlevelmonitorconfigurationapi/nf-highlevelmonitorconfigurationapi-getmonitortechnologytype)
- The Win32 error codes the API can raise, from "COM Error Codes (COMADMIN, FILTER, GRAPHICS)"
  (https://learn.microsoft.com/en-us/windows/win32/com/com-error-codes-5), verbatim:
  - `0xC0262580 ERROR_GRAPHICS_I2C_NOT_SUPPORTED` "The monitor connected to the specified video
    output does not have an I2C bus."
  - `0xC0262581 ERROR_GRAPHICS_I2C_DEVICE_DOES_NOT_EXIST` "No device on the I2C bus has the
    specified address."
  - `0xC0262582 ERROR_GRAPHICS_I2C_ERROR_TRANSMITTING_DATA` "An error occurred while transmitting
    data to the device on the I2C bus." (the 2026-09-14 failure, -1071241854 signed)
  - `0xC0262583 ERROR_GRAPHICS_I2C_ERROR_RECEIVING_DATA` "An error occurred while receiving data
    from the device on the I2C bus."
  - `0xC0262584 ERROR_GRAPHICS_DDCCI_VCP_NOT_SUPPORTED` "The monitor does not support the
    specified VCP code."
  - `0xC0262585 ERROR_GRAPHICS_DDCCI_INVALID_DATA` "The data received from the monitor is
    invalid."
  - `0xC026258B ERROR_GRAPHICS_DDCCI_INVALID_MESSAGE_CHECKSUM` "... the checksum field in a DDC/CI
    message did not match ... This error implies that the data was corrupted while it was being
    transmitted from a monitor to a computer." (the transient seen in issue #28, -1071241845)
  - `0xC026258D ERROR_GRAPHICS_MONITOR_NO_LONGER_EXISTS` "The operating system asynchronously
    destroyed the monitor which corresponds to this handle because the operating system's state
    changed. This error typically occurs because the monitor PDO associated with this handle was
    removed, the monitor PDO associated with this handle was stopped, or a display mode change
    occurred."
  `0xC026258D` is the documented error for a monitor that went away between obtaining the handle
  and using it; the Bridge re-enumerates on every call (`_select_physical_monitor` in
  `Bridges/BenQ_MoonHalo/moonhalo_bridge/ddc.py`), so an unplugged monitor is more likely to
  surface as the primary HMONITOR vanishing or its physical-monitor array being empty
  ("Selected monitor has no physical monitor handle") than as `0xC026258D`; which one is not
  documented and is part of §8.
- Windows *does* publish the OS's own view of display power, as power-setting notifications, not
  as a monitor query: `GUID_CONSOLE_DISPLAY_STATE` "The current monitor's display state has
  changed" with `PowerMonitorOff (0)`, `PowerMonitorOn (1)`, `PowerMonitorDim (2)`, and the older
  `GUID_MONITOR_POWER_ON` "The primary system monitor has been powered on or off"
  (https://learn.microsoft.com/en-us/windows/win32/power/power-setting-guids). These report what
  Windows asked the display to do (its DPM output), which is exactly what ddcutil reads from DRM
  on Linux. Nothing on that page says the notification fires when a user presses the monitor's own
  power button, and there is no reason in the DPM model to expect it to: DPM is a host-to-display
  signal. **Inference:** these GUIDs tell the Bridge when *Windows* has blanked the display (screen
  timeout), not when the *user* has switched the monitor off at the button; the two cases need
  different sources.

## 6. Answering the three cases from the documents

| Case | What the documents support | Confidence |
|---|---|---|
| Cable unplugged / no I2C | DDC/CI 1.1 §7: slave not acknowledged -> "detached". Windows: enumeration changes or a `0xC02625xx` error; the Bridge's `MonitorLink` already reports this as `failed`. | Documented, exact symptom on this PC not yet observed |
| Standby at the button, controller answering | D6 read is the only documented query. DDC/CI 1.1 Appendix B (non-normative): a D6 read "always returns the current physical monitor power state". ddcutil (#482): whether a monitor answers at all in standby is "display implementation" dependent; the 2026-09-15 observation shows the RD280UG *does* answer writes. A `SetVCPFeature` success "only means that the display has successfully received the request packet" (#482), matching the observation that the halo did not light. | Documented in principle; the RD280UG's D6 values are undocumented (§3) |
| On | D6 reads the "on" value, whatever the RD280UG's encoding of it is. | Needs the experiment |

There is **no** documented way to learn from a `SetVCPFeature` success whether the monitor acted
on the write (MCCS/DDC-CI define no reply to a Set; Microsoft documents none). Read-back of D7 was
already found unreliable on this model (Didact's `noVerify` flag on D7,
`docs/research/ddcci-windows-api.md` §1), so the state must come from a separate D6 read, not from
verifying D7.

## 7. Cost and safety of reading D6 (question 5)

- A D6 read is one `GetVCPFeatureAndVCPFeatureReply`, which Microsoft documents at "about 40
  milliseconds" (§5). The Bridge's `read_vcp` already wraps every read in
  `_read_with_retries` (3 attempts, 50 ms apart, `Bridges/BenQ_MoonHalo/moonhalo_bridge/ddc.py`),
  so a failing D6 read costs at most about 220 ms before it raises `DdcError`.
- The read is the same call the Bridge already makes on D9 before a Ramp; nothing is written.
  MCCS defines D6 as R/W, and Microsoft says "Vendor-specific VCP codes can be used with this
  function", so a read is within both specs.
- **One documented risk to plan around:** in ddcutil #482 the *read* that followed a standby
  write woke the Samsung display ("this implicit getvcp operation wakes up the display"). That was a
  display put to sleep *by D6 write*, and the author's explanation was that any subsequent getvcp
  would do it. Whether a D6 read wakes an RD280UG that was switched off at its button is
  undocumented and is a specific check in §8. **Inference:** a monitor whose power button is a
  soft switch (controller stays up, as the 2026-09-15 writes show) is the kind that *could* wake
  on I2C traffic, so the experiment should watch for the panel lighting during the read.
- Never write 05h (or any of BenQ's four values) as part of a status check: MCCS says 05h "may
  require user intervention at the display ... to restore operation", and ddcutil #482 shows 04h
  can drop DDC/CI entirely on some monitors.

## 8. Proposed Bridge mapping (inference) and the experiment that must confirm it

**Inference, not yet backed by a measurement on the RD280UG:**

1. Before a Ramp (or on the existing health/read path), read D6 once through `read_vcp(0xD6)`.
2. Map: D6 current == the value observed with the monitor on -> `on`; D6 current == a value
   observed with the monitor off at its button -> `standby`; `DdcError` (retries exhausted, no
   monitors enumerated, empty physical-monitor array, or any `0xC02625xx`) -> `failed`, which is
   what `MonitorLink` already records.
3. In `standby`, either skip the Ramp and report "monitor in standby, halo not lit" to the Driver,
   or run it and mark the result unverified; which is a product decision for #38, not a research
   finding.
4. Do not infer `standby` from a write that succeeded; per §2/§5 a write success carries no such
   information.

The mapping stands or falls on what the RD280UG actually returns, which no source records. The
experiment, read-only except for the one D7 write in step 4:

```
py -m moonhalo_bridge read D6      # monitor on
py -m moonhalo_bridge read D6      # monitor switched off at its front button (wait ~10 s first)
py -m moonhalo_bridge read D6      # monitor's HDMI cable unplugged (and again with DP if used)
```

Record for each: the `current` and `maximum` values (or the `DdcError` text and Win32 code), how
long the call took, and whether the panel or halo changed state during the read (the wake-on-read
risk from §7). Then, with the monitor off at its button:

```
py -m moonhalo_bridge write D7 <on value>   # does the halo light while the panel is in standby?
py -m moonhalo_bridge read D6               # did the write change what D6 reports?
```

The 2026-09-15 evidence already says the D7 write returns success and the halo stays dark; the
experiment should re-confirm that and add the D6 readings around it. Expected outcomes that would
confirm the mapping: two distinct D6 values for on and off-at-button, drawn from `50 60 90 A0` or
the standard `01`-`04`, and a `DdcError` (not a value) when unplugged. Outcomes that would refute
it: the same D6 value in both states (D6 reports the last *written* value, not the physical
state, contrary to DDC/CI 1.1 Appendix B), or the read waking the panel.

## 9. Measured on the RD280UG, 2026-09-15 (Bridge 0.0.7, HDMI on the NVIDIA RTX 4070 SUPER)

`py -m moonhalo_bridge read D6` from the Bridge folder, the serving Bridge idle:

| Monitor | Result |
|---|---|
| On | `VCP 0xD6: current=96 (0x0060) maximum=144 (0x0090)` |
| Off at its front button, after ~10 s | `VCP 0xD6: current=96 (0x0060) maximum=144 (0x0090)` |
| HDMI cable unplugged | Not measurable this way: the RD280UG is the PC's only display, so there is nothing to type on. To be measured through the Hub instead: unplug, send On from the device page, replug, read `bridge.log` for `outcome=ok` or `outcome=error:<text>`. |

**Outcome: the refuting one from §8.** D6 reads the same value, `0x60`, whether the panel is on
or switched off at its button, so on this monitor a D6 read cannot tell the two apart. Read
together with the 2026-09-15 evidence that D7/D9 writes succeed and a Ramp completes while the
panel is dark, DDC/CI on the RD280UG gives no signal for the button state at all: neither writes
nor the power-mode register change. Whether `0x60` is "on" in BenQ's encoding or a value that
never changes is unknown; either way it is not usable.

Still to measure: the cable-unplugged case through the Hub (expected `failed` with one of the
§5 error codes, or an enumeration failure), and `write D7 544` with the panel off at its button,
to learn whether the halo lights in that state or the write is accepted and ignored.

Consequence for the Bridge (inference): a `standby` value for the Monitor link cannot be built
from D6 on this monitor. The choices left are to accept that the button state is invisible, or
to look for it outside DDC/CI (the Windows console display state GUIDs in §5 cover OS-driven
blanking, not the button, per the docs). The 2026-09-14 stuck-link failure and an unplugged
cable both surface as `failed`, which the existing Monitor link already reports.

## Open questions

- The meanings of `50 60 90 A0` on the RD280UG, and whether they are read values, write values or
  both. No BenQ document found; only the experiment can assign them.
- Whether a D6 read wakes the panel from button-standby (§7).
- Which exact failure the Bridge sees when the cable is unplugged on this PC: an empty
  enumeration, a missing primary, an empty physical-monitor array, `0xC0262581`, `0xC0262582`,
  or `0xC026258D`. The Bridge's re-enumeration per call makes the enumeration path likelier, but
  nothing documents it.
- Whether Windows' `GUID_CONSOLE_DISPLAY_STATE` notification fires on a button press (the docs
  describe only the OS-driven state); if it does not, the OS notification can cover screen-timeout
  blanking while D6 covers the button, and the Bridge might want both.
- Whether the "stuck I2C" failure of 2026-09-14 (`0xC0262582` on every call until a real restart)
  is distinguishable from an unplugged cable by anything other than the error code; the documents
  give the same family of codes for both.

## Sources

- VESA, "Monitor Control Command Set Standard, Version 2.2a, 13 January 2011", Table 8-9 (page 69)
  and §4.3.2 (page 21); copy read: https://milek7.pl/ddcbacklight/mccs.pdf (VESA sells the
  original; VESA's own 2009 release note for MCCS 2.2 is
  https://www.vesa.org/wp-content/uploads/2010/12/PR42009MCCS.pdf).
- VESA, "Display Data Channel Command Interface Standard, Version 1.1, October 29, 2004", §6.4,
  §6.7.1, §6.7.3, §7 and Appendix B; copy read: https://glenwing.github.io/docs/VESA-DDCCI-1.1.pdf
- Elo Touch Solutions application note "Elo Device Management, Remote Management: Elo Displays"
  (doc 20061AEB00033), which reproduces the MCCS D6h table verbatim and adds Elo's own reading
  ("01: Power on; 02: Sleep mode; 04: Power off; 05: BL off"), used only to cross-check the MCCS
  table text: https://docs.elotouch.com/ELO_APP_Notes_20061AEB00033.pdf
- ddcutil feature table: https://raw.githubusercontent.com/rockowitz/ddcutil/master/src/vcp/vcp_feature_codes.c
- ddcutil status codes: https://raw.githubusercontent.com/rockowitz/ddcutil/master/src/public/ddcutil_status_codes.h
- ddcutil display detection (DPMS handling): https://raw.githubusercontent.com/rockowitz/ddcutil/master/src/ddc/ddc_displays.c
- ddcutil CHANGELOG (2.0.0, 2.1.0 entries): https://raw.githubusercontent.com/rockowitz/ddcutil/master/CHANGELOG.md
- ddcutil release notes: https://www.ddcutil.com/release_notes/
- ddcutil issue #36 "Changing Power Mode?" (2017): https://github.com/rockowitz/ddcutil/issues/36
- ddcutil issue #482 "RPI: Cannot control anymore HDMI display after action on feature D6" (2024-25):
  https://github.com/rockowitz/ddcutil/issues/482
- ddccontrol issue #8, BenQ BL2420PT capabilities (`D6 (01 04)`): https://github.com/ddccontrol/ddccontrol/issues/8
- BenQ Display Pilot 2 specifications (no VCP reference published):
  https://www.benq.com/en-us/monitor/software/display-pilot-2/spec.html
- Microsoft Learn, `SetVCPFeature`:
  https://learn.microsoft.com/en-us/windows/win32/api/lowlevelmonitorconfigurationapi/nf-lowlevelmonitorconfigurationapi-setvcpfeature
- Microsoft Learn, `GetVCPFeatureAndVCPFeatureReply`:
  https://learn.microsoft.com/en-us/windows/win32/api/lowlevelmonitorconfigurationapi/nf-lowlevelmonitorconfigurationapi-getvcpfeatureandvcpfeaturereply
- Microsoft Learn, `GetPhysicalMonitorsFromHMONITOR`:
  https://learn.microsoft.com/en-us/windows/win32/api/physicalmonitorenumerationapi/nf-physicalmonitorenumerationapi-getphysicalmonitorsfromhmonitor
- Microsoft Learn, `GetMonitorCapabilities`:
  https://learn.microsoft.com/en-us/windows/win32/api/highlevelmonitorconfigurationapi/nf-highlevelmonitorconfigurationapi-getmonitorcapabilities
- Microsoft Learn, `GetMonitorTechnologyType`:
  https://learn.microsoft.com/en-us/windows/win32/api/highlevelmonitorconfigurationapi/nf-highlevelmonitorconfigurationapi-getmonitortechnologytype
- Microsoft Learn, "COM Error Codes (COMADMIN, FILTER, GRAPHICS)" (the `ERROR_GRAPHICS_I2C_*`,
  `ERROR_GRAPHICS_DDCCI_*` and `ERROR_GRAPHICS_MONITOR_NO_LONGER_EXISTS` entries):
  https://learn.microsoft.com/en-us/windows/win32/com/com-error-codes-5
- Microsoft Learn, "Power Setting GUIDs" (`GUID_CONSOLE_DISPLAY_STATE`, `GUID_MONITOR_POWER_ON`):
  https://learn.microsoft.com/en-us/windows/win32/power/power-setting-guids
- Hubitat community forum: two searches (DDC/CI, standby, monitor power state; BenQ, MoonHalo,
  ControlMyMonitor) found no thread on DDC/CI or monitor power detection. This question is on the
  PC/monitor side, so the forum's silence is expected, not a gap.
- This repo: `docs/research/rd280ug-capabilities.md` (the D6 value list and mccs_ver),
  `docs/research/ddcci-windows-api.md` (API signatures, timing, Didact's `noVerify` on D7),
  `Bridges/BenQ_MoonHalo/moonhalo_bridge/ddc.py` (retry policy, per-call enumeration) and
  `model.py` (`MonitorLink`).

## What is documented fact vs inference

Documented: the MCCS D6 definition and values (§1); DDC/CI 1.1's power-management clauses, NULL
message and "detached" rule, and Appendix B's (non-normative) "GetVCP returns the physical power
state" (§2); the RD280UG's `D6 (50 60 90 A0)` list and the absence of any public BenQ meaning for
it (§3); ddcutil's table, its author's statements that standby behaviour is monitor-specific, that
a write success means only "packet received", and that its own sleep detection comes from the OS
(§4); every Microsoft statement and error code quoted in §5; the 40 ms read cost and the Bridge's
retry policy (§7).

Inference: the R/W reading of the stray `RO` token (§1); the high-nibble guess about BenQ's values
(§3); that the Windows power GUIDs do not fire on a button press (§5); that a soft-button monitor
could wake on a read (§7); the whole Bridge mapping and the expected experiment outcomes (§8).
