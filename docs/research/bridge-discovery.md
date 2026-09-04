# Bridge Discovery — Research Notes

Scope: how the Hub should find the Bridge (the Windows-PC helper service) when the Bridge's IP address
changes often — it joins/leaves a Tailscale tailnet and may switch between Wi-Fi and Ethernet, which also
changes its MAC — and the owner rejects DHCP reservations. Candidate design under test: the Bridge
periodically announces its current IP/port to the Hub's LAN listener on port 39501; the Driver's `parse()`
receives the announcement and updates the address it calls; a missed announcement marks the MoonHalo
offline.

All docs2.hubitat.com facts below come from a live browser render (docs2 is a JS SPA; a plain fetch only
returns the page `<title>`). Anything not found in the sources consulted is labeled as such rather than
guessed.

## One-paragraph answer

The candidate design is sound and matches how several real Hubitat LAN drivers solve exactly this problem,
but two details need to change from the sketch in the question. First, the Driver's device network ID
(DNI) must be the Bridge's **MAC address** (upper-case hex, no separators), not its IP — Hubitat's port
39501 router matches incoming traffic to a device by DNI-equals-sender-IP-hex **or** DNI-equals-sender-MAC-hex
(both are documented, order unspecified), and every real-world push-style driver surveyed below (Konnected,
Kasa/Tapo) keys its DNI off the MAC precisely because the IP is the thing that changes. Second, because the
Bridge's own network adapter can also change (Wi-Fi ↔ Ethernet swap changes the MAC Hubitat would route
on), the DNI itself is not fully stable either — the Driver has to be able to notice its DNI no longer
matches what the Bridge is announcing and update the DNI at runtime (`setDeviceNetworkId()`, documented to
exist but with no documented uniqueness/format constraints). The IP the Driver calls with `asynchttpGet`
should be a plain field the Driver updates on every announcement — carried inside the announcement body
itself, not just inferred from `parseLanMessage()`'s IP, so it survives NAT/proxy edge cases and is
explicit about port. A heartbeat every 1–2 minutes with a missed-heartbeat timeout of about 3× that
interval, plus keeping the existing HTTP-poll `refresh()` path as a fallback confirmation, gives a design
that degrades gracefully on first install (before any announcement has arrived) by falling back to the
configured `bridgeIp` preference. This is a recommended design synthesized from the sources below; the
individual routing/API facts are documented, the synthesis is not.

## 1. Port 39501 routing — documented facts

Source: [Building a LAN or Cloud Driver](https://docs2.hubitat.com/en/developer/driver/building-a-lan-driver)
(rendered page text, section "Port 39501").

Verbatim:

> "Incoming traffic to port 39501 on the hub will be routed to a device with a DNI matching the IP address
> or MAC address of the source device (converted to hex, all uppercase, no separators). This is one way to
> handle unsolicited incoming traffic from LAN devices that can be configured to send data to a specific IP
> address and port... This incoming traffic will be sent to the parse() method in the driver. The data
> (passed in as the first and only parameter) can then be further processed (e.g., with parseLanMessage())
> or otherwise dealt with as necessary."

What this confirms and what it does not:

- **DNI match target**: "IP address or MAC address of the source device (converted to hex, all uppercase,
  no separators)". Both forms are explicitly documented as valid DNIs for routing. **The order of
  precedence when a device exists under one form and not the other, or under both, is not documented in
  the sources consulted.**
- **What `parse()` receives**: "The data (passed in as the first and only parameter)" — i.e. `parse(String
  description)`, a single positional String argument, consistent with the existing Driver's
  `void parse(String description)` stub.
- **`parseLanMessage()`**: named only as the tool to further process that data. Its full signature is given
  elsewhere as `Map parseLanMessage(String stringToParse)` (source:
  [Common Methods](https://docs2.hubitat.com/en/developer/common-methods-object), listed only in the page's
  "Additional to be documented" bare-signature list). **The Map's actual keys (`headers`, `body`, `mac`,
  `ip`, etc.) are not documented in the prose of any page fetched in this research pass.** The Konnected app
  (GitHub source, see section 5) uses `parseLanMessage(evt.description)` and then reads `.mac`, so `mac` is
  confirmed as a real key by that independent (non-Hubitat-authored) usage, but this is inferred from a
  third-party driver, not from Hubitat's own docs.
