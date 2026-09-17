# Windows monitor identity without DDC/CI: can the Bridge know it is the RD280UG when I2C is dead?

Research for issue #44 (2026-09-16). On the evening of 2026-09-16, after a cable replug, the
RD280UG on `\\.\DISPLAY1` was enumerated by Windows but every DDC/CI call to it failed with Win32
error -1071241854 = `0xC0262582` (`ERROR_GRAPHICS_I2C_ERROR_TRANSMITTING_DATA`), so the Bridge's
detection (`_detect` in `Bridges/BenQ_MoonHalo/moonhalo_bridge/ddc.py`, which reads each monitor's
capabilities string and matches `model(RD280UG)`) reported it `unreadable` and chose nothing
("State B" in #44). Earlier the same evening (21:08 and 22:04) the RD280UG was missing from
`EnumDisplayMonitors` entirely ("State A"). Four questions: (1) does Windows keep a monitor's EDID
identity available without a live DDC/CI transaction; (2) how does that identity map onto the
`\\.\DISPLAYn` name and the physical-monitor handle the Bridge writes through; (3) what do the
Monitor Configuration API documents say about `0xC0262582` and hot-plug; (4) what removes a monitor
from `EnumDisplayMonitors` and which Windows messages announce it.

**Status:** research complete; live observation done with both monitors attached and healthy.
**Date:** 2026-09-16, observation at 22:31 local (UTC-4), Bridge 0.0.9 serving and idle.
**Method:** Microsoft Learn pages read live (URLs in Sources); the repo's own code, `bridge.log` and
issue #44 for observed behaviour; read-only queries on this PC (WMI, PnP properties, registry, a
ctypes script under the scratchpad calling `EnumDisplayDevices` and `QueryDisplayConfig`, the
Bridge's `monitors` command, and the event logs). No VCP register was written, no monitor setting
changed, and the MoonHaloBridge scheduled task was not touched. The Hubitat community forum was
searched twice (DDC/CI, EDID, WmiMonitorID) and has nothing on the subject; this is a PC-side
question, so that silence is expected. Every claim below is either quoted from a document with its
URL, marked as observed on this PC, or labelled inference.

---

## 1. EDID identity without a live DDC/CI transaction (question 1)

Four Windows surfaces carry the monitor's EDID identity. What each one documents about *where the
data comes from* varies, and none of the Monitor Configuration API is involved in any of them.

### 1.1 `WmiMonitorID` (WMI, `root\wmi`)

Microsoft Learn, "WmiMonitorID class"
(https://learn.microsoft.com/en-us/windows/win32/wmicoreprov/wmimonitorid):

> "The **WmiMonitorID** WMI class represents the identifying information about a video monitor,
> such as manufacturer name, year of manufacture, or serial number. The data in this class
> correspond to data in the Vendor/Product Identification block of Video Input Definition of the
> Video Electronics Standard Association (VESA) Enhanced Extended Display Identification Data
> (E-EDID) standard."

Properties (all read-only): `Active` "Indicates the active monitor."; `InstanceName` (Key) "Name of
the specific monitor instance."; `ManufacturerName` (uint16 array) "Name of manufacturer.";
`ProductCodeID` "Vendor assigned product code ID."; `SerialNumberID` "Serial number.";
`UserFriendlyName` "The friendly name of the monitor."; `WeekOfManufacture`; `YearOfManufacture`.
Requirements: "Namespace Root\wmi", "MOF WmiCore.mof", "DLL WmiProv.dll". The class derives from
`MSMonitorClass`, "an abstract WMI base class. The classes that describe video display monitors
inherit from this MSMonitorClass" (https://learn.microsoft.com/en-us/windows/win32/wmicoreprov/msmonitorclass),
whose siblings include `WmiMonitorRawEEdidV1Block` and `WmiMonitorDescriptorMethods` with the
method `WmiGetMonitorRawEEdidV1Block(BlockId) -> BlockType, BlockContent[128]`
(https://learn.microsoft.com/en-us/windows/win32/wmicoreprov/wmigetmonitorraweedidv1block-wmimonitordescriptormethods).

Who answers these WMI queries is documented on the driver side. "Monitor Class Function Driver"
(https://learn.microsoft.com/en-us/windows-hardware/drivers/display/monitor-class-function-driver):

> "User-mode applications use WMI to invoke the services of the monitor class function driver.
> Those services include exposing a monitor's identification data."

> "The FDO processes a request from a user-mode application to read a monitor's EDID in that
> monitor's device stack. When the FDO receives a request to retrieve the monitor's EDID: The FDO
> sends a request to the PDO at the bottom of the monitor's device stack. The PDO uses the Display
> Data Channel (DDC) protocol to read the monitor's EDID over the I²C bus, which is a simple
> two-wire bus built into all standard monitor cables."

And the miniport-side entry point, `DxgkDdiQueryDeviceDescriptor`
(https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/dispmprt/nc-dispmprt-dxgkddi_query_device_descriptor):

> "For a child device that has a connected monitor, the display port driver calls
> *DxgkDdiQueryDeviceDescriptor* during initialization to obtain the first 128-byte block of a
> monitor's EDID. Later the monitor class function driver (Monitor.sys) calls
> *DxgkDdiQueryDeviceDescriptor* to obtain selected portions (including the first 128-byte block)
> of that same monitor's EDID."

So the documented path for a WMI EDID request is user mode -> WMI -> Monitor.sys (FDO) -> the
display miniport's PDO -> DDC over I2C. **What is not documented** is whether the miniport (here
NVIDIA's) answers `DxgkDdiQueryDeviceDescriptor` from a copy it took at hot-plug or by a fresh I2C
read each time, nor whether `WmiMonitorID` (parsed fields) is served from the same call as
`WmiGetMonitorRawEEdidV1Block` (raw block). Two further points, both **inference**: EDID over DDC
is a different I2C slave from DDC/CI (the DDI page below says the DDC/CI transmit function "is
required to transmit data to an I2C device that has address 0x6E"; the EDID EEPROM address is not
named on any Microsoft page read, and the E-DDC standard was not consulted in this pass), so an
I2C failure on 0x6E need not imply one on the EDID address; and the monitor's devnode existing at
all means the port driver *had* read its EDID at enumeration, since the devnode's hardware ID
`MONITOR\BNQ80BB` is built from it (see 1.3).

### 1.2 `EnumDisplayDevices` with `EDD_GET_DEVICE_INTERFACE_NAME`

Microsoft Learn, "EnumDisplayDevicesW"
(https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-enumdisplaydevicesw):

> "*lpDevice*: A pointer to the device name. If **NULL**, function returns information for the
> display adapter(s) on the machine, based on *iDevNum*."

> "*dwFlags*: Set this flag to EDD_GET_DEVICE_INTERFACE_NAME (0x00000001) to retrieve the device
> interface name for GUID_DEVINTERFACE_MONITOR, which is registered by the operating system on a
> per monitor basis. The value is placed in the DeviceID member of the DISPLAY_DEVICE structure
> returned in *lpDisplayDevice*. The resulting device interface name can be used with SetupAPI
> functions and serves as a link between GDI monitor devices and SetupAPI monitor devices."

> "To obtain information on a display monitor, first call **EnumDisplayDevices** with *lpDevice*
> set to **NULL**. Then call **EnumDisplayDevices** with *lpDevice* set to
> DISPLAY_DEVICE.**DeviceName** from the first call to **EnumDisplayDevices** and with *iDevNum*
> set to zero. Then **DISPLAY_DEVICE**.**DeviceString** is the monitor name."

The `DISPLAY_DEVICE` structure page
(https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ns-wingdi-display_devicew) is thinner:
`DeviceString` is "either a description of the display adapter or of the display monitor",
`DeviceID` is "Not used." and `DeviceKey` is "Reserved." (the `EnumDisplayDevices` page above
overrides the first of those for the flag case). Its `StateFlags` entry for `DISPLAY_DEVICE_ACTIVE`
reads: "specifies whether a monitor is presented as being 'on' by the respective GDI view.
**Windows Vista:** EnumDisplayDevices will only enumerate monitors that can be presented as being
'on.'" What the *un-flagged* `DeviceID` contains (`MONITOR\BNQ80BB\{class GUID}\0002` on this PC,
section 5.4) is not documented on either page; it is observed.

`GUID_DEVINTERFACE_MONITOR` itself
(https://learn.microsoft.com/en-us/windows-hardware/drivers/install/guid-devinterface-monitor):
"Class GUID {E6F07B5F-EE97-4a90-B076-33F57BF4EAA7}" and "Windows registers a device interface for
each monitor that is configured in the operating system."

### 1.3 The registry under `HKLM\SYSTEM\CurrentControlSet\Enum\DISPLAY`

The monitor's PnP identity is built from the EDID at enumeration. "Enumerating Child Devices of a
Display Adapter"
(https://learn.microsoft.com/en-us/windows-hardware/drivers/display/enumerating-child-devices-of-a-display-adapter):

> "During initialization, the display port driver calls *DxgkDdiQueryDeviceDescriptor* for each
> monitor to obtain the first 128-byte block of the monitor's EDID. That gives the display port
> driver what it needs at initialization time: PnP hardware ID, instance ID, compatible IDs, and
> device text."

The hardware ID's form is documented in the monitor INF sections: "the expression
**Monitor\MON12AB** combines the device class (Monitor) and the device identification (MON12AB) as
it appears in the device's *EDID*"
(https://learn.microsoft.com/en-us/previous-versions/windows/drivers/display/monitor-inf-file-sections),
and a device instance ID "is a system-supplied device identification string that uniquely identifies
a device in the system ... A device instance ID is persistent across system restarts"
(https://learn.microsoft.com/en-us/windows-hardware/drivers/install/device-instance-ids).

That the EDID bytes themselves sit in the registry is documented only indirectly, through the
override mechanism ("Using an INF File to Override EDIDs",
https://learn.microsoft.com/en-us/windows-hardware/drivers/display/overriding-monitor-edids):

> "Device installation reads the updated EDID information from the INF file and stores the
> information as values under the hardware key of the monitor device. ... The monitor driver checks
> the registry during initialization and uses any EDID information stored there instead of the
> corresponding information on EEPROM. EDID information that is added to the registry always takes
> precedence over EEPROM EDID info."

> "The monitor driver obtains the updated data for the corrected blocks from the registry and uses
> the EEPROM data for the remaining blocks."

No Microsoft page read documents the `Device Parameters\EDID` value that this PC (and every Windows
PC) carries under each `Enum\DISPLAY\<PnP ID>\<instance>` key. Two archived MSDN forum threads speak
to it, one with a Microsoft-badged answer: in "how to read edid data direct from monitor (not
registry)" (https://learn.microsoft.com/en-us/archive/msdn-technet-forums/1a19a278-c296-4d34-ade7-83bf3315db96)
the accepted answer (poster "d", signed with the standard Microsoft "AS IS" disclaimer) says "the
method to read EDID is private to the display/monitor driver. it does not expose a public API for
you to get at the EDID directly ... you need to use
SetupDiGetClassDevices(GUID_DEVINTERFACE_MONITOR)/SetupDiEnumDeviceInterfaces/SetupDiOpenDevRegKey
to get an HKEY to this path", and a 2017 reply adds "in Win10 1709 only the first part (128 bytes)
is cached in the registry, even if the monitor has more ... Cached data can be deleted by removing
the monitor device in Device Manager. Next time when the monitor is plugged in, the cache will be
created again." The 128-byte claim is contradicted on this PC, where the RD280UG's registry EDID
is 384 bytes (section 5.3). Treat the thread as a forum source: the registry value is a cache
written at PnP enumeration, refreshed when the device is re-enumerated, and readable with no I2C
traffic at all; the last point is the one that matters here and is consistent with everything
observed.

### 1.4 `QueryDisplayConfig` + `DisplayConfigGetDeviceInfo(DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME)`

`DISPLAYCONFIG_TARGET_DEVICE_NAME`
(https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ns-wingdi-displayconfig_target_device_name):

> "`edidManufactureId`: The manufacture identifier from the monitor extended display
> identification data (EDID). This member is set only when the **edidIdsValid** bit-field is set in
> the **flags** member."

> "`edidProductCodeId`: The product code from the monitor EDID. This member is set only when the
> **edidIdsValid** bit-field is set in the **flags** member."

> "`monitorFriendlyDeviceName[64]`: A NULL-terminated WCHAR string that is the device name for the
> monitor. This name can be used with *SetupAPI.dll* to obtain the device name that is contained in
> the installation package."

> "`monitorDevicePath[128]`: A NULL-terminated WCHAR string that is the path to the device name for
> the monitor. This path can be used with *SetupAPI.dll* to obtain the device name that is contained
> in the installation package."

> "If an application calls the DisplayConfigGetDeviceInfo function to obtain the monitor name and
> **DisplayConfigGetDeviceInfo** either cannot get the monitor name or the target is forced without
> a monitor connected, the string in the **monitorFriendlyDeviceName** member ... is a **NULL**
> string and none of the bit-field flags in the DISPLAYCONFIG_TARGET_DEVICE_NAME_FLAGS structure
> are set."

The flags (https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ns-wingdi-displayconfig_target_device_name_flags):
`friendlyNameFromEdid` (0x1) "indicates that the string in the **monitorFriendlyDeviceName** member
... was constructed from the manufacture identification string in the extended display
identification data (EDID)"; `friendlyNameForced` (0x2) "indicates that the target is forced with
no detectable monitor attached"; `edidIdsValid` (0x4) "indicates that the **edidManufactureId** and
**edidProductCodeId** members ... are valid and were obtained from the EDID."

`DisplayConfigGetDeviceInfo` returns `ERROR_ACCESS_DENIED` when "The caller does not have access to
the console session. This error occurs if the calling process does not have access to the current
desktop or is running on a remote session"
(https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-displayconfiggetdeviceinfo);
`QueryDisplayConfig` has the same clause
(https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-querydisplayconfig). Nothing
on these pages says whether the EDID fields are served from a cache or from the wire; they are
"obtained from the EDID" and that is all.

**Answer to question 1.** Yes. The manufacturer ID, product code, serial and friendly name are
exposed by `WmiMonitorID`, by the PnP device ID that `EnumDisplayDevices` returns, by the registry
EDID cache, and by `DisplayConfigGetDeviceInfo`. The registry is documented as stored data. The
other three are documented as EDID-derived without any statement about caching; the documented
kernel path for a WMI EDID read does end at the miniport's EDID descriptor call, which a miniport may
serve from the wire. None of the four goes anywhere near the DDC/CI (0x6E) path the Bridge uses.

## 2. Mapping the identity onto `\\.\DISPLAYn` and the physical-monitor handle (question 2)

The Bridge's chain is `EnumDisplayMonitors` -> `GetMonitorInfoW` (`szDevice`) ->
`GetPhysicalMonitorsFromHMONITOR` -> `hPhysicalMonitor` (`WindowsDdcPort.list_monitors` and
`_open_physical_monitor` in `ddc.py`). Each link that joins the GDI view to a PnP identity:

| Link | Status | Source |
|---|---|---|
| `HMONITOR` -> `\\.\DISPLAYn` | **Documented.** `MONITORINFOEX.szDevice` is "A string that specifies the device name of the monitor being used." | https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-monitorinfoexw |
| `\\.\DISPLAYn` is the adapter name that `EnumDisplayDevices(NULL, i)` returns, and `EnumDisplayDevices(that name, 0)` returns its monitor | **Documented** (the two-call recipe in 1.2). That the string in `szDevice` and the adapter `DeviceName` are the same namespace is observed (section 5.4), not stated. | https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-enumdisplaydevicesw |
| Monitor `DeviceID` with `EDD_GET_DEVICE_INTERFACE_NAME` = the `GUID_DEVINTERFACE_MONITOR` interface name, "a link between GDI monitor devices and SetupAPI monitor devices" | **Documented** (1.2). | same |
| That interface name -> the PnP device instance ID (`DISPLAY\BNQ80BB\5&3a1fce67&0&UID4352`) | **Observed**: the interface path is `\\?\` + the instance ID with `\` replaced by `#` + `#{E6F07B5F-...}` (5.4). No page read documents the composition; the documented way to walk it is SetupAPI/CfgMgr on the interface name. | section 5.4 |
| PnP instance ID -> `WmiMonitorID.InstanceName` | **Observed**: `InstanceName` is the instance ID plus `_0` (5.1). The `_0` suffix is not documented on the class page. | section 5.1 |
| `QueryDisplayConfig` path: `sourceInfo.id` -> `viewGdiDeviceName` | **Documented.** `DISPLAYCONFIG_SOURCE_DEVICE_NAME.viewGdiDeviceName` is "the GDI device name for the source, or view". | https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ns-wingdi-displayconfig_source_device_name |
| Same path: `targetInfo.id` -> `monitorDevicePath`, `monitorFriendlyDeviceName`, EDID IDs | **Documented** (1.4); the path structure ties source and target ("Each element in *pathArray* describes a single path from a source to a target"). | https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-querydisplayconfig |
| `monitorDevicePath` == the `EnumDisplayDevices` interface name | **Observed** identical strings (5.4, 5.5); not stated by either page. | sections 5.4, 5.5 |
| `targetInfo.id` (4352) == the `UID4352` in the instance ID | **Observed.** The docs say the VidPN target identifier is the miniport's `ChildUid` ("Each child device of type **TypeVideoOutput** is associated with a video present target, and the **ChildUid** member ... is used as the identifier for the video present target", enumerating-child-devices page). That the instance ID embeds that number is inference from the two matching. | section 5.5 |
| `GetPhysicalMonitorsFromHMONITOR` handle -> which physical monitor of the view | **Undocumented.** The page says only "A single **HMONITOR** handle can be associated with more than one physical monitor. This function returns a handle and a text description for each physical monitor." On this PC each view has exactly one physical monitor and one `EnumDisplayDevices` monitor, so the pairing is unambiguous here; with a cloned/duplicated view it would not be. | https://learn.microsoft.com/en-us/windows/win32/api/physicalmonitorenumerationapi/nf-physicalmonitorenumerationapi-getphysicalmonitorsfromhmonitor |

A 2012 MSDN thread asked exactly this ("How to locate the EDID data folder/key in the registry,
which belongs to a specific PHYSICAL_MONITOR object",
https://learn.microsoft.com/en-us/archive/msdn-technet-forums/efc46c70-7479-4d59-822b-600cb4852c4b);
the Microsoft-disclaimered reply was "from looking at the structures and the APIs, I can't see a way
to tie a PHYSICAL_MONITOR or the hMonitor value back to an instance of GUID_DEVINTERFACE_MONITOR",
and a driver consultant's answer went via `DISPLAY_DEVICE.DeviceID` and the registry with the warning
"this is very fragile". The `EDD_GET_DEVICE_INTERFACE_NAME` text on today's `EnumDisplayDevices`
page (1.2) is the documented link that thread lacked; the `HMONITOR` -> `szDevice` -> adapter name
-> monitor `DeviceID` route is what closes it, per view.

**Answer to question 2.** Documented end to end except at two joints: the pairing of a physical
monitor handle with a specific monitor when a view has several (irrelevant on this PC), and the
string equivalences (interface path == PnP instance ID, `monitorDevicePath` == `DeviceID`), which
are observed rather than promised.

## 3. `0xC0262582`, physical-monitor handles and hot-plug (question 3)

### 3.1 The error definitions

Microsoft Learn, "COM Error Codes (COMADMIN, FILTER, GRAPHICS)" (Winerror.h,
https://learn.microsoft.com/en-us/windows/win32/com/com-error-codes-5), verbatim rows:

| Code | Name | Text |
|---|---|---|
| `0xC0262338` | `ERROR_GRAPHICS_MONITOR_NOT_CONNECTED` | "There is no monitor connected on the specified video present target." |
| `0xC0262580` | `ERROR_GRAPHICS_I2C_NOT_SUPPORTED` | "The monitor connected to the specified video output does not have an I2C bus." |
| `0xC0262581` | `ERROR_GRAPHICS_I2C_DEVICE_DOES_NOT_EXIST` | "No device on the I2C bus has the specified address." |
| `0xC0262582` | `ERROR_GRAPHICS_I2C_ERROR_TRANSMITTING_DATA` | "An error occurred while transmitting data to the device on the I2C bus." |
| `0xC0262583` | `ERROR_GRAPHICS_I2C_ERROR_RECEIVING_DATA` | "An error occurred while receiving data from the device on the I2C bus." |
| `0xC0262584` | `ERROR_GRAPHICS_DDCCI_VCP_NOT_SUPPORTED` | "The monitor does not support the specified VCP code." |
| `0xC0262585` | `ERROR_GRAPHICS_DDCCI_INVALID_DATA` | "The data received from the monitor is invalid." |
| `0xC026258B` | `ERROR_GRAPHICS_DDCCI_INVALID_MESSAGE_CHECKSUM` | "An error occurred because the checksum field in a DDC/CI message did not match the message's computed checksum value. This error implies that the data was corrupted while it was being transmitted from a monitor to a computer." |
| `0xC026258C` | `ERROR_GRAPHICS_INVALID_PHYSICAL_MONITOR_HANDLE` | "This function failed because an invalid monitor handle was passed to it." |
| `0xC026258D` | `ERROR_GRAPHICS_MONITOR_NO_LONGER_EXISTS` | "The operating system asynchronously destroyed the monitor which corresponds to this handle because the operating system's state changed. This error typically occurs because the monitor PDO associated with this handle was removed, the monitor PDO associated with this handle was stopped, or a display mode change occurred. A display mode change occurs when windows sends a WM_DISPLAYCHANGE windows message to applications." |
| `0xC02625E5` | `ERROR_GRAPHICS_NO_MONITORS_CORRESPOND_TO_DISPLAY_DEVICE` | "The function failed because the specified GDI device did not have any monitors associated with it." |

`0xC0262582` as a signed 32-bit integer is -1071241854, the value in `bridge.log` and #44.

The kernel-side origin gives the code its precise meaning. The display miniport DDI
`DxgkDdiI2CTransmitDataToDisplay`
(https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/dispmprt/nc-dispmprt-dxgkddi_i2c_transmit_data_to_display)
"transmits data to an I2C device in a monitor" and lists, among its return codes:

> "STATUS_GRAPHICS_MONITOR_NOT_CONNECTED: There is no monitor connected to the video output
> identified by VidPnTargetId."
> "STATUS_GRAPHICS_I2C_DEVICE_DOES_NOT_EXIST: No device acknowledged the I2C address supplied in
> SevenBitI2CAddress. This could mean that no device on the I2C bus has the specified address or that
> an error occurred when the address was transmitted."
> "STATUS_GRAPHICS_I2C_ERROR_TRANSMITTING_DATA: The I2C address was successfully transmitted, but
> there was an error transmitting data to the I2C device."

And: "**DxgkDdiI2CTransmitDataToDisplay** is responsible for signaling the I2C start condition,
sending the I2C address, sending the data in the buffer, checking for acknowledgments from the
receiver, and signaling the stop condition", "is required to transmit data to an I2C device that has
address 0x6E", and "is permitted to block if another part of the display miniport driver or graphics
hardware is using the specified monitor's I2C bus. It is also permitted to block if the display
miniport driver is using the I2C bus to send or receive High-bandwidth Digital Content Protection
(HDCP) data."

The Win32 name and the NTSTATUS name are the same word for word and share the low 16 bits (0x0582);
that the user-mode `ERROR_GRAPHICS_I2C_ERROR_TRANSMITTING_DATA` is the translated form of the DDI's
`STATUS_GRAPHICS_I2C_ERROR_TRANSMITTING_DATA` is inference by name, not stated on either page.
Reading the two together (**inference**): in State B the RD280UG's DDC/CI slave *acknowledged its
address* on every attempt (otherwise the code would have been `0xC0262581`) and then the data phase
failed; the monitor's DDC/CI controller was present on the bus but not completing transfers. That is
a different picture from an unplugged cable (no acknowledgment) and from a stale handle
(`0xC026258D`).

### 3.2 Handle lifetime and hot-plug

`GetPhysicalMonitorsFromHMONITOR` documents only: "When you are done using the monitor handles,
close them by passing the *pPhysicalMonitorArray* array to the DestroyPhysicalMonitors function."
`DestroyPhysicalMonitors` "Closes an array of physical monitor handles" and says nothing else
(https://learn.microsoft.com/en-us/windows/win32/api/physicalmonitorenumerationapi/nf-physicalmonitorenumerationapi-destroyphysicalmonitors).
The overview "Using the High-Level Monitor Configuration Functions"
(https://learn.microsoft.com/en-us/windows/win32/monitor/using-the-high-level-monitor-configuration-functions)
lists "Changes in Monitor State" (front-panel controls, resolution/refresh/bit-depth changes,
low-level writes, factory resets) and documents one recoverable error, `ERROR_DISABLED_MONITOR_SETTING`,
with the advice "Display an error message and suggest to the user that he or she try adjusting the
setting by using the front-panel control" or call `RestoreMonitorFactoryDefaults`. Neither page
mentions unplugging, replugging, or I2C errors.

The only documented statement about a handle outliving its monitor is the `0xC026258D` text above:
a handle dies when "the monitor PDO associated with this handle was removed, the monitor PDO
associated with this handle was stopped, or a display mode change occurred". So, to the direct
question: **yes, after an unplug/replug (a PDO removal and re-creation) a previously obtained handle
is documented to fail, with `0xC026258D`, and must be re-obtained.** The Bridge already does this on
every call (`_open_physical_monitor` enumerates afresh and `_destroy` closes after each use), and the
error it saw was `0xC0262582`, not `0xC026258D`; a stale handle was therefore not the State B cause.

**No documented recovery** exists for `0xC0262582` short of the monitor answering again: the
Monitor Configuration API pages document no reset, no bus re-initialisation and no retry policy
(the Bridge's three attempts 50 ms apart are its own, `_read_with_retries` in `ddc.py`). The
"Monitor Configuration" overview says only "Internally, the monitor configuration functions use the
Display Data Channel Command Interface (DDC/CI) to send commands to the monitor"
(https://learn.microsoft.com/en-us/windows/win32/monitor/monitor-configuration). What did recover it
on this PC is in section 5.7.

## 4. What removes a monitor from `EnumDisplayMonitors`, and what announces it (question 4)

### 4.1 What is enumerated

`EnumDisplayMonitors` "enumerates display monitors (including invisible pseudo-monitors associated
with the mirroring drivers) that intersect a region formed by the intersection of a specified
clipping rectangle and the visible region of a device context"; with both parameters NULL it
"Enumerates all display monitors" and "the visible region of interest is the virtual screen that
encompasses all the displays on the desktop"
(https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-enumdisplaymonitors). So the
enumeration is of the *desktop's* monitors, and the `DISPLAY_DEVICE_ACTIVE` note (1.2) says the
sibling API "will only enumerate monitors that can be presented as being 'on'". Whether a monitor in
DPMS sleep counts as "on" for this purpose is not stated on either page.

### 4.2 How Windows learns a monitor came or went

For HDMI the miniport declares the output `HpdAwarenessInterruptible` ("Child Devices of the Display
Adapter", https://learn.microsoft.com/en-us/windows-hardware/drivers/display/child-devices-of-the-display-adapter,
whose table lists "DVI, HDMI" under Interruptible; the enum page defines it as "the child device is
able to generate an interrupt when an external device is connected or disconnected",
https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/d3dkmdt/ne-d3dkmdt-_dxgk_child_device_hpd_awareness).
"The operating system is notified when an external display device is connected to or disconnected
from the child device." The notification is `DxgkCbIndicateChildStatus`
(https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/dispmprt/nc-dispmprt-dxgkcb_indicate_child_status):

> "The display miniport driver's DPC for ISR calls **DxgkCbIndicateChildStatus** when the display
> adapter generates an interrupt for any of the following reasons: An external device (typically a
> monitor) has been connected to one of the display adapter's child devices ... sets
> *ChildStatus*.**HotPlug**.**Connected** to **TRUE**. An external device (typically a monitor) has
> been disconnected ... sets *ChildStatus*.**HotPlug**.**Connected** to **FALSE**."

The PDO follows: "The display port driver creates a PDO for each child device that ... has an HPD
awareness value of **HpdAwarenessPolled** or **HpdAwarenessInterruptible**, and the operating system
knows from a previous query or notification that the child device has an external device connected"
(enumerating-child-devices page). And `DISPLAYCONFIG_PATH_TARGET_INFO.targetAvailable`:

> "Because the asynchronous nature of display topology changes when a monitor is removed, a path
> might still be marked as active even though the monitor has been removed. In such a case,
> **targetAvailable** could be **FALSE** for an active path. This is typically a transient situation
> that will change after the operating system takes action on the monitor removal."
> (https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ns-wingdi-displayconfig_path_target_info)

`DxgkDdiSetPowerState` adds the same latency from the other side: "The operating system might call
*DxgkDdiSetPowerState* on a child device of the display adapter that is no longer connected (for
example, a monitor that was recently unplugged). This anomaly occurs because an inherent latency
exists between the time that the operating system calls the driver's *DxgkDdiSetPowerState* and the
time that the operating system processes the disconnection"
(https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/dispmprt/nc-dispmprt-dxgkddi_set_power_state).

So the documented sequence for an HDMI monitor is: hot-plug-detect interrupt -> miniport reports
`Connected = FALSE` -> the OS removes the monitor PDO and reworks the topology -> the view leaves the
desktop -> `EnumDisplayMonitors` no longer returns it. Which physical events raise that interrupt
is the GPU's and the monitor's business: **an unplugged cable does** (the 18:00 case in #44, plainly
labelled State A); **whether the RD280UG drops its HDMI hot-plug line in its own standby or deep
sleep is not documented anywhere read**, and so whether States A at 21:08 and 22:04 were the monitor
sleeping is unknown from documents (inference: a monitor that de-asserts HPD in standby would look
exactly like State A). OS-driven blanking is a separate mechanism with its own notification,
`GUID_CONSOLE_DISPLAY_STATE` ("The current monitor's display state has changed" with
`PowerMonitorOff`/`On`/`Dim`) and `GUID_SESSION_DISPLAY_STATUS` ("The display associated with the
application's session has been powered on or off ... sent only to user-mode applications")
(https://learn.microsoft.com/en-us/windows/win32/power/power-setting-guids); nothing on that page
says the monitor leaves the desktop when the OS turns it off, and the `DxgkDdiSetPowerState` page
describes a power state for the child device, not its removal.

### 4.3 The messages

- `WM_DISPLAYCHANGE` "is sent to all windows when the display resolution has changed" (wParam bit
  depth, lParam width/height); "This message is only sent to top-level windows. For all other
  windows it is posted." (https://learn.microsoft.com/en-us/windows/win32/gdi/wm-displaychange).
  The `0xC026258D` text ties it to mode changes that invalidate physical-monitor handles.
- `WM_DEVICECHANGE` "Notifies an application of a change to the hardware configuration of a device
  or the computer", with `DBT_DEVNODES_CHANGED` (0x0007) "A device has been added to or removed from
  the system.", `DBT_DEVICEARRIVAL` (0x8000) "A device or piece of media has been inserted and is now
  available." and `DBT_DEVICEREMOVECOMPLETE` (0x8004) "A device or piece of media has been removed."
  (https://learn.microsoft.com/en-us/windows/win32/devio/wm-devicechange). `DBT_DEVICEARRIVAL`'s
  lParam is "A pointer to a structure identifying the device inserted ... treat the structure as a
  DEV_BROADCAST_HDR structure, then check its **dbch_devicetype** member"
  (https://learn.microsoft.com/en-us/windows/win32/devio/dbt-devicearrival); for an interface class
  it is `DEV_BROADCAST_DEVICEINTERFACE` with `dbcc_classguid` "The GUID for the interface device
  class." and `dbcc_name` "A null-terminated string that specifies the name of the device."
  (https://learn.microsoft.com/en-us/windows/win32/api/dbt/ns-dbt-dev_broadcast_deviceinterface_w).
  That `dbcc_name` is the same interface path as `EnumDisplayDevices` returns is inference (both
  are the `GUID_DEVINTERFACE_MONITOR` interface name; no page equates them).
- Getting the per-interface events requires `RegisterDeviceNotification` with
  `DBT_DEVTYP_DEVICEINTERFACE` and the class GUID; "Any application with a top-level window can
  receive basic notifications by processing the WM_DEVICECHANGE message. Applications can use the
  **RegisterDeviceNotification** function to register to receive device notifications." Only
  ports and volumes are broadcast without registering. The page also notes "You can use
  CM_Register_Notification instead of **RegisterDeviceNotification** if your code targets Windows 8
  or newer versions of Windows. The advantage of **CM_Register_Notification** is that it does not
  require a window handle to work."
  (https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerdevicenotificationw;
  worked example at https://learn.microsoft.com/en-us/windows/win32/devio/registering-for-device-notification).
  For a windowless Python service like the Bridge, `CM_Register_Notification` is the documented
  route (**inference** that it is the practical one; the page only says it removes the window
  requirement).

**Answer to question 4.** A cable pull is documented to remove the monitor from the desktop by way of
the HPD interrupt and PDO removal. The monitor's own standby and an HDMI link drop do the same *only
if* they de-assert hot-plug detect, which no document read decides for the RD280UG. OS display-off
is documented as a power state with its own notifications, not as a removal. The removal is
announced to a registered window/service by `WM_DEVICECHANGE` (`DBT_DEVICEREMOVECOMPLETE` /
`DBT_DEVICEARRIVAL` for `GUID_DEVINTERFACE_MONITOR`), to everyone by `DBT_DEVNODES_CHANGED`, and the
topology change by `WM_DISPLAYCHANGE`.

## 5. Live observation on this PC, 2026-09-16 22:31 (both monitors on, Bridge healthy)

All read-only. The `py` commands were run from `Bridges/BenQ_MoonHalo`; the ctypes script is
`enum_display_devices.py` in the session scratchpad and is reproduced in outline in 5.4/5.5.

### 5.1 `WmiMonitorID`

```
Get-CimInstance -Namespace root\wmi -ClassName WmiMonitorID | Select-Object InstanceName, Active,
  @{n='Mfr';e={[string]::new([char[]]($_.ManufacturerName -ne 0))}}, ... | Format-List

InstanceName      : DISPLAY\BNQ802E\5&3a1fce67&0&UID4353_0
Active            : True
Mfr               : BNQ
Product           : 802E
Serial            : ETSCL07402SL0
Name              : BenQ PD2700U
YearOfManufacture : 2020
WeekOfManufacture : 51

InstanceName      : DISPLAY\BNQ80BB\5&3a1fce67&0&UID4352_0
Active            : True
Mfr               : BNQ
Product           : 80BB
Serial            : EMS6T00258087
Name              : BenQ RD280UG
YearOfManufacture : 2026
WeekOfManufacture : 26
```

### 5.2 `Get-PnpDevice -Class Monitor`

```
Status       : Unknown   Present : False   Generic Monitor                 DISPLAY\DEFAULT_MONITOR\5&3A1FCE67&0&UID4352
Status       : Unknown   Present : False   Generic Monitor (BenQ PD2700U)  DISPLAY\BNQ802E\5&3A1FCE67&0&UID4352
Status       : OK        Present : True    Generic Monitor (BenQ PD2700U)  DISPLAY\BNQ802E\5&3A1FCE67&0&UID4353
Status       : OK        Present : True    Generic Monitor (BenQ RD280UG)  DISPLAY\BNQ80BB\5&3A1FCE67&0&UID4352
```

Four devnodes, two present. The PD2700U has an old node on `UID4352` (it sat on that target before
the cable moves of #40) and its live one on `UID4353`. The RD280UG is on `UID4352`. And there is a
`DEFAULT_MONITOR` node, hardware ID `MONITOR\Default_Monitor`, device description "Generic Non-PnP
Monitor", on `UID4352` as well: at some point Windows brought that target up **without a readable
EDID** and created a non-PnP monitor for it (5.7 dates it).

### 5.3 Registry `Enum\DISPLAY` (EDID cache)

```
DISPLAY\BNQ802E\5&3a1fce67&0&UID4352   Driver ...\0001  EDID 256 bytes; bytes 8-15: 09D1 2E80 01010101
DISPLAY\BNQ802E\5&3a1fce67&0&UID4353   Driver ...\0000  EDID 256 bytes; bytes 8-15: 09D1 2E80 01010101
DISPLAY\BNQ80BB\5&3a1fce67&0&UID4352   Driver ...\0002  EDID 384 bytes; bytes 8-15: 09D1 BB80 01010101
DISPLAY\Default_Monitor\5&3a1fce67&0&UID4352  Driver ...\0003  EDID (none)
```

Every real monitor key holds a `Device Parameters\EDID` value; the RD280UG's is three 128-byte
blocks, so on this Windows 11 build the whole E-EDID is cached, not only block 0. Bytes 8-9 `09 D1`
are the manufacturer ID (0x09D1 decodes to the PnP letters B-N-Q), bytes 10-11 the product code
little-endian (`BB 80` = 0x80BB), bytes 12-15 the 32-bit ID serial (0x01010101, i.e. BenQ leaves it
at 1 and puts the real serial in a descriptor string, which is what `WmiMonitorID.SerialNumberID`
returned). The same block 0 read through the documented WMI method agreed byte for byte:

```
Invoke-CimMethod ... WmiGetMonitorRawEEdidV1Block -Arguments @{BlockId=0}
DISPLAY\BNQ80BB\...UID4352_0  ReturnValue True  BlockType 1  Length 128
  Header 00 FF FF FF FF FF FF 00   bytes 8-15: 09 D1 BB 80 01 01 01 01   bytes 16-17: 1A 24
```

(`1A 24` = week 26, year 1990+36 = 2026, matching 5.1.) Enumerating `WmiMonitorRawEEdidV1Block`
instances directly returned "Not supported" (HRESULT 0x8004100c); the method is the working route.

### 5.4 `EnumDisplayDevices` (ctypes, `EDD_GET_DEVICE_INTERFACE_NAME` = 0x1)

```
adapter[0] DeviceName='\\.\DISPLAY1' DeviceString='NVIDIA GeForce RTX 4070 SUPER' StateFlags=0x00000001
    monitor[0] DeviceName='\\.\DISPLAY1\Monitor0'
               DeviceString='Generic PnP Monitor'
               StateFlags=0x00000003
               DeviceID='\\?\DISPLAY#BNQ80BB#5&3a1fce67&0&UID4352#{e6f07b5f-ee97-4a90-b076-33f57bf4eaa7}'
               DeviceKey='\Registry\Machine\System\CurrentControlSet\Control\Class\{4d36e96e-e325-11ce-bfc1-08002be10318}\0002'
    monitor[0] without flag: DeviceID='MONITOR\BNQ80BB\{4d36e96e-e325-11ce-bfc1-08002be10318}\0002'
adapter[1] DeviceName='\\.\DISPLAY2' DeviceString='NVIDIA GeForce RTX 4070 SUPER' StateFlags=0x00000005
    monitor[0] DeviceName='\\.\DISPLAY2\Monitor0'
               DeviceString='Generic PnP Monitor'
               StateFlags=0x00000003
               DeviceID='\\?\DISPLAY#BNQ802E#5&3a1fce67&0&UID4353#{e6f07b5f-ee97-4a90-b076-33f57bf4eaa7}'
               DeviceKey='...\{4d36e96e-e325-11ce-bfc1-08002be10318}\0000'
    monitor[0] without flag: DeviceID='MONITOR\BNQ802E\{4d36e96e-e325-11ce-bfc1-08002be10318}\0000'
adapter[2..3] '\\.\DISPLAY3', '\\.\DISPLAY4'  NVIDIA, StateFlags=0, no monitor
adapter[4..7] '\\.\DISPLAY5'..'\\.\DISPLAY8'  Intel(R) UHD Graphics 770, StateFlags=0, no monitor

EnumDisplayMonitors -> GetMonitorInfoW:
HMONITOR=0x71FB012F szDevice='\\.\DISPLAY1' primary=False rect=(1920,-835)-(3058,872)
HMONITOR=0x58A907EF szDevice='\\.\DISPLAY2' primary=True  rect=(0,0)-(1920,1080)
```

Both `DeviceID` forms name the PnP ID `BNQ80BB` for `\\.\DISPLAY1`; the flagged form is the
`GUID_DEVINTERFACE_MONITOR` path and contains the full instance ID. `DeviceString` is "Generic PnP
Monitor" for both monitors (the `DeviceDesc` from `monitor.inf`, per the registry in 5.3), which is
exactly why the Bridge's `szPhysicalMonitorDescription` cannot tell them apart (issue #40). The
`StateFlags` value 0x3 for each monitor includes bit 0x1 (`DISPLAY_DEVICE_ACTIVE`; the numeric value
is from `wingdi.h`, not printed on the Learn page).

### 5.5 `QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS)` + `DisplayConfigGetDeviceInfo`

```
path[0] source id=0 adapter=00000000:0000E1F6 -> viewGdiDeviceName='\\.\DISPLAY1'
        target id=4352 targetAvailable=True outputTechnology=5
        flags=0x5 edidManufactureId=0xD109 edidProductCodeId=0x80BB connectorInstance=0
        monitorFriendlyDeviceName='BenQ RD280UG'
        monitorDevicePath='\\?\DISPLAY#BNQ80BB#5&3a1fce67&0&UID4352#{e6f07b5f-ee97-4a90-b076-33f57bf4eaa7}'
path[1] source id=1 adapter=00000000:0000E1F6 -> viewGdiDeviceName='\\.\DISPLAY2'
        target id=4353 targetAvailable=True outputTechnology=10
        flags=0x5 edidManufactureId=0xD109 edidProductCodeId=0x802E connectorInstance=0
        monitorFriendlyDeviceName='BenQ PD2700U'
        monitorDevicePath='\\?\DISPLAY#BNQ802E#5&3a1fce67&0&UID4353#{e6f07b5f-ee97-4a90-b076-33f57bf4eaa7}'
```

`flags=0x5` = `friendlyNameFromEdid | edidIdsValid`. `outputTechnology` 5 is
`DISPLAYCONFIG_OUTPUT_TECHNOLOGY_HDMI` and 10 is `DISPLAYCONFIG_OUTPUT_TECHNOLOGY_DISPLAYPORT_EXTERNAL`
(https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ne-wingdi-displayconfig_video_output_technology),
confirming the RD280UG is on HDMI and the PD2700U on DisplayPort. `edidManufactureId` comes back as
0xD109, the EDID's big-endian 0x09D1 read as a little-endian 16-bit value; it decodes to "BNQ" only
after a byte swap (observed; the byte order is not documented). `edidProductCodeId` 0x80BB matches
5.1 and 5.3 directly. `WmiMonitorConnectionParams` agreed (`VideoOutputTechnology` 5 and 10).

### 5.6 The Bridge's view

```
py -m moonhalo_bridge monitors
device=\\.\DISPLAY1 primary=False description='Generic PnP Monitor'
device=\\.\DISPLAY2 primary=True description='Generic PnP Monitor'
selected: RD280UG on \\.\DISPLAY1 (by model)
```

**Pairing, right now:** the RD280UG's EDID identity (BNQ / 0x80BB / "BenQ RD280UG" / EMS6T00258087)
is visible through all four paths and every one of them lands on `\\.\DISPLAY1`, the same name the
Bridge selects by capabilities string. Whether these paths *stayed* readable during State B was not
measured (State B was over by the time this pass ran); see Open questions.

### 5.7 PnP timestamps and the event logs

`Get-PnpDeviceProperty` on the four devnodes (`DEVPKEY_Device_InstallDate` is documented as "the
time stamp when the device instance was last installed in the system",
https://learn.microsoft.com/en-us/windows-hardware/drivers/install/devpkey-device-installdate;
`DEVPKEY_Device_LastArrivalDate` / `LastRemovalDate` have no page on Learn that could be found and
are read here as the property names say):

```
DISPLAY\BNQ80BB\...UID4352  (RD280UG)      FirstInstall 2026-09-03 16:38  LastArrival 2026-09-16 22:19:53  LastRemoval (blank)
DISPLAY\BNQ802E\...UID4353  (PD2700U now)  FirstInstall 2026-09-16 10:07  LastArrival 2026-09-16 10:10:45  LastRemoval (blank)
DISPLAY\BNQ802E\...UID4352  (PD2700U old)  FirstInstall 2024-12-03        LastArrival 2026-09-01 16:40     LastRemoval 2026-09-03 16:37
DISPLAY\DEFAULT_MONITOR\...UID4352         FirstInstall 2026-09-07 09:47  LastArrival 2026-09-16 10:15:08  LastRemoval 2026-09-16 10:15:22
```

Two readings. First, **the RD280UG's devnode last arrived at 22:19:53**, i.e. after State B
(22:16:38-22:17:16 in `bridge.log`) and before the Bridge's recovery line at 22:21:22 ("monitor
RD280UG on \\.\DISPLAY1 by model"). Windows re-enumerated the monitor at 22:19:53, and DDC/CI worked
from then on. That is the PC-side answer to #44's "what recovered it": a PnP re-arrival of the
monitor, which on an HDMI output means the hot-plug line went away and came back (section 4.2).
Whether that was the button power-cycle the user was advised to do, or another replug, only the
user can say; the property records one arrival and the earlier ~22:15 replug is no longer visible
(`LastRemovalDate` is blank on the RD280UG despite the 18:00 unplug, so the property does not keep a
removal once the device is back; this is observed, not documented). Second, the `Default_Monitor`
node's 14-second life at 10:15:08-10:15:22 this morning, during the #40 cable work, shows what
Windows does when it brings the HDMI target up and **cannot read an EDID**: a non-PnP "Generic
Monitor" with no hardware ID. Nothing of the kind happened this evening, so in State B the EDID had
been read fine and only DDC/CI was failing (**inference** from the devnode being the real one).

The event logs add nothing: `Microsoft-Windows-Kernel-PnP/Configuration` holds only install-time
events (three today, all the PD2700U's new node at 10:07), and `System` had no `Kernel-PnP`,
`Display`, `nvlddmkm` or `DeviceSetupManager` entries in 17:40-22:35. Arrivals that need no driver
install are not logged there.

## What this means for the Bridge

1. **Identity can come from EDID, with the capabilities read demoted to a sanity check.** On this
   PC, `EnumDisplayDevices(szDevice, 0, EDD_GET_DEVICE_INTERFACE_NAME)` on the very `szDevice` the
   Bridge already gets from `GetMonitorInfoW` returns a `DeviceID` containing the PnP ID `BNQ80BB`,
   in one user32 call with no I2C. `QueryDisplayConfig` gives the same answer with the friendly name
   "BenQ RD280UG" and product code 0x80BB, keyed by `viewGdiDeviceName` (documented as the GDI name),
   at the cost of two more structures. Either way the match key is the EDID product identity
   (`BNQ80BB`, or manufacturer `BNQ` + product code 0x80BB), not a description and not a port. The
   capabilities `model(RD280UG)` read then becomes what it should have been: proof that the
   identified monitor *answers DDC/CI*, run once after identification, with the D9 probe as the
   halo-register check it already is. Which of the two identity APIs to bind is a design choice
   (**inference**: `EnumDisplayDevices` is the smaller change since `szDevice` is already in hand;
   the flagged `DeviceID` also gives the instance ID that `WmiMonitorID.InstanceName` and the
   registry key share, should the Bridge ever want the serial number).
2. **A sharper Monitor link error.** With identity settled first, the Bridge can say which of three
   things is wrong instead of "no monitor with model RD280UG among: unreadable (\\.\DISPLAY1)":
   - identified on `\\.\DISPLAYn` but DDC/CI fails with `0xC0262582`: "RD280UG on \\.\DISPLAY1
     identified by EDID; DDC/CI not answering (I2C transmit error 0xC0262582): the monitor
     acknowledges but does not complete transfers; power-cycle the monitor or replug the cable"
     (the recovery wording is inference from 5.7 and the DDI text; the code's meaning is documented);
   - identified but `0xC0262581` (no device at the address): controller not on the bus;
   - identified but `0xC026258D`: stale handle, re-enumerate (the Bridge already does);
   - not identified on any attached display (State A): "RD280UG not attached to the desktop", which
     a `WmiMonitorID`/PnP presence check could split into "not connected" versus "connected but not
     in the desktop topology" (inference that the split is useful; the APIs for it are documented).
   In every identified-but-failing case the link is still `failed`; what changes is that the text
   names the monitor and the failure instead of reporting it absent.
3. **Hot-plug needs no new handle discipline.** Handles are documented to die with the PDO
   (`0xC026258D`), and the Bridge already opens and destroys per call. If it wants to learn about a
   replug *before* the next hub command, the documented signal is `DBT_DEVICEARRIVAL` for
   `GUID_DEVINTERFACE_MONITOR` (via `RegisterDeviceNotification`, or `CM_Register_Notification`
   without a window); the display-set cache in `resolve_target` already covers the next call.
4. **What remains unknown.** (a) Whether the EDID paths keep answering while DDC/CI is stuck: not
   measured in State B, only argued from the devnode still existing and the registry cache. The
   check is one `EnumDisplayDevices` / `WmiMonitorID` read the next time `unreadable` appears.
   (b) What the user did at 22:19:53 (button, cable) and therefore which action the README should
   recommend first. (c) Whether the RD280UG de-asserts HDMI hot-plug in its own standby, which would
   make States A at 21:08 and 22:04 the monitor asleep; a `GUID_CONSOLE_DISPLAY_STATE` /
   `DBT_DEVICEREMOVECOMPLETE` listener, or simply the `LastArrivalDate` property read after the next
   State A, would settle it. (d) Whether NVIDIA's miniport serves EDID reads from a cache or the
   wire; undocumented and only relevant if (a) turns out badly. (e) Whether the Bridge process, as
   a scheduled task, has console-session access for `QueryDisplayConfig` (it does for
   `EnumDisplayMonitors`, which is the same session requirement in practice; inference).

## Open questions

- Are `WmiMonitorID` and `EnumDisplayDevices` still answering with the RD280UG's identity during a
  State B episode? (Expected yes; not observed.)
- What produced the 22:19:53 re-arrival: monitor button power-cycle, cable replug, or neither?
- Does the RD280UG drop HDMI hot-plug detect in standby or deep sleep (State A without a cable
  action)? No document read says; `docs/research/rd280ug-d6-power-mode.md` §9 found button standby
  still answers DDC/CI, which is a different state from "gone from the desktop".
- Is the `DISPLAY_DEVICE_ACTIVE` "presented as being 'on'" wording affected by DPMS off? Neither page
  says.
- Does the NVIDIA miniport answer `DxgkDdiQueryDeviceDescriptor` from the wire or a cache?

## Sources

Microsoft Learn (all read live 2026-09-16):

- WmiMonitorID class: https://learn.microsoft.com/en-us/windows/win32/wmicoreprov/wmimonitorid
- MSMonitorClass: https://learn.microsoft.com/en-us/windows/win32/wmicoreprov/msmonitorclass
- WmiMonitorRawEEdidV1Block: https://learn.microsoft.com/en-us/windows/win32/wmicoreprov/wmimonitorraweedidv1block
- WmiGetMonitorRawEEdidV1Block method: https://learn.microsoft.com/en-us/windows/win32/wmicoreprov/wmigetmonitorraweedidv1block-wmimonitordescriptormethods
- EnumDisplayDevicesW: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-enumdisplaydevicesw
- DISPLAY_DEVICEW: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ns-wingdi-display_devicew
- GUID_DEVINTERFACE_MONITOR: https://learn.microsoft.com/en-us/windows-hardware/drivers/install/guid-devinterface-monitor
- EnumDisplayMonitors: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-enumdisplaymonitors
- MONITORINFOEXW: https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-monitorinfoexw
- QueryDisplayConfig: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-querydisplayconfig
- DisplayConfigGetDeviceInfo: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-displayconfiggetdeviceinfo
- DISPLAYCONFIG_TARGET_DEVICE_NAME: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ns-wingdi-displayconfig_target_device_name
- DISPLAYCONFIG_TARGET_DEVICE_NAME_FLAGS: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ns-wingdi-displayconfig_target_device_name_flags
- DISPLAYCONFIG_SOURCE_DEVICE_NAME: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ns-wingdi-displayconfig_source_device_name
- DISPLAYCONFIG_PATH_TARGET_INFO: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ns-wingdi-displayconfig_path_target_info
- DISPLAYCONFIG_VIDEO_OUTPUT_TECHNOLOGY: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ne-wingdi-displayconfig_video_output_technology
- GetPhysicalMonitorsFromHMONITOR: https://learn.microsoft.com/en-us/windows/win32/api/physicalmonitorenumerationapi/nf-physicalmonitorenumerationapi-getphysicalmonitorsfromhmonitor
- DestroyPhysicalMonitors: https://learn.microsoft.com/en-us/windows/win32/api/physicalmonitorenumerationapi/nf-physicalmonitorenumerationapi-destroyphysicalmonitors
- Monitor Configuration (overview): https://learn.microsoft.com/en-us/windows/win32/monitor/monitor-configuration
- Using the High-Level Monitor Configuration Functions: https://learn.microsoft.com/en-us/windows/win32/monitor/using-the-high-level-monitor-configuration-functions
- COM Error Codes (COMADMIN, FILTER, GRAPHICS), Winerror.h: https://learn.microsoft.com/en-us/windows/win32/com/com-error-codes-5
- DXGKDDI_I2C_TRANSMIT_DATA_TO_DISPLAY: https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/dispmprt/nc-dispmprt-dxgkddi_i2c_transmit_data_to_display
- DXGKDDI_QUERY_DEVICE_DESCRIPTOR: https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/dispmprt/nc-dispmprt-dxgkddi_query_device_descriptor
- DXGKDDI_SET_POWER_STATE: https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/dispmprt/nc-dispmprt-dxgkddi_set_power_state
- DXGKCB_INDICATE_CHILD_STATUS: https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/dispmprt/nc-dispmprt-dxgkcb_indicate_child_status
- DXGK_CHILD_STATUS: https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/dispmprt/ns-dispmprt-_dxgk_child_status
- DXGK_CHILD_DEVICE_HPD_AWARENESS: https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/d3dkmdt/ne-d3dkmdt-_dxgk_child_device_hpd_awareness
- Child Devices of the Display Adapter: https://learn.microsoft.com/en-us/windows-hardware/drivers/display/child-devices-of-the-display-adapter
- Enumerating Child Devices of a Display Adapter: https://learn.microsoft.com/en-us/windows-hardware/drivers/display/enumerating-child-devices-of-a-display-adapter
- Monitor Driver Stack: https://learn.microsoft.com/en-us/windows-hardware/drivers/display/monitor-drivers
- Monitor Class Function Driver: https://learn.microsoft.com/en-us/windows-hardware/drivers/display/monitor-class-function-driver
- Using an INF File to Override EDIDs: https://learn.microsoft.com/en-us/windows-hardware/drivers/display/overriding-monitor-edids
- Monitor INF File Sections (archived): https://learn.microsoft.com/en-us/previous-versions/windows/drivers/display/monitor-inf-file-sections
- Device Instance ID: https://learn.microsoft.com/en-us/windows-hardware/drivers/install/device-instance-ids
- Hardware ID: https://learn.microsoft.com/en-us/windows-hardware/drivers/install/hardware-ids
- DEVPKEY_Device_InstallDate: https://learn.microsoft.com/en-us/windows-hardware/drivers/install/devpkey-device-installdate
- WM_DISPLAYCHANGE: https://learn.microsoft.com/en-us/windows/win32/gdi/wm-displaychange
- WM_DEVICECHANGE: https://learn.microsoft.com/en-us/windows/win32/devio/wm-devicechange
- DBT_DEVICEARRIVAL: https://learn.microsoft.com/en-us/windows/win32/devio/dbt-devicearrival
- DEV_BROADCAST_DEVICEINTERFACE_W: https://learn.microsoft.com/en-us/windows/win32/api/dbt/ns-dbt-dev_broadcast_deviceinterface_w
- RegisterDeviceNotificationW: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerdevicenotificationw
- Registering for device notification: https://learn.microsoft.com/en-us/windows/win32/devio/registering-for-device-notification
- Power Setting GUIDs: https://learn.microsoft.com/en-us/windows/win32/power/power-setting-guids

Archived MSDN forum threads (secondary; one Microsoft-disclaimered answer each):

- "how to read edid data direct from monitor (not registry)" (2012-2017): https://learn.microsoft.com/en-us/archive/msdn-technet-forums/1a19a278-c296-4d34-ade7-83bf3315db96
- "How to locate the EDID data folder/key in the registry, which belongs to a specific PHYSICAL_MONITOR object" (2012): https://learn.microsoft.com/en-us/archive/msdn-technet-forums/efc46c70-7479-4d59-822b-600cb4852c4b

Hubitat community forum: searches for "DDC/CI", "EDID" and "WmiMonitorID" returned no relevant
thread (PC-side topic).

This repo: issue #44 (`gh issue view 44`), `Bridges/BenQ_MoonHalo/bridge.log` (2026-09-16
entries), `Bridges/BenQ_MoonHalo/moonhalo_bridge/ddc.py` (`_detect`, `list_monitors`,
`_open_physical_monitor`, `_read_with_retries`), `docs/research/rd280ug-d6-power-mode.md` §5 and §9,
`docs/research/ddcci-windows-api.md`. Scratch script: `enum_display_devices.py` in the session
scratchpad (ctypes; `EnumDisplayDevicesW`, `EnumDisplayMonitors`, `GetMonitorInfoW`,
`GetDisplayConfigBufferSizes`, `QueryDisplayConfig`, `DisplayConfigGetDeviceInfo`; no dxva2 calls).

## What is documented fact vs inference

Documented: everything quoted in sections 1-4: the `WmiMonitorID` fields and their E-EDID origin;
the WMI -> Monitor.sys -> PDO -> DDC-over-I2C path for an EDID read and the port driver's EDID read
at enumeration; `EDD_GET_DEVICE_INTERFACE_NAME` as "a link between GDI monitor devices and SetupAPI
monitor devices"; the EDID override registry mechanism; the `DISPLAYCONFIG_TARGET_DEVICE_NAME`
fields and flags; `szDevice` and `viewGdiDeviceName` as GDI device names; the error-code texts
including `0xC0262582` and `0xC026258D`; the DDI meaning of "transmitting data" (address
acknowledged, data failed); HPD awareness, `DxgkCbIndicateChildStatus`, PDO creation rules and the
`targetAvailable` latency; the `WM_DISPLAYCHANGE` / `WM_DEVICECHANGE` / `RegisterDeviceNotification`
/ `CM_Register_Notification` behaviours; the power-setting GUIDs.

Observed on this PC (section 5): the identity values, the string equivalences between the interface
path, the PnP instance ID, `WmiMonitorID.InstanceName` and `monitorDevicePath`; the 384-byte
registry EDID; the byte-swapped `edidManufactureId`; the `Default_Monitor` node and its 14-second
life this morning; the RD280UG's 22:19:53 re-arrival between State B and recovery.

Inference: that a 0x6E failure need not imply an EDID-address failure; that the NTSTATUS and Win32
codes correspond by name; that in State B the controller acknowledged but did not complete
transfers; that States A at 21:08/22:04 could be the monitor de-asserting hot-plug in standby; that
`dbcc_name` equals the `EnumDisplayDevices` interface path; that the 22:19:53 arrival was the
user's power-cycle or replug; that the `Default_Monitor` node marks an EDID read failure; the
`LastRemovalDate` clearing behaviour; every design suggestion in "What this means for the Bridge".
