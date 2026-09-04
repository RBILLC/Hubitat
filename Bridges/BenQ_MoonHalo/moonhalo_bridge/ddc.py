"""DDC/CI port abstraction: list monitors, read and write VCP registers.

This module defines the `DdcPort` interface plus two implementations:
`WindowsDdcPort`, which drives the real monitor through the Windows Monitor
Configuration API (dxva2.dll / user32.dll via ctypes), and `FakeDdcPort`,
an in-memory stand-in used by tests and `--dry-run`.

Windows-only bindings are created lazily, inside `WindowsDdcPort.__init__`,
so this module can be imported on any OS.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional

#: Total read attempts (the original try plus retries) before giving up.
DEFAULT_READ_RETRIES = 3
#: Pause between read attempts, in seconds.
DEFAULT_READ_RETRY_DELAY = 0.05


@dataclass(frozen=True)
class MonitorInfo:
    """One physical monitor attached to the system.

    device_name: the GDI device name of the parent display (e.g. ``\\\\.\\DISPLAY1``).
    primary: True if the parent display is the Windows primary monitor.
    description: the physical monitor's DDC/CI description string.
    """

    device_name: str
    primary: bool
    description: str


class DdcError(Exception):
    """A DDC/CI operation failed.

    `win32_error` carries the value of `GetLastError()` when the failure
    came from a Win32 call, or `None` for errors raised without one (for
    example an unknown VCP code on `FakeDdcPort`).
    """

    def __init__(self, message: str, win32_error: Optional[int] = None):
        self.win32_error = win32_error
        if win32_error is not None:
            message = f"{message} (Win32 error {win32_error})"
        super().__init__(message)


class DdcPort(ABC):
    """Port to a monitor's DDC/CI interface."""

    @abstractmethod
    def list_monitors(self) -> list[MonitorInfo]:
        """Return every physical monitor attached to the system."""

    @abstractmethod
    def read_vcp(self, code: int) -> tuple[int, int]:
        """Return `(current, maximum)` for the given VCP feature code."""

    @abstractmethod
    def write_vcp(self, code: int, value: int) -> None:
        """Write `value` to the given VCP feature code."""


def _read_with_retries(
    read_once: Callable[[], tuple[int, int]],
    retries: int = DEFAULT_READ_RETRIES,
    delay: float = DEFAULT_READ_RETRY_DELAY,
) -> tuple[int, int]:
    """Call `read_once()` up to `retries` times, pausing `delay` seconds
    between attempts, and re-raise the last `DdcError` if every attempt
    fails. Shared by both port implementations so the retry behaviour can
    be exercised through `FakeDdcPort` in tests.
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


class WindowsDdcPort(DdcPort):
    """Real DDC/CI port using the Windows Monitor Configuration API.

    Opens a physical monitor handle for each operation and destroys it
    with `DestroyPhysicalMonitors` afterwards. `monitor_selector`, when
    given, matches a case-insensitive substring of a monitor's device name
    or physical monitor description; it is wired now and reserved for a
    later ticket. With no selector, the primary monitor is used.
    """

    def __init__(
        self,
        monitor_selector: Optional[str] = None,
        retries: int = DEFAULT_READ_RETRIES,
        retry_delay: float = DEFAULT_READ_RETRY_DELAY,
    ):
        self.monitor_selector = monitor_selector
        self._retries = retries
        self._retry_delay = retry_delay
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

        self._PHYSICAL_MONITOR = PHYSICAL_MONITOR
        self._MONITORINFOEXW = MONITORINFOEXW
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
                for pm in arr:
                    result.append(
                        MonitorInfo(
                            device_name=device_name,
                            primary=primary,
                            description=pm.szPhysicalMonitorDescription,
                        )
                    )
            finally:
                self._destroy(arr)
        return result

    def _select_physical_monitor(self):
        """Return the PHYSICAL_MONITOR array holding the selected monitor
        (index 0 is the target); the caller destroys it after use. Arrays
        for every monitor not selected are destroyed here."""
        records = []  # (hmon, device_name, primary, arr)
        for hmon in self._enum_hmonitors():
            device_name, primary = self._monitor_info(hmon)
            arr = self._physical_monitors(hmon)
            records.append((hmon, device_name, primary, arr))

        if not records:
            raise DdcError("No display monitors found")

        selected = None
        if self.monitor_selector:
            needle = self.monitor_selector.lower()
            for record in records:
                _, device_name, _, arr = record
                if needle in device_name.lower() or any(
                    needle in pm.szPhysicalMonitorDescription.lower() for pm in arr
                ):
                    selected = record
                    break
        else:
            for record in records:
                if record[2]:  # primary flag
                    selected = record
                    break

        if selected is None:
            selected = records[0]

        for record in records:
            if record is not selected:
                self._destroy(record[3])

        arr = selected[3]
        if len(arr) == 0:
            raise DdcError("Selected monitor has no physical monitor handle")
        return arr

    # -- VCP ------------------------------------------------------------

    def read_vcp(self, code: int) -> tuple[int, int]:
        return _read_with_retries(lambda: self._read_vcp_once(code), self._retries, self._retry_delay)

    def _read_vcp_once(self, code: int) -> tuple[int, int]:
        ctypes = self._ctypes
        wintypes = self._wintypes
        arr = self._select_physical_monitor()
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

    def write_vcp(self, code: int, value: int) -> None:
        wintypes = self._wintypes
        arr = self._select_physical_monitor()
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


class FakeDdcPort(DdcPort):
    """In-memory DDC port for tests and `--dry-run`.

    `registers` maps VCP code -> `(current, maximum)`. `writes` records
    every `write_vcp` call as `(code, value)`, in the order made, and a
    write also updates `registers` so a following read reflects it
    (preserving the existing maximum). `fail_reads` maps VCP code -> a
    count of scripted read failures still owed; each read of that code
    consumes one before falling through to `registers`, which is how
    tests exercise the retry path without hardware.
    """

    def __init__(
        self,
        monitors: Optional[list[MonitorInfo]] = None,
        registers: Optional[dict[int, tuple[int, int]]] = None,
        retries: int = DEFAULT_READ_RETRIES,
        retry_delay: float = 0.0,
    ):
        self.monitors: list[MonitorInfo] = list(monitors) if monitors else [
            MonitorInfo(device_name="DRYRUN1", primary=True, description="Generic PnP Monitor"),
        ]
        self.registers: dict[int, tuple[int, int]] = dict(registers) if registers else {}
        self.writes: list[tuple[int, int]] = []
        self.fail_reads: dict[int, int] = {}
        self._retries = retries
        self._retry_delay = retry_delay

    def list_monitors(self) -> list[MonitorInfo]:
        return list(self.monitors)

    def read_vcp(self, code: int) -> tuple[int, int]:
        return _read_with_retries(lambda: self._read_vcp_once(code), self._retries, self._retry_delay)

    def _read_vcp_once(self, code: int) -> tuple[int, int]:
        remaining = self.fail_reads.get(code, 0)
        if remaining > 0:
            self.fail_reads[code] = remaining - 1
            raise DdcError(f"simulated read failure for VCP 0x{code:02X}")
        if code not in self.registers:
            raise DdcError(f"unknown VCP code 0x{code:02X}")
        return self.registers[code]

    def write_vcp(self, code: int, value: int) -> None:
        self.writes.append((code, value))
        _, existing_max = self.registers.get(code, (value, value))
        self.registers[code] = (value, existing_max)
