# RD280UG DDC/CI capabilities string: which VCP codes it advertises

Research for [issue #28](https://github.com/RBILLC/Hubitat/issues/28) (part of #1, blocks #27).
Question: what does the BenQ RD280UG's own DDC/CI capabilities string say it supports — in
particular, is there any VCP code beyond D7/D9 that could plausibly be a MoonHalo fade/transition
register, and what value ranges does it advertise for D7 and D9?

**Date:** 2026-09-07
**Method:** read-only. `GetCapabilitiesStringLength` then `CapabilitiesRequestAndCapabilitiesReply`
from `dxva2.dll` via `ctypes`, called from a throwaway script (`get_capabilities.py`, written to the
session scratchpad, not committed to the repo) run with `py` on the Windows PC the RD280UG is
attached to as the primary monitor. Two read-only `GetVCPFeatureAndVCPFeatureReply` calls (D7, D9)
were added to cross-check current/max against the capabilities string. **`SetVCPFeature` was never
declared or called** — nothing was written to the monitor.

---

## 1. Raw capabilities string (verbatim)

```
(prot(monitor)type(LCD)model(RD280UG)cmds(01 02 03 07 0C E3 F3)vcp(02 04 08 10 12 13 (00 01) 14 (04 05 08 0B) 16 18 19 1A 52 60 (0F 11 13) 62 68 (00 02 04 06 08 0A 0C 0E) 69 (00 01) 6A (00 01) 6F (00 01) 71 (00 01) 72 (50 64 78 8C A0) 7D (00 01 02 07 08) 7E(0F 11 13) 7F (01) 80 (00 01 02) 80 (00 01 02 03) 81 (00 01 02) 86 (02 05) 87 8A 8D (01 02) 94 (01 02 03) AA (01 02 03) C1 C2 C9 CA(01 02 05 06 09 0A 11 12 21 22) CC(01 02 03 04 05 06 07 09 0A 0B 0D 0E 0F 10 12 14 17 1A 1E 1F 24 ) D0(01 02 03 04 05 06 07 08 09 0A) D1(00 01 02) D2 D6 (50 60 90 A0) D7 D9 DC (0A 0F 12 1F 23 30 31 32 3A) DF E1 E3 (00 01) E4 (02 03 04) E5 E6 (00 01) E7 (00 01 0A 14 1E 3C 50 A0) E8 (01 02) E9 (01 02 03) EB (00 01 02 03) EE (00 01 02) EF (00 01) F0 (00 01 02) F1 (00 1E 20 3C) F3 (00 01) F4 (00 01) F6 (00 01) F8 (00 0A 14 1E) FD (00 03 04) mswhql(1)asset_eep(40)mccs_ver(2.2))
```

Length reported by `GetCapabilitiesStringLength`: 866 characters (including the NUL terminator).

Reported physical-monitor description string (from `GetPhysicalMonitorsFromHMONITOR`): `Generic PnP
Monitor` — this is a generic Windows/GDI label, not the DDC/CI `model()` field; the model comes from
the capabilities string itself (see §3).

**Transient failure observed, as documented.** The first `GetCapabilitiesStringLength` call failed
with `GetLastError()` = `-1071241845` (`0xC026258B` as an unsigned 32-bit value); the second attempt,
50 ms later, succeeded. This matches Microsoft's own documented caveat for both capabilities
functions: "This function usually returns quickly, but sometimes it can take several seconds to
complete." (`GetCapabilitiesStringLength`,
https://learn.microsoft.com/en-us/windows/win32/api/lowlevelmonitorconfigurationapi/nf-lowlevelmonitorconfigurationapi-getcapabilitiesstringlength
; identical wording on
`CapabilitiesRequestAndCapabilitiesReply`,
https://learn.microsoft.com/en-us/windows/win32/api/lowlevelmonitorconfigurationapi/nf-lowlevelmonitorconfigurationapi-capabilitiesrequestandcapabilitiesreply),
and `docs/research/ddcci-windows-api.md` §9, which quotes the same lines. The retry-with-pause
strategy specified in the task (up to 3 attempts, 50 ms apart) recovered on attempt 2; no failure
persisted to 3 attempts in this run.

---

## 2. Grammar used to parse it

Primary sources for the capabilities-string grammar:

- **Microsoft Learn**, "Using the Low-Level Monitor Configuration Functions": "The capabilities
  string is an ASCII string that contains static information about the monitor. One part of the
  string lists the VCP codes that the monitor supports. The string also lists the supported values
  of the noncontinuous VCP codes." And: "For a continuous VCP code, call
  `GetVCPFeatureAndVCPFeatureReply` to get the current and maximum values of the code. For a
  noncontinuous VCP code, parse the capabilities string to get the supported values."
  (https://learn.microsoft.com/en-us/windows/win32/monitor/using-the-low-level-monitor-configuration-functions)
- **ddcutil source**, `src/vcp/parse_capabilities.c` (the reference open-source parser for this exact
  string format): the string is "a parenthesized expression containing a sequence of `segments`",
  each segment being "a segment name, followed by a parenthesized value" — e.g. `prot(...)`,
  `type(...)`, `model(...)`, `cmds(...)`, `vcp(...)`, `mccs_ver(...)`. Inside the `vcp()` segment
  specifically: "A VCP [entry] contains either the feature code in hex, or the feature code followed
  by a parenthesized list of values (in hex)." Feature codes are read as **two hex characters**; the
  parser also tolerates feature codes not separated by blanks ("If len > 2, feature codes not
  separated by blanks. Take just the first 2 characters"), citing "the Access Bus spec, Section 7"
  for the permitted spacing variability.
  (https://github.com/rockowitz/ddcutil/blob/master/src/vcp/parse_capabilities.c)
- **ddcutil docs**, VCP feature types: "Continuous (C): Able to take any value up to some maximum;
  Non-continuous (NC): Able to take only a designated set of values; Table (T): Used for 'raw' data
  such as a video LUT." (https://www.ddcutil.com/mccs_background/) — this is the type system the
  parenthesized value lists exist to serve: a bare code with no parenthesized list is either
  Continuous (its range comes from `GetVCPFeatureAndVCPFeatureReply`'s reported maximum, not the
  capabilities string) or an NC/Table code the monitor's firmware simply didn't enumerate.
- **ddcutil source**, `src/vcp/vcp_feature_codes.c`: codes `0xE0`-`0xFF` are treated as the
  "manufacturer specific feature" range generically (`0xe0 <= feature_id && feature_id <= 0xff`);
  a code below `0xE0` with no table entry is reported as "unrecognized feature" — i.e. ddcutil
  distinguishes "MCCS-numbered but not assigned a public meaning ddcutil knows" from "in the
  vendor-private block by definition." (https://raw.githubusercontent.com/rockowitz/ddcutil/master/src/vcp/vcp_feature_codes.c)

Applying that grammar: the string's top level is `prot`, `type`, `model`, `cmds`, `vcp`, `mswhql`,
`asset_eep`, `mccs_ver` segments (the last three appended without a leading space, which the ddcutil
parser's "not separated by blanks" tolerance above explicitly accounts for). Inside `vcp(...)`, each
token is a 2-hex-digit code, optionally followed by a `(space-separated hex list)` of the legal
values for that code (a Non-Continuous feature) — the whitespace between a code and its `(` is
inconsistent in this exact string (e.g. `"7E(0F 11 13)"` has none, `"7F (01)"` has one), which the
ddcutil source above documents as expected, not an error.

## 3. Parsed fields

| Field | Value |
|---|---|
| `prot` | `monitor` |
| `type` | `LCD` |
| `model` | `RD280UG` |
| `mccs_ver` | `2.2` |
| `mswhql` | `1` |
| `asset_eep` | `40` |
| `cmds` (DDC/CI command codes, not VCP codes) | `01 02 03 07 0C E3 F3` |

## 4. Parsed VCP code list

Every code in the `vcp(...)` block, in the order the monitor listed them, with any advertised value
list:

```
02
04
08
10
12
13  (00 01)
14  (04 05 08 0B)
16
18
19
1A
52
60  (0F 11 13)
62
68  (00 02 04 06 08 0A 0C 0E)
69  (00 01)
6A  (00 01)
6F  (00 01)
71  (00 01)
72  (50 64 78 8C A0)
7D  (00 01 02 07 08)
7E  (0F 11 13)
7F  (01)
80  (00 01 02)        <- appears a second time below with a different list; see note
80  (00 01 02 03)
81  (00 01 02)
86  (02 05)
87
8A
8D  (01 02)
94  (01 02 03)
AA  (01 02 03)
C1
C2
C9
CA  (01 02 05 06 09 0A 11 12 21 22)
CC  (01 02 03 04 05 06 07 09 0A 0B 0D 0E 0F 10 12 14 17 1A 1E 1F 24)
D0  (01 02 03 04 05 06 07 08 09 0A)
D1  (00 01 02)
D2
D6  (50 60 90 A0)
D7
D9
DC  (0A 0F 12 1F 23 30 31 32 3A)
DF
E1
E3  (00 01)
E4  (02 03 04)
E5
E6  (00 01)
E7  (00 01 0A 14 1E 3C 50 A0)
E8  (01 02)
E9  (01 02 03)
EB  (00 01 02 03)
EE  (00 01 02)
EF  (00 01)
F0  (00 01 02)
F1  (00 1E 20 3C)
F3  (00 01)
F4  (00 01)
F6  (00 01)
F8  (00 0A 14 1E)
FD  (00 03 04)
```

61 lines above, 60 distinct codes (`80` is listed twice with two different value lists — verbatim in
the raw string, not a parsing artifact of this script; **inference**: most likely a firmware
authoring quirk in the monitor's own capabilities string, since neither the Microsoft Learn nor
ddcutil grammar sources describe a case where the same code is legitimately allowed to appear twice
with different lists).

## 5. D7 and D9: what the string says, and what the monitor reports live

**Neither D7 nor D9 has a parenthesized value list in this capabilities string** — both are listed as
bare codes, like the other codes with no value list in this string
(`02 04 08 10 12 16 18 19 1A 52 62 87 8A C1 C2 C9 D2 DF E1 E5`). Per the Microsoft Learn grammar
quoted in §2 ("for a
noncontinuous VCP code, parse the capabilities string to get the supported values"), a bare code with
no list is not something the monitor's own capabilities string tells a DDC/CI host how to interpret —
the host would fall back to treating it as continuous and asking `GetVCPFeatureAndVCPFeatureReply`
for the live maximum. Cross-checking that live call, read-only, immediately after parsing the string:

| Code | Current (hex) | Current (dec) | Max (hex) | Max (dec) |
|---|---|---|---|---|
| D7 | `0x0220` | 544 | `0x0231` | 561 |
| D9 | `0x030A` | 778 | `0x070A` | 1802 |

**Inference, not documented fact**, cross-referencing `docs/research/ddcci-windows-api.md` §3 (the
Didact-derived facts about this exact model's D7/D9 packing): D7's live current value `0x0220`
decodes under Didact's shipped `valueMask` scheme as low byte `0x20` (= "On", matching the shipped
BenQ profile's `d7` options: `0x10`=Off, `0x20`=On, `0x30`=Auto) and high byte `0x02` (= "360°" light
mode, matching `0x0200`=360° in the same profile) — i.e. the monitor was On/360° at the moment of this
read. D9's current `0x030A` decodes under the shipped `byte: high/low` scheme as low byte `0x0A` (=
10, the documented max of the Brightness range 1-10) and high byte `0x03` (= 3, within the documented
Color Temperature range 1-7). Both decoded values are plausible/in-range for the shipped profile,
which is consistent with (does not on its own prove) that scheme still being correct for this unit's
firmware.

The `max` values `GetVCPFeatureAndVCPFeatureReply` reports for D7/D9 (`0x0231`, `0x070A`) are **not
meaningful maxima in the MCCS continuous-feature sense** — per the Microsoft Learn quote in §2, a
`maximum` from this call is documented as the ceiling for a *continuous* code's single 16-bit value,
but D7/D9 are packed two-sub-value registers (per Didact's `valueMask`/`byte` scheme documented in
`docs/research/ddcci-windows-api.md` §3), so the "maximum" the monitor reports is an artifact of
whatever the firmware last had cached as a ceiling for the combined 16-bit register, not a documented
per-sub-value range. This is **inference**: no source consulted (Microsoft Learn, ddcutil, or the
capabilities string itself) says what a monitor should report as `maximum` for a packed/vendor NC
register it doesn't declare with a value list.

## 6. Is there any code beyond D7/D9 that plausibly relates to a MoonHalo fade/transition?

**No code's name or value list in this string names or numerically suggests "fade," "transition," or
a timing/ramp parameter.** Cross-checked against ddcutil's own generic VCP feature-name table
(`src/vcp/vcp_feature_codes.c`, fetched in full): a full-text search of that file for `fade`,
`transition`, `ramp`, `Moon Halo`, and `BenQ` returned **no matches at all** — ddcutil's feature-name
database, built from the public MCCS assignments across spec revisions, has no code anywhere
associated with fade/transition/animation timing, for this or any vendor.

What that same ddcutil table does say about the codes adjacent to D7/D9 in this string, by name
(these are ddcutil's generic/public MCCS names, not RD280UG-specific — cited to show what a *generic*
DDC/CI client would assume, which is exactly why BenQ's private reuse of D7 is notable):

- `0xD6` → "Power Mode" (DPM/DPMS-style display power states) — a real, publicly-assigned MCCS code,
  unrelated to MoonHalo.
- `0xD7` → ddcutil's generic table names this **"Auxiliary Power Output"**, not MoonHalo. This
  confirms BenQ has repurposed a code that already had a different public MCCS meaning for its own
  MoonHalo power/mode feature — consistent with `docs/research/ddcci-windows-api.md` §3's finding
  that the shipped BenQ profile packs MoonHalo power (low byte) and light-mode angle (high byte) into
  D7 via a `valueMask`.
- `0xD9` → **no entry at all** in ddcutil's table; ddcutil would report it as "unrecognized feature,"
  not "manufacturer specific" (that label is reserved for `0xE0`-`0xFF` only). D9 sits in the
  MCCS-numbered-but-publicly-unassigned space, which is exactly where a vendor is free to put a
  private feature like MoonHalo Brightness/Color-Temperature without colliding with any documented
  meaning.
- `0xDC` → "Display Application" (picture-mode presets like Productivity/Movie/Games/Sports, per
  ddcutil) — unrelated to MoonHalo, and its advertised value list here (`0A 0F 12 1F 23 30 31 32 3A`)
  is a set of discrete preset IDs, not a duration/ramp parameter.
- `0xDF` → "Version" (VCP version query, paired with `0xC9`) — unrelated.
- Every code in the `0xE1`-`0xFD` range present in this string falls inside ddcutil's generic
  `0xE0`-`0xFF` "manufacturer specific feature" band — i.e. these are all vendor-private by
  definition, so nothing in any public source (MCCS assignments as reflected in ddcutil, or Microsoft
  Learn) says what any of them do. **Inference**: any of E1/E3/E4/E5/E6/E7/E8/E9/EB/EE/EF/F0/F1/
  F3/F4/F6/F8/FD *could* in principle be something BenQ uses for a MoonHalo-adjacent purpose (a fade
  duration, a transition curve, etc.) — nothing rules that out — but nothing in the capabilities
  string, its value lists, or any source consulted here **names or suggests** such a purpose for any
  of them, and none is grouped adjacent to D7/D9 in a way that would hint at a relationship. `E7`'s
  value list (`00 01 0A 14 1E 3C 50 A0`) is numerically the most "duration-shaped" of the bunch (its
  values read like they could be seconds or a scaled duration: 0, 1, 10, 20, 30, 60, 80, 160 in
  decimal) but this is **pure speculation, not a finding** — no source ties `0xE7` to timing, to
  MoonHalo, or to BenQ at all, and it is flagged here only because the task asked specifically whether
  anything "plausibly" fits, not because there is evidence it does.
- **Conclusion for #27's transition design**: this capabilities string gives **no evidence of a
  monitor-native fade/transition VCP register** for MoonHalo. It neither confirms nor rules out that
  one of the manufacturer-specific codes above secretly does this — that would require either BenQ's
  own documentation (not found in this pass) or empirically writing test values to each candidate
  code and observing the monitor, which is out of scope for this read-only research task. Absent such
  evidence, the transition design on #27 should keep assuming a fade can only be a Bridge-driven
  stepped ramp over D9/D7, exactly as #28's question framed the risk.

## 7. Sources

- Microsoft Learn, "Using the Low-Level Monitor Configuration Functions":
  https://learn.microsoft.com/en-us/windows/win32/monitor/using-the-low-level-monitor-configuration-functions
- Microsoft Learn, `GetCapabilitiesStringLength`:
  https://learn.microsoft.com/en-us/windows/win32/api/lowlevelmonitorconfigurationapi/nf-lowlevelmonitorconfigurationapi-getcapabilitiesstringlength
- Microsoft Learn, `CapabilitiesRequestAndCapabilitiesReply`:
  https://learn.microsoft.com/en-us/windows/win32/api/lowlevelmonitorconfigurationapi/nf-lowlevelmonitorconfigurationapi-capabilitiesrequestandcapabilitiesreply
- Microsoft Learn, `GetVCPFeatureAndVCPFeatureReply`:
  https://learn.microsoft.com/en-us/windows/win32/api/lowlevelmonitorconfigurationapi/nf-lowlevelmonitorconfigurationapi-getvcpfeatureandvcpfeaturereply
- ddcutil source, capabilities-string parser: `src/vcp/parse_capabilities.c`
  https://github.com/rockowitz/ddcutil/blob/master/src/vcp/parse_capabilities.c
- ddcutil source, generic VCP feature-name table: `src/vcp/vcp_feature_codes.c`
  https://raw.githubusercontent.com/rockowitz/ddcutil/master/src/vcp/vcp_feature_codes.c
- ddcutil docs, "Monitor Control Command Set" (feature type definitions — Continuous/Non-Continuous/
  Table): https://www.ddcutil.com/mccs_background/
- ddcutil docs, `capabilities` command: https://www.ddcutil.com/command_capabilities/
- This repo, prior research: `docs/research/ddcci-windows-api.md` (Win32 API signatures used here,
  §6/§9 timing/retry guidance, and §3's Didact-derived facts about the RD280UG's D7/D9 packing scheme,
  used only for the cross-check in §5/§6 above, not re-verified independently in this pass).

## 8. What is inference vs. documented fact

Documented facts (backed by a source quoted above): the raw string in §1; the grammar in §2; the
field/code parsing in §3/§4; the live D7/D9 current/max values in §5's table; ddcutil's generic names
for D6/D7/D9/DC/DF and the E0-FF manufacturer-specific boundary in §6.

Everything else — the D7/D9 byte decoding narrative in §5 (borrowed from a *different* research
pass's Didact findings, not re-derived from this string alone), the "no evidence of a fade/transition
code" conclusion in §6, and especially the E7-duration speculation in §6 — is explicitly labeled
inference above and should be read as such.

## 9. Script

The script used (`get_capabilities.py`) was written to the session scratchpad, not committed to this
repo, per the task's instructions. It declares only `GetCapabilitiesStringLength`,
`CapabilitiesRequestAndCapabilitiesReply`, `GetVCPFeatureAndVCPFeatureReply`, and the enumeration/
teardown calls (`EnumDisplayMonitors`, `GetMonitorInfoW`, `GetNumberOfPhysicalMonitorsFromHMONITOR`,
`GetPhysicalMonitorsFromHMONITOR`, `DestroyPhysicalMonitors`) — `SetVCPFeature` is never declared or
called anywhere in it.
