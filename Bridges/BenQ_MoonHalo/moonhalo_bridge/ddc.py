"""DDC/CI port abstraction: list monitors, pick the MoonHalo monitor, read
and write VCP registers.

`DdcPort` is the interface; `WindowsDdcPort` drives the real monitor
through the Windows Monitor Configuration API (dxva2.dll / user32.dll via
ctypes) and `FakeDdcPort` is the in-memory stand-in for tests and
`--dry-run`.

Monitor detection (issues #40, #44) happens here, once per display set.
With `monitor_selector` set, the first monitor whose device name or
description contains it is the target. Otherwise the target is the
attached monitor whose EDID identity has product `monitor_product`
(default `BNQ80BB`, the RD280UG). The identity is the registry's EDID
cache, located through `EnumDisplayDevices`, so detection makes no
DDC/CI call: the first read or write is the first one. One match is rule
`edid`; several take the first with one warning (`first-of-ambiguous`);
none is a miss, raised as `DdcError` naming what is attached and tried
again on every call. A DDC/CI failure on the identified monitor is
re-raised with its label and `identified by EDID; DDC/CI not answering:`
in front, so a stuck link never reads as an absent monitor. The README
has the details.

Windows-only bindings load lazily in `WindowsDdcPort.__init__`, so this
module imports on any OS.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Optional, TypeVar, Union

from .edid import EdidIdentity, device_parameters_key, parse_edid

T = TypeVar("T")

_logger = logging.getLogger(__name__)

#: Total read attempts (the original try plus retries) before giving up.
DEFAULT_READ_RETRIES = 3
#: Pause between read attempts, in seconds.
DEFAULT_READ_RETRY_DELAY = 0.05
#: The EDID product (manufacturer letters plus product code) the Bridge
#: looks for when no selector is set: the RD280UG's.
DEFAULT_MONITOR_PRODUCT = "BNQ80BB"
#: EDID names of known products, so a miss can name the monitor before
#: it has ever been seen.
KNOWN_PRODUCT_NAMES = {DEFAULT_MONITOR_PRODUCT: "BenQ RD280UG"}
#: What `target_label` (and so `state.monitor`) reads before any
#: resolution and after a miss.
UNKNOWN_LABEL = "unknown"
#: `EnumDisplayDevices` flag: return the monitor's device interface path.
EDD_GET_DEVICE_INTERFACE_NAME = 0x00000001


@dataclass(frozen=True)
class MonitorInfo:
    """One physical monitor attached to the system.

    device_name: the GDI device name of the parent display (e.g. ``\\\\.\\DISPLAY1``).
    primary: True if the parent display is the Windows primary monitor.
    description: the physical monitor's DDC/CI description string.
    product, name, serial: its EDID identity (``BNQ80BB``, ``BenQ RD280UG``,
        ``EMS6T00258087``); all None when Windows has no EDID for it, name
        or serial None when the EDID lacks that descriptor.
    """

    device_name: str
    primary: bool
    description: str
    product: Optional[str] = None
    name: Optional[str] = None
    serial: Optional[str] = None

    def describe(self) -> str:
        """`BenQ RD280UG BNQ80BB (\\\\.\\DISPLAY1)`; `BNQ80BB (...)` with no
        name; `no EDID (...)` with no identity."""
        if self.product is None:
            what = "no EDID"
        elif self.name is None:
            what = self.product
        else:
            what = f"{self.name} {self.product}"
        return f"{what} ({self.device_name})"


#: The monitor a bare `FakeDdcPort()` and `--dry-run` have: the RD280UG's
#: product and name with a made-up serial, so it is detected by `edid`
#: like the real monitor.
DEFAULT_FAKE_MONITOR = MonitorInfo(
    device_name="DRYRUN1",
    primary=True,
    description="Generic PnP Monitor",
    product=DEFAULT_MONITOR_PRODUCT,
    name=KNOWN_PRODUCT_NAMES[DEFAULT_MONITOR_PRODUCT],
    serial="FAKE00000000",
)


class DdcError(Exception):
    """A DDC/CI operation failed.

    `win32_error` carries the value of `GetLastError()` when the failure
    came from a Win32 call, printed as decimal and hex (`-1071241854 =
    0xC0262582`), or `None` for errors raised without one (for example an
    unknown VCP code on `FakeDdcPort`).
    """

    def __init__(self, message: str, win32_error: Optional[int] = None):
        self.win32_error = win32_error
        if win32_error is not None:
            message = f"{message} (Win32 error {win32_error} = 0x{win32_error & 0xFFFFFFFF:08X})"
        super().__init__(message)

    def on_identified(self, label: str) -> "DdcError":
        """This failure as reported when it happened on a monitor that
        detection identified by EDID."""
        error = DdcError(f"{label} identified by EDID; DDC/CI not answering: {self}")
        error.win32_error = self.win32_error
        return error


@dataclass(frozen=True)
class Detection:
    """The outcome of picking the target monitor (see the module docstring).

    device_name: the chosen monitor's device name; None when none was chosen.
    label: what `state.monitor` reports: `"<EDID name> on <device name>"`
        for a detected monitor (its product when the EDID has no name),
        `"<description> on <device name>"` for a selector match,
        `UNKNOWN_LABEL` when none was chosen.
    rule: how it was chosen: "selector", "edid", "first-of-ambiguous", or "none".
    seen: the attached device names at the time, sorted -- the display set
        a later call compares against to decide whether to resolve again.
    error: why nothing was chosen; None when something was.
    candidates: every monitor detection looked at, as `MonitorInfo.describe`
        gives them; empty for a selector match.
    """

    device_name: Optional[str]
    label: str
    rule: str
    seen: tuple[str, ...]
    error: Optional[str] = None
    candidates: tuple[str, ...] = ()

    @property
    def found(self) -> bool:
        return self.device_name is not None


def _read_with_retries(
    read_once: Callable[[], T],
    retries: int = DEFAULT_READ_RETRIES,
    delay: float = DEFAULT_READ_RETRY_DELAY,
) -> T:
    """Call `read_once()` up to `retries` times, pausing `delay` seconds
    between attempts, and re-raise the last `DdcError` if every attempt
    fails. `read_vcp` goes through here, so the retry behaviour can be
    exercised through `FakeDdcPort` in tests.
    """
    last_error: Optional[DdcError] = None
    for attempt in range(retries):
        try:
            return read_once()
        except DdcError as error:
            last_error = error
            if attempt < retries - 1:
                time.sleep(delay)
    assert last_error is not None
    raise last_error


class DdcPort(ABC):
    """Port to a monitor's DDC/CI interface.

    Subclasses provide `list_monitors` and the per-device primitives
    (`_read_vcp_on`, `_write_vcp_on`); the public `read_vcp` and
    `write_vcp` resolve the target monitor here first (see the module
    docstring), retrying reads.
    """

    def __init__(
        self,
        monitor_selector: Optional[str] = None,
        monitor_product: str = DEFAULT_MONITOR_PRODUCT,
        retries: int = DEFAULT_READ_RETRIES,
        retry_delay: float = DEFAULT_READ_RETRY_DELAY,
        logger: Optional[logging.Logger] = None,
    ):
        self.monitor_selector = monitor_selector
        self.monitor_product = monitor_product
        self._retries = retries
        self._retry_delay = retry_delay
        #: Where detection lines go: `serve` passes the Bridge's file
        #: logger so they land in `bridge.log`; the CLI a stderr logger.
        self._logger = logger if logger is not None else _logger
        self._detection: Optional[Detection] = None
        #: The reason of the last miss logged; a repeat is not logged again.
        self._last_miss: Optional[str] = None

    # -- interface -------------------------------------------------------

    @abstractmethod
    def list_monitors(self) -> list[MonitorInfo]:
        """Return every physical monitor attached to the system, with its
        EDID identity."""

    @abstractmethod
    def _read_vcp_on(self, device_name: str, code: int) -> tuple[int, int]:
        """One attempt at `(current, maximum)` for `code` on that display."""

    @abstractmethod
    def _write_vcp_on(self, device_name: str, code: int, value: int) -> None:
        """Write `value` to `code` on that display."""

    # -- the target monitor ------------------------------------------------

    @property
    def detection(self) -> Optional[Detection]:
        """The last resolution, or None before the first."""
        return self._detection

    @property
    def target_label(self) -> str:
        """`"<name> on <device name>"` for the current target, or
        `UNKNOWN_LABEL` before the first resolution or after a miss. What
        the model reports as `state.monitor`."""
        return self._detection.label if self._detection is not None else UNKNOWN_LABEL

    def resolve_target(self) -> Detection:
        """Resolve the target monitor for the attached display set, reusing
        the last result while the set of device names is unchanged and it
        found something; a miss is tried again on every call. Never raises
        for a miss: the returned Detection says so (and the port calls
        raise from it)."""
        monitors = self.list_monitors()
        seen = tuple(sorted({monitor.device_name for monitor in monitors}))
        cached = self._detection
        if cached is not None and cached.found and cached.seen == seen:
            return cached
        if not monitors:
            detection = Detection(None, UNKNOWN_LABEL, "none", seen, "No display monitors found")
        elif self.monitor_selector:
            detection = self._select(monitors, seen)
        else:
            detection = self._detect(monitors, seen)
        self._log(detection)
        self._detection = detection
        return detection

    def _log(self, detection: Detection) -> None:
        """One line per detection; a miss only when its reason is new."""
        if detection.rule == "selector":
            self._logger.info(
                "monitor %s by selector %r", detection.label, self.monitor_selector
            )
        elif detection.found:
            self._logger.info(
                "monitor %s by %s; candidates: %s",
                detection.label,
                detection.rule,
                ", ".join(detection.candidates),
            )
        elif detection.error != self._last_miss:
            self._logger.warning("monitor not found: %s", detection.error)
        self._last_miss = detection.error

    def _on_target(self, action: Callable[[str], T]) -> T:
        """Run `action(device_name)` on the target monitor. A miss raises
        its reason; a `DdcError` on a monitor identified by EDID is
        re-raised with the identity in front."""
        detection = self.resolve_target()
        if not detection.found:
            assert detection.error is not None
            raise DdcError(detection.error)
        assert detection.device_name is not None
        try:
            return action(detection.device_name)
        except DdcError as error:
            if detection.rule == "selector":
                raise
            raise error.on_identified(detection.label) from error

    def _select(self, monitors: list[MonitorInfo], seen: tuple[str, ...]) -> Detection:
        """The manual override: first monitor whose device name or
        description contains `monitor_selector`, case-insensitive."""
        needle = self.monitor_selector.lower()
        for monitor in monitors:
            if needle in monitor.device_name.lower() or needle in monitor.description.lower():
                return Detection(
                    monitor.device_name,
                    f"{monitor.description} on {monitor.device_name}",
                    "selector",
                    seen,
                )
        among = ", ".join(f"{m.description} ({m.device_name})" for m in monitors)
        return Detection(
            None,
            UNKNOWN_LABEL,
            "none",
            seen,
            f"no monitor matches selector {self.monitor_selector!r} among: {among}",
        )

    def _detect(self, monitors: list[MonitorInfo], seen: tuple[str, ...]) -> Detection:
        """Detection by EDID identity: the monitors whose product is
        `monitor_product`, compared case-insensitively."""
        candidates: list[MonitorInfo] = []
        for monitor in monitors:
            if all(c.device_name != monitor.device_name for c in candidates):
                candidates.append(monitor)
        described = tuple(c.describe() for c in candidates)
        wanted = self.monitor_product.upper()
        matches = [c for c in candidates if c.product is not None and c.product.upper() == wanted]
        if not matches:
            return Detection(
                None,
                UNKNOWN_LABEL,
                "none",
                seen,
                f"{self._wanted_label()} is not attached: asleep, off or unplugged; "
                f"attached: {', '.join(described)}",
                candidates=described,
            )
        rule = "edid"
        if len(matches) > 1:
            rule = "first-of-ambiguous"
            self._logger.warning(
                "%d monitors have product %s, taking the first: %s",
                len(matches),
                self.monitor_product,
                ", ".join(c.describe() for c in matches),
            )
        winner = matches[0]
        return Detection(
            winner.device_name,
            f"{winner.name or winner.product} on {winner.device_name}",
            rule,
            seen,
            candidates=described,
        )

    def _wanted_label(self) -> str:
        """`BenQ RD280UG (BNQ80BB)` for a known product; the bare product
        otherwise."""
        name = KNOWN_PRODUCT_NAMES.get(self.monitor_product.upper())
        return f"{name} ({self.monitor_product})" if name else self.monitor_product

    # -- reads and writes ------------------------------------------------

    def read_vcp(self, code: int) -> tuple[int, int]:
        """Return `(current, maximum)` for the given VCP feature code on
        the target monitor, retrying a transient failure."""
        return self._on_target(
            lambda device: _read_with_retries(
                lambda: self._read_vcp_on(device, code), self._retries, self._retry_delay
            )
        )

    def write_vcp(self, code: int, value: int) -> None:
        """Write `value` to the given VCP feature code on the target monitor."""
        self._on_target(lambda device: self._write_vcp_on(device, code, value))


class WindowsDdcPort(DdcPort):
    """Real DDC/CI port using the Windows Monitor Configuration API.

    Opens a physical monitor handle for each operation and destroys it
    with `DestroyPhysicalMonitors` afterwards. Which display the handle is
    opened on is the target resolved by `DdcPort` (selector or detection).
    The EDID identity of each monitor is read from the registry cache
    under its device interface path (`EnumDisplayDevices` with
    `EDD_GET_DEVICE_INTERFACE_NAME` on the display's device name).
    """

    def __init__(
        self,
        monitor_selector: Optional[str] = None,
        monitor_product: str = DEFAULT_MONITOR_PRODUCT,
        retries: int = DEFAULT_READ_RETRIES,
        retry_delay: float = DEFAULT_READ_RETRY_DELAY,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(monitor_selector, monitor_product, retries, retry_delay, logger)
        self._load_bindings()

    def _load_bindings(self) -> None:
        """Import ctypes and declare the Win32 signatures. Windows-only;
        called only when a WindowsDdcPort is actually constructed."""
        import ctypes
        import ctypes.wintypes as wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._dxva2 = ctypes.WinDLL("dxva2", use_last_error=True)

        class PHYSICAL_MONITOR(ctypes.Structure):
            _fields_ = [
                ("hPhysicalMonitor", wintypes.HANDLE),
                ("szPhysicalMonitorDescription", wintypes.WCHAR * 128),
            ]

        class MONITORINFOEXW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
                ("szDevice", wintypes.WCHAR * 32),
            ]

        class DISPLAY_DEVICEW(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("DeviceName", wintypes.WCHAR * 32),
                ("DeviceString", wintypes.WCHAR * 128),
                ("StateFlags", wintypes.DWORD),
                ("DeviceID", wintypes.WCHAR * 128),
                ("DeviceKey", wintypes.WCHAR * 128),
            ]

        self._PHYSICAL_MONITOR = PHYSICAL_MONITOR
        self._MONITORINFOEXW = MONITORINFOEXW
        self._DISPLAY_DEVICEW = DISPLAY_DEVICEW
        self._MONITORENUMPROC = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HMONITOR,
            wintypes.HDC,
            ctypes.POINTER(wintypes.RECT),
            wintypes.LPARAM,
        )

        self._user32.EnumDisplayMonitors.argtypes = [
            wintypes.HDC,
            ctypes.POINTER(wintypes.RECT),
            self._MONITORENUMPROC,
            wintypes.LPARAM,
        ]
        self._user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
        self._user32.EnumDisplayDevicesW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.POINTER(DISPLAY_DEVICEW),
            wintypes.DWORD,
        ]
        self._user32.EnumDisplayDevicesW.restype = wintypes.BOOL
        self._dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR.argtypes = [
            wintypes.HMONITOR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._dxva2.GetPhysicalMonitorsFromHMONITOR.argtypes = [
            wintypes.HMONITOR,
            wintypes.DWORD,
            ctypes.POINTER(PHYSICAL_MONITOR),
        ]
        self._dxva2.SetVCPFeature.argtypes = [wintypes.HANDLE, wintypes.BYTE, wintypes.DWORD]
        self._dxva2.GetVCPFeatureAndVCPFeatureReply.argtypes = [
            wintypes.HANDLE,
            wintypes.BYTE,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._dxva2.DestroyPhysicalMonitors.argtypes = [wintypes.DWORD, ctypes.POINTER(PHYSICAL_MONITOR)]

    # -- monitor enumeration -------------------------------------------------

    def _enum_hmonitors(self) -> list:
        hmons: list = []

        def _cb(hmon, hdc, rect, lparam):
            hmons.append(hmon)
            return True

        self._user32.EnumDisplayMonitors(None, None, self._MONITORENUMPROC(_cb), 0)
        return hmons

    def _monitor_info(self, hmon) -> tuple[str, bool]:
        ctypes = self._ctypes
        info = self._MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(self._MONITORINFOEXW)
        self._user32.GetMonitorInfoW(hmon, ctypes.byref(info))
        primary = bool(info.dwFlags & 1)
        return info.szDevice, primary

    def _physical_monitors(self, hmon):
        ctypes = self._ctypes
        wintypes = self._wintypes
        n = wintypes.DWORD(0)
        self._dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(hmon, ctypes.byref(n))
        if n.value == 0:
            return (self._PHYSICAL_MONITOR * 0)()
        arr = (self._PHYSICAL_MONITOR * n.value)()
        if not self._dxva2.GetPhysicalMonitorsFromHMONITOR(hmon, n.value, arr):
            raise DdcError("GetPhysicalMonitorsFromHMONITOR failed", ctypes.get_last_error())
        return arr

    def _destroy(self, arr) -> None:
        if len(arr) == 0:
            return
        self._dxva2.DestroyPhysicalMonitors(len(arr), arr)

    def list_monitors(self) -> list[MonitorInfo]:
        result: list[MonitorInfo] = []
        for hmon in self._enum_hmonitors():
            device_name, primary = self._monitor_info(hmon)
            arr = self._physical_monitors(hmon)
            try:
                for index, pm in enumerate(arr):
                    identity = self._edid_identity(device_name, index)
                    result.append(
                        MonitorInfo(
                            device_name=device_name,
                            primary=primary,
                            description=pm.szPhysicalMonitorDescription,
                            product=identity.product if identity else None,
                            name=identity.name if identity else None,
                            serial=identity.serial if identity else None,
                        )
                    )
            finally:
                self._destroy(arr)
        return result

    # -- EDID identity ----------------------------------------------------

    def _interface_path(self, device_name: str, index: int) -> Optional[str]:
        """The device interface path of the `index`th monitor of that
        display (`\\\\?\\DISPLAY#BNQ80BB#...#{guid}`), or None when Windows
        lists none."""
        ctypes = self._ctypes
        device = self._DISPLAY_DEVICEW()
        device.cb = ctypes.sizeof(self._DISPLAY_DEVICEW)
        ok = self._user32.EnumDisplayDevicesW(
            device_name, index, ctypes.byref(device), EDD_GET_DEVICE_INTERFACE_NAME
        )
        if not ok or not device.DeviceID:
            return None
        return device.DeviceID

    def _registry_edid(self, interface_path: str) -> Optional[bytes]:
        """The cached EDID bytes under that monitor's `Device Parameters`
        key, or None when the key or the value is missing."""
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, device_parameters_key(interface_path)) as key:
                value, kind = winreg.QueryValueEx(key, "EDID")
        except (OSError, ValueError):
            return None
        return bytes(value) if kind == winreg.REG_BINARY else None

    def _edid_identity(self, device_name: str, index: int) -> Optional[EdidIdentity]:
        """The EDID identity of that monitor; None when Windows has no
        EDID for it."""
        path = self._interface_path(device_name, index)
        data = self._registry_edid(path) if path is not None else None
        if data is None:
            return None
        try:
            return parse_edid(data)
        except ValueError as error:
            self._logger.debug("EDID of %s not parsed: %s", device_name, error)
            return None

    def _open_physical_monitor(self, device_name: str):
        """Return the PHYSICAL_MONITOR array of the display named
        `device_name` (index 0 is the handle used); the caller destroys it
        after use."""
        for hmon in self._enum_hmonitors():
            name, _ = self._monitor_info(hmon)
            if name != device_name:
                continue
            arr = self._physical_monitors(hmon)
            if len(arr) == 0:
                raise DdcError(f"display {device_name} has no physical monitor handle")
            return arr
        raise DdcError(f"display {device_name} is no longer attached")

    # -- VCP ------------------------------------------------------------

    def _read_vcp_on(self, device_name: str, code: int) -> tuple[int, int]:
        ctypes = self._ctypes
        wintypes = self._wintypes
        arr = self._open_physical_monitor(device_name)
        try:
            handle = arr[0].hPhysicalMonitor
            current, maximum, vcp_type = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
            ok = self._dxva2.GetVCPFeatureAndVCPFeatureReply(
                handle,
                wintypes.BYTE(code),
                ctypes.byref(vcp_type),
                ctypes.byref(current),
                ctypes.byref(maximum),
            )
            if not ok:
                raise DdcError(
                    f"GetVCPFeatureAndVCPFeatureReply failed for VCP 0x{code:02X}",
                    ctypes.get_last_error(),
                )
            return current.value, maximum.value
        finally:
            self._destroy(arr)

    def _write_vcp_on(self, device_name: str, code: int, value: int) -> None:
        wintypes = self._wintypes
        arr = self._open_physical_monitor(device_name)
        try:
            handle = arr[0].hPhysicalMonitor
            ok = self._dxva2.SetVCPFeature(handle, wintypes.BYTE(code), wintypes.DWORD(value))
            if not ok:
                raise DdcError(
                    f"SetVCPFeature failed for VCP 0x{code:02X}",
                    self._ctypes.get_last_error(),
                )
        finally:
            self._destroy(arr)


@dataclass
class FakeMonitor:
    """One monitor of a `FakeDdcPort`: its identity plus its own
    registers, scripted failures and writes.

    `registers` maps VCP code -> `(current, maximum)`; a write updates it
    (preserving the maximum) so a following read reflects it. `fail_reads`
    maps VCP code -> a count of scripted read failures still owed; each
    read of that code consumes one before falling through to `registers`,
    which is how tests exercise the retry path without hardware.
    `write_error` is a Win32 error code every write fails with (None
    writes normally), standing for a stuck DDC/CI link.
    `writes` records this monitor's `(code, value)` writes in order.
    """

    info: MonitorInfo
    registers: dict[int, tuple[int, int]] = field(default_factory=dict)
    fail_reads: dict[int, int] = field(default_factory=dict)
    write_error: Optional[int] = None
    writes: list[tuple[int, int]] = field(default_factory=list)

    @property
    def device_name(self) -> str:
        return self.info.device_name


class FakeDdcPort(DdcPort):
    """In-memory DDC port for tests and `--dry-run`.

    `monitors` lists the attached monitors as `FakeMonitor`s, or as
    `MonitorInfo`s that all get a copy of `registers`; the default is one
    primary "Generic PnP Monitor" with the RD280UG's EDID identity that
    answers as the RD280UG. `fake_monitors` is that list, editable between
    calls to stand for a cable swap. `writes` records every `write_vcp`
    call port-wide as `(code, value)`, in the order made;
    `monitor(device_name).writes` has the ones that reached each monitor.
    `reads` records every VCP read attempt as `(device_name, code)`, so a
    test can show detection made none.

    `registers` and `fail_reads` are those of the first listed monitor,
    which is what a one-monitor test means by "the monitor".
    """

    def __init__(
        self,
        monitors: Optional[list[Union[MonitorInfo, FakeMonitor]]] = None,
        registers: Optional[dict[int, tuple[int, int]]] = None,
        retries: int = DEFAULT_READ_RETRIES,
        retry_delay: float = 0.0,
        monitor_selector: Optional[str] = None,
        monitor_product: str = DEFAULT_MONITOR_PRODUCT,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(monitor_selector, monitor_product, retries, retry_delay, logger)
        if monitors is None:
            monitors = [DEFAULT_FAKE_MONITOR]
        self.fake_monitors: list[FakeMonitor] = [
            entry
            if isinstance(entry, FakeMonitor)
            else FakeMonitor(entry, registers=dict(registers) if registers else {})
            for entry in monitors
        ]
        self.writes: list[tuple[int, int]] = []
        self.reads: list[tuple[str, int]] = []

    # -- the first monitor's state, for one-monitor tests ------------------

    @property
    def _first(self) -> FakeMonitor:
        return self.fake_monitors[0]

    @property
    def monitors(self) -> list[MonitorInfo]:
        return [monitor.info for monitor in self.fake_monitors]

    @property
    def registers(self) -> dict[int, tuple[int, int]]:
        return self._first.registers

    @registers.setter
    def registers(self, value: dict[int, tuple[int, int]]) -> None:
        self._first.registers = value

    @property
    def fail_reads(self) -> dict[int, int]:
        return self._first.fail_reads

    @fail_reads.setter
    def fail_reads(self, value: dict[int, int]) -> None:
        self._first.fail_reads = value

    def monitor(self, device_name: str) -> FakeMonitor:
        """The attached FakeMonitor with that device name (KeyError if none)."""
        for monitor in self.fake_monitors:
            if monitor.device_name == device_name:
                return monitor
        raise KeyError(device_name)

    def _attached(self, device_name: str) -> FakeMonitor:
        try:
            return self.monitor(device_name)
        except KeyError:
            raise DdcError(f"display {device_name} is no longer attached") from None

    # -- port -----------------------------------------------------------

    def list_monitors(self) -> list[MonitorInfo]:
        return self.monitors

    def _read_vcp_on(self, device_name: str, code: int) -> tuple[int, int]:
        self.reads.append((device_name, code))
        monitor = self._attached(device_name)
        remaining = monitor.fail_reads.get(code, 0)
        if remaining > 0:
            monitor.fail_reads[code] = remaining - 1
            raise DdcError(f"simulated read failure for VCP 0x{code:02X}")
        if code not in monitor.registers:
            raise DdcError(f"unknown VCP code 0x{code:02X}")
        return monitor.registers[code]

    def _write_vcp_on(self, device_name: str, code: int, value: int) -> None:
        monitor = self._attached(device_name)
        if monitor.write_error is not None:
            raise DdcError(f"SetVCPFeature failed for VCP 0x{code:02X}", monitor.write_error)
        self.writes.append((code, value))
        monitor.writes.append((code, value))
        _, existing_max = monitor.registers.get(code, (value, value))
        monitor.registers[code] = (value, existing_max)