- **Whether the hub answers the sender**: **not documented anywhere found.** Port 39501 is described purely
  as an inbound listener that dispatches to `parse()`; no page describes the hub sending any acknowledgement
  or response back to the device that pushed data to port 39501.
- **The port number itself and that it is fixed**: confirmed independently on the
  [Hub Object](https://docs2.hubitat.com/en/developer/hub-object) page — `localSrvPortTCP` is documented as
  "String: The local tcp port of the hub (**always returns 39501**)". This is a second primary source
  confirming 39501 as a hub-side constant, not a Driver-configurable value.

## 2. Changing a device's own DNI at runtime

Source: [Device Object](https://docs2.hubitat.com/en/developer/device-object) (rendered page text).

`getDeviceNetworkId()` / `setDeviceNetworkId(String dni)` both appear, but **only** in the page's
"Additional to be documented" bare-signature list:

```
String getDeviceNetworkId()
void setDeviceNetworkId(String dni)
```

No prose on this page describes:
- Uniqueness constraints (whether two devices may share a DNI, or what happens if `setDeviceNetworkId` is
  called with a value already in use by another device),
- Format constraints beyond what's implied by the port-39501 section (hex, uppercase, no separators, for
  the IP/MAC-matching use case specifically),
- Whether a call from inside the driver's own `updated()`/`parse()` is safe, immediate, or queued.

**Conclusion: changing the DNI at runtime is a documented capability (the method exists) but its behavior
and constraints are not documented in the sources consulted.** The real-world drivers in section 5
(HubDuino, Konnected/Kasa-by-MAC) demonstrate it working in practice — HubDuino recomputes
`device.setDeviceNetworkId("${iphex}")` from a hex-encoded IP inside `updated()` whenever the IP preference
changes (see section 5) — but that is example-driven confirmation, not documentation.

Also relevant: `device.deviceNetworkId = ...` (bare property assignment, as opposed to the
`setDeviceNetworkId()` method call) is **not shown anywhere** on this page — only the method form is listed.
Prefer the documented method form.

## 3. `asynchttpGet` and hostnames/DNS

Source: [Common Methods](https://docs2.hubitat.com/en/developer/common-methods-object) and
[Building a LAN or Cloud Driver](https://docs2.hubitat.com/en/developer/driver/building-a-lan-driver).

The `uri` parameter of `asynchttpGet`'s `params` map is documented only as: "uri - The URI to send the
request to." No page fetched in this research pass says anything about:
- Whether a hostname (`mypc.lan`, `mypc.local`) is accepted in place of a literal IP,
- What DNS resolver the hub uses for outbound HTTP calls,
- Whether mDNS/`.local` names resolve at all.

**Conclusion: not documented in the sources consulted.** Nothing on the Common Methods or
Building-a-LAN-Driver pages restricts `uri` to a literal IP either — the absence of any DNS-related caveat
cuts both ways and should not be read as either a green light or a red light for hostname use. Given this
silence, the recommended design (section "Recommended design" below) does not rely on hostname resolution
at all; it treats the announced IP address as the only address the Driver ever calls with.

## 4. Alternatives Hubitat documents: SSDP/UPnP, mDNS, driver-only discovery, and OAuth endpoints

Source: [HubAction Object](https://docs2.hubitat.com/en/developer/hubaction-object) and
[Building a LAN or Cloud Driver](https://docs2.hubitat.com/en/developer/driver/building-a-lan-driver).

- **SSDP/UPnP discovery is documented**, via `hubitat.device.HubAction`, verbatim example from the
  HubAction Object page:
  ```groovy
  // Send a UPnP SSDP discovery message
  new HubAction("lan discovery urn:schemas-somecompany-com:device:deviceName:1", Protocol.LAN)
  ```
  The Building-a-LAN-Driver page states generically: "Drivers (and apps) can build a HubAction object and
  send the command this object builds" — so **a driver alone (no app) can issue an SSDP discovery
  HubAction.** What is **not documented** is how the driver receives the (potentially multiple, asynchronous)
  SSDP responses beyond the generic HubAction rule that a response goes to the `callback` option if given,
  "or... to the parse method of a Device." Real-world SSDP-based rediscovery (Konnected, section 5) is done
  from an **app**, subscribing to a location-wide event stream (`subscribe(location, "ssdpTerm.xxx",
  handler)`) that is not shown anywhere in the driver-facing docs fetched here — **whether a driver alone can
  receive the same location-wide SSDP broadcast stream (as opposed to just the reply to its own discovery
  HubAction) is not documented in the sources consulted.**
- **mDNS**: no page fetched in this research pass mentions mDNS, Bonjour, or `.local` resolution in any
  capacity. **Not documented.**
- **Driver-only discovery**: confirmed possible for outbound SSDP HubActions (above). For genuinely
  unsolicited inbound traffic (a device pushing to the hub unprompted), the only driver-only documented
  mechanism is port 39501 (section 1) — there is no documented driver-only equivalent of an app's
  `mappings{}` HTTP endpoint.
- **Inbound OAuth/HTTP endpoints require an app** (already known, reconfirmed here): "While not possible in
  a driver alone, apps can be configured to handle incoming HTTP traffic (GET, PUT, POST, or DELETE) by
  defining mappings in the app code" (Building a LAN or Cloud Driver page, verbatim).

## 5. How real LAN drivers with a changing device IP handle it

| Driver / project | Source | DNI = | Device announces itself? | How the driver learns/updates the IP |
|---|---|---|---|---|
| **Shelly** (ShellyUSA/Hubitat-Drivers, by Scott Grayban / Allterco) | [Shelly-as-a-Switch.groovy](https://github.com/ShellyUSA/Hubitat-Drivers/blob/master/Shelly-as-a-Switch.groovy), lines 320–350 (`obs.wifi_sta.ip` → `state.ip`), line 654 (`updateDataValue("ShellyIP", state.ip)`) | Not IP/MAC-based routing at all — `ip`/`port` are plain user preferences (`input("ip", "string", ...)`); no evidence in the fetched file of `setDeviceNetworkId` being called from the IP | No (poll-only; the driver GETs the Shelly's `/status`-style endpoint) | The driver's own poll reply carries `wifi_sta.ip`, which it stores to `state.ip`/`updateDataValue("ShellyIP", ...)` for **display only** — the address actually dialed next time is still the `ip` preference the user must edit by hand. |
| **HubDuino / ST_Anything** (DanielOgorchock/ST_Anything, by Dan Ogorchock) | [hubduino-parent-ethernet.groovy](https://github.com/DanielOgorchock/ST_Anything/blob/master/HubDuino/Drivers/hubduino-parent-ethernet.groovy), lines 199–204 (`getHostAddress()` reads `settings.ip`/`settings.port`), lines 262–264 (`def iphex = convertIPtoHex(ip); device.setDeviceNetworkId("${iphex}")` inside `updated()`) | **IP**, hex-encoded, recomputed in `updated()` every time the `ip` preference is saved | No — the Arduino/ESP device is polled/pushed to at a fixed IP the user configures | The changelog comment at line 46 says this driver deliberately moved from a MAC-based DNI to an IP-based one ("Eliminate the need for user to supply MAC address... Configure the Parent DNI to use Arduino IP Address instead") — i.e., it accepted that the DNI must be re-set by hand (via re-saving preferences) whenever the device's IP changes. This is the weakest of the four for an IP that changes on its own, since nothing pushes a new IP to the driver. |
| **Konnected** (konnected-io/konnected-hubitat, official) | [konnected-service-manager.groovy](https://github.com/konnected-io/konnected-hubitat/blob/master/apps/konnected-service-manager.groovy): `mappings{}` block lines 32–34 (device PUTs to `/device/:mac/:id/:deviceState`), `childDeviceStateUpdate()` lines 47–63 (DNI = `params.mac.toUpperCase() + "|" + pin`), SSDP rediscovery `discoverySearchHandler()` lines 292–305 (`event.networkAddress` updates `device.networkAddress` when the same `ssdpUSN` re-announces), `getDeviceIpAndPort()` line 283 | **MAC** (plus a pin suffix for the child device) — never the IP | **Yes, both ways**: (a) the physical device is configured (`updateSettingsOnDevice()`, line ~471, pushing `apiUrl: getFullLocalApiServerUrl()`) with the **app's own inbound URL**, so the Konnected device itself calls back into the hub's app endpoint on every state change; (b) the app also periodically re-runs SSDP discovery and, on seeing the same `ssdpUSN` (a stable per-device identifier independent of IP) reply again, overwrites `device.networkAddress` with the new IP. | This is the closest real-world analog to the candidate design in the research question: device-initiated push to a hub-side listener (an app `mappings{}` endpoint, since a driver alone cannot host one — see section 4), keyed by MAC, with IP kept only as a volatile, re-derived attribute. |
| **Kasa/Tapo** (DaveGut/tpLink_Hubitat, community, actively maintained) | [tpLink_parent.groovy](https://raw.githubusercontent.com/DaveGut/tpLink_Hubitat/main/Drivers/tpLink_parent.groovy): DNI-vs-MAC check lines 133–136 (`hubDni = device.getDeviceNetworkId(); if (respData.mac != hubDni) {...}`), `devIp` kept as a **data value**, not the DNI, line 112 (`getDataValue("devIp")`), UDP rediscovery `sendFindCmd(devIp, "20004"/"20002", ...)` calling into `LAN_TYPE_UDPCLIENT` HubAction plumbing (`tpLinkComms` library, `sendLanCmd`, lines ~709–719) | **MAC** | No unsolicited push observed in the fetched files; the parent driver's `configure()` re-runs a UDP "find" broadcast (`sendFindCmd`) to the last-known `devIp` and validates the reply's MAC against the DNI before accepting a new IP | Same pattern as Konnected: DNI is the durable identity (MAC), the IP is a separately-stored, disposable value that is re-validated against the DNI whenever it's refreshed, rather than trusted blindly. |

Overall pattern across the three drivers that actually cope with IP churn (Konnected, Kasa/Tapo, and — less
robustly — HubDuino): **the DNI is the MAC (or, for HubDuino, is a value the user must re-save), and the IP
is stored separately and re-validated against the MAC/identity whenever it changes.** Shelly is the
counter-example: it stores the IP for display but never uses it to re-target requests, so a Shelly whose IP
changes silently goes stale until a human edits the preference — this is the failure mode the research
question is trying to avoid.

## 6. Windows side: learning the Bridge's own current LAN IP

### The `socket` connect-trick (documented primitives, undocumented as a named recipe)

Source: [`docs.python.org` — `socket.socket.connect`](https://docs.python.org/3/library/socket.html) and
[`socket.socket.getsockname`](https://docs.python.org/3/library/socket.html).

- `connect(address)`: "Connect to a remote socket at *address*." (exact wording from the page).
- `getsockname()`: "Return the socket's own address. This is useful to find out the port number of an
  IPv4/v6 socket, for instance." (exact wording from the page).

**The Python docs do not document a "connect a UDP socket to a remote address, then call getsockname() to
learn the local IP" recipe as such** — this is a widely-used community idiom built entirely from two
individually-documented primitives (`socket.socket(...)`, `.connect(...)`, `.getsockname()`), not something
`docs.python.org` names or endorses as a technique in its own right. It works because `connect()` on a UDP
socket does not actually send any packet — it only makes the kernel pick a local source
address/route — but that mechanism is a general property of `connect()` on datagram sockets, not something
the `socket` page spells out for this exact purpose.

### `psutil.net_if_addrs()` (third-party library, not part of the Python standard library)

Source: [psutil documentation](https://psutil.io/), `net_if_addrs()`.

Returns a dict keyed by interface name (e.g. `psutil.net_if_addrs()['wlan0']`), each value a list of
address-family structures. This is documented to expose **per-adapter** address lists — i.e., it can tell
the Bridge apart Wi-Fi, Ethernet, and a Tailscale virtual adapter by interface name, which the
single-socket connect-trick cannot do (that trick returns whichever address the OS routing table picks for
the destination you connect to, with no visibility into the adapter name or whether it's the Tailscale
interface). `psutil` is a third-party package, not `docs.python.org`; it is documented on its own site,
not Python's standard-library docs. `ipconfig`-output parsing is an unstructured alternative to `psutil`
with no stable documented output contract at all — **not recommended and not "documented" in any formal
sense**, only mentioned in the research ticket as a candidate to rule out.

**Recommendation for the Bridge**: prefer `psutil.net_if_addrs()` (or the standard-library
`socket.if_nameindex()`/`ipaddress` combination if avoiding a third-party dependency is a priority) over
raw `ipconfig` parsing, specifically because the Bridge must distinguish "this PC's real LAN address" from
"this PC's Tailscale 100.x address" — a distinction the connect-trick cannot make reliably if a default
route happens to prefer the Tailscale interface, and `ipconfig` text output has no documented, versioned
schema.

### Detecting an address change

Source: [Microsoft Learn — `NotifyAddrChange`](https://learn.microsoft.com/en-us/windows/win32/api/iphlpapi/nf-iphlpapi-notifyaddrchange)
and [Microsoft Learn — `NotifyIpInterfaceChange`](https://learn.microsoft.com/en-us/windows/win32/api/netioapi/nf-netioapi-notifyipinterfacechange).

- `NotifyAddrChange` (`iphlpapi.h`, Win32): "causes a notification to be sent to the caller whenever a
  change occurs in the table that maps IPv4 addresses to interfaces." Can be called synchronously
  (blocks until a change) or asynchronously (via an `OVERLAPPED` handle). Its own Remarks section states:
  "On Windows Vista and later, the `NotifyIpInterfaceChange` function can be used to register to be
  notified for changes to IPv4 and IPv6 interfaces on the local computer" — i.e. Microsoft's own docs
  point callers on Vista+ (which covers any realistic target here) toward the newer API rather than
  `NotifyAddrChange`.
- `NotifyIpInterfaceChange` (`netioapi.h`, Win32): "registers to be notified for changes to all IP
  interfaces, IPv4 interfaces, or IPv6 interfaces on a local computer... defined on Windows Vista and
  later."

**Both are native Win32 APIs (C calling convention, `iphlpapi.dll`/`netioapi.dll`), not Python APIs.** A
Python bridge would need `ctypes`/`pywin32` bindings to call either directly — this plumbing is not
documented on `docs.python.org` (which has no wrapper for either function), so using them from Python is an
inferred integration, not a documented one. **Simpler and equally correct for this use case: skip OS-level
change notification entirely and just re-run the `psutil.net_if_addrs()` check on a timer** (the same timer
that drives the heartbeat announcement to the Hub) — the two-second cost of polling every heartbeat interval
is negligible against a MoonHalo control loop, and it avoids adding a native-API dependency for a benefit
(sub-second change detection) the design doesn't need.

## 7. Can the Hub's own IP be assumed stable, and how should the Bridge learn it?

Source: [Hub Object](https://docs2.hubitat.com/en/developer/hub-object) (rendered page text).

`location.hub.localIP` is documented: "String: The local ip address of the hub." This confirms the hub's
own IP is a knowable, documented value **from the driver/app side** (i.e., the Driver can always read its
own hub's current IP via `location.hub.localIP`, useful if the Driver ever needs to hand this value to
something). It says nothing about the Bridge (a separate Windows process) learning the Hub's IP —
that question is entirely outside Hubitat's documentation scope, since the Hub is not the thing whose
docs were consulted here.

**No page fetched in this research pass documents an SSDP announcement or a `/hub/details`-style HTTP
endpoint that the Hub exposes for third parties to discover its own IP.** (The research ticket already
assumes this is plausible from general Hubitat community knowledge, but it is not confirmed in the sources
actually consulted for this document, and no such page was found or fetched.) Whether it is stable is a
reasonable **inference**, not a documented fact: the CONTEXT.md glossary describes the Hub as "The Hubitat
Elevation hub," a wired appliance (Hubitat hubs ship as small dedicated boxes with an Ethernet port; the
common deployment is wired to the router) — but no primary source fetched in this research pass states this.

**Recommendation**: treat the Hub's IP as a plain configuration value on the Bridge (an environment
variable or config-file entry the owner sets once), exactly as `bridgeIp` is today a plain preference on
the Driver side. This is the cheapest, most symmetric choice and needs no new discovery machinery on the
Hub side; it also sidesteps the undocumented question of whether the Hub exposes any of its own
self-description over the LAN.

## Recommended design

**Bridge responsibilities** (inferred synthesis, not documented by any single source — built from the
patterns in section 5 plus the Windows-IP facts in section 6):

- The Bridge reads the Hub's IP and the UDP announcement port from its own config (a plain settings value,
  per section 7 — no discovery needed on this side).
- On startup, and every time `psutil.net_if_addrs()` (or equivalent) shows its LAN-facing address has
  changed, and otherwise on a fixed heartbeat timer, the Bridge sends a short UDP datagram to
  `<hub-ip>:39501` whose body carries at minimum: the Bridge's own current LAN IPv4 address, the HTTP port
  it's listening on (`5000` today), and a stable identifier for itself (a fixed string is enough, since
  there's only ever one Bridge — no need to invent a device-id scheme). Hubitat's own port-39501 routing
  (section 1) does the DNI matching from the *sender's* IP/MAC automatically — the Bridge doesn't need to
  know or set anything about DNIs; it just needs its packet to land on port 39501, from whatever IP it
  currently has.
- Sending UDP rather than HTTP for the announcement matters: `asynchttpGet`/`httpGet` are Driver-outbound
  calls that expect a specific target address; the announcement is exactly the case the port-39501 feature
  exists for — Hubitat's own docs frame it as "one way to handle unsolicited incoming traffic from LAN
  devices" (section 1, verbatim). HubAction's `LAN_TYPE_UDPCLIENT` (documented on the HubAction Object page)
  is the Driver-side mirror of this, though the Bridge only needs a plain UDP socket send, nothing
  Hubitat-specific.

**Driver responsibilities:**

- The DNI should be the Bridge's **MAC address** in the documented hex/uppercase/no-separators form, not
  its IP — this is the section-5 pattern (Konnected, Kasa/Tapo) that survives IP churn, and it is
  necessitated here specifically because the Bridge's IP is expected to change routinely (Tailscale
  join/leave) while its MAC on a given physical adapter does not.
- `parse(String description)` stops being a no-op: it calls `parseLanMessage(description)`, and if the
  announcement body it carries matches the expected format, the Driver updates a `state.bridgeIp` (and
  `state.bridgePort` if ever variable) value and timestamps `state.lastAnnounceAt`. `sendBridge()` is
  changed to prefer `state.bridgeIp` over the `bridgeIp` preference when a `state.bridgeIp` is present and
  recent — this is the "Driver treats the announcement as the address it calls" half of the candidate
  design, confirmed workable by the Konnected/Kasa pattern of storing the IP as a mutable value separate
  from the durable identity.
- **The adapter-switch problem** (Wi-Fi ↔ Ethernet changes the MAC, which is the DNI): since Hubitat's
  port-39501 router also accepts a DNI-equals-sender-**IP** match (section 1, both forms are documented as
  valid), a single announcement handler can serve double duty — but only if the DNI happens to already
  equal one of {current IP, current MAC}, and a MAC change silently breaks that unless the Driver notices.
  The pragmatic fix, given `setDeviceNetworkId()`'s behavior is undocumented (section 2) but shown to work
  from inside a driver in the wild (HubDuino): have the announcement body **also carry the Bridge's current
  MAC**, and have `parse()` compare it against `device.getDeviceNetworkId()`; on mismatch, call
  `device.setDeviceNetworkId(newMacHex)` so future port-39501 traffic from the (now different) adapter still
  routes to this device. This is inferred, not documented — no source fetched here confirms this
  specific runtime-DNI-migration pattern is safe, only that the method exists and that one real driver
  (HubDuino) calls it from inside a lifecycle method without apparent issue.
- **Heartbeat vs. poll interval**: keep the existing `pollMinutes` HTTP poll (`refresh()`, 1–30 minutes,
  default 5) as the confirmation/state-refresh path — it already asks the Bridge for full state and is how
  `applyState()` gets its data. Add a **separate, shorter heartbeat expectation**: the Bridge announces
  itself every 60–120 seconds (much shorter than the poll interval, since its only job is "I'm alive at this
  address," not carrying MoonHalo state), and the Driver runs its own `runIn`/`runEvery1Minute`-scheduled
  check that calls `markOffline()` (the method already in the Driver) if `state.lastAnnounceAt` is older
  than roughly **3× the heartbeat interval** (a standard heartbeat-timeout multiplier — not itself sourced
  from any Hubitat doc, just ordinary practice, chosen to tolerate one or two dropped UDP datagrams before
  declaring the Bridge offline, since UDP is not guaranteed to arrive).
- **First install, before any announcement has arrived**: `state.bridgeIp` is unset, so `sendBridge()` falls
  back to the existing `bridgeIp` text preference exactly as the Driver behaves today — the owner still
  types an initial IP once, on setup, which becomes moot the moment the first announcement lands and
  populates `state.bridgeIp`. This preserves the current Driver's `installed()`/`updated()` flow unchanged;
  the only new behavior is that `state.bridgeIp`, once populated, takes priority over the static
  `bridgeIp` preference in `sendBridge()`.

## What's documented vs. inferred — summary

**Documented** (cited above): port 39501's DNI-matching rule (IP-hex or MAC-hex, order unspecified);
`parse(String)` receiving the raw data; `parseLanMessage()`'s bare signature (not its return-Map contract);
`setDeviceNetworkId()`'s bare signature (not its runtime constraints); SSDP discovery via `HubAction("lan
discovery ...")`, usable from a driver alone; inbound HTTP mappings requiring an app; `asynchttpGet`'s `uri`
parameter with no documented DNS/hostname behavior; `location.hub.localIP` and `localSrvPortTCP` (fixed at
39501); Python's `socket.connect`/`getsockname` primitives; `psutil.net_if_addrs()`'s per-adapter shape;
`NotifyAddrChange`/`NotifyIpInterfaceChange`'s existence, parameters, and Microsoft's own steer toward the
newer API.

**Inferred** (not documented by any source fetched here, built from example-driver behavior or ordinary
engineering judgment): that a Driver may safely call `setDeviceNetworkId()` on itself at runtime in response
to a MAC change; the entire "announcement body also carries the MAC, Driver reconciles DNI" mechanism; the
3×-heartbeat-interval offline threshold; that the Hub's IP is stable because it is a wired appliance;
treating UDP-to-39501 as more appropriate than HTTP for the announcement.

## Open questions

1. **`parseLanMessage()`'s exact return-Map keys** (`headers`, `body`, `mac`, `ip`, `port`, etc.) — no
   primary Hubitat doc page fetched here spells this out in prose; only inferred from Konnected's use of
   `.mac`. A hub-side experiment (send a test UDP packet to port 39501 and log
   `parseLanMessage(description)` verbatim) would settle this before relying on any key beyond `mac`.
2. **`setDeviceNetworkId()`'s runtime constraints** — whether it can collide with another device's DNI,
   whether the change takes effect immediately for the *next* inbound packet, and whether calling it from
   inside `parse()` itself (as opposed to `updated()`, as HubDuino does) is safe.
3. **Precedence when both an IP-hex and a MAC-hex device exist** for the same source address — not stated
   anywhere found.
4. **Whether a driver alone (not an app) can subscribe to the hub-wide SSDP reply stream** the way
   Konnected's app does with `subscribe(location, "ssdpTerm.xxx", handler)`, or whether that pattern is
   an app-only capability — not confirmed either way in the sources consulted.
5. **Whether the hub sends any acknowledgement back to a device that pushes to port 39501** — not
   documented; the recommended design does not depend on an ack (UDP fire-and-forget, tolerated by the
   3×-heartbeat threshold), but confirming this would rule out any future temptation to build a
   handshake on top of it.
6. **Whether Hubitat exposes any documented mechanism for a LAN device to discover the Hub's own IP**
   (SSDP, `/hub/details`, or similar) — no such page was found in this research pass; the recommended
   design sidesteps this by making the Hub's IP a Bridge-side config value instead.
