"""DDC/CI port abstraction: list monitors, pick the MoonHalo monitor, read
and write VCP registers.

This module defines the `DdcPort` interface plus two implementations:
`WindowsDdcPort`, which drives the real monitor through the Windows Monitor
Configuration API (dxva2.dll / user32.dll via ctypes), and `FakeDdcPort`,
an in-memory stand-in used by tests and `--dry-run`.

Which monitor a read or write goes to is decided here, once per display
set (issue #40). With `monitor_selector` set, the first monitor whose
device name or description contains it (case-insensitive) is the target,
as in 0.0.7. With no selector the target is *detected* by identity: each
attached monitor's DDC/CI capabilities string is read and the one whose
`model(...)` contains `monitor_model` (default "RD280UG") wins. If the
capabilities read fails on every monitor, the D9 probe decides instead:
the monitor whose D9 read (the MoonHalo's own register) returns a non-zero
maximum. Two model matches are broken the same way; still ambiguous, the
first is taken with one warning. A model match is sanity-checked with one
D9 read, warning if it fails or its maximum is zero; the match stands.

Why: on 2026-09-16 a second monitor (PD2700U) became the Windows primary
display and carried the same "Generic PnP Monitor" description as the
RD280UG. Selecting the primary sent every write to the wrong monitor,
which acknowledged them, so every link read healthy while the halo did
nothing. A description is no handle and a device name (`\\\\.\\DISPLAY1`)
names a port that a cable move can renumber; the capabilities string is
the only thing that says what the monitor is.

The result is cached against the set of attached device names: the ports
enumerate on every call anyway, so a cable swap while running is noticed
on the next command and detection runs again. A miss (no monitor found,
or a selector that matches nothing) is kept for `MISS_RETRY_SECONDS`
while the display set stays the same, then tried again: on 2026-09-16
each miss cost 2.8 s (the PD2700U's capabilities read), and detecting on
every call made a Ramp's writes and the command queued behind them take
longer than the Driver's 5 s request timeout, so the Bridge link flapped
offline. A cable change still detects at once. Nothing is chosen
silently: a miss raises `DdcError` with the models seen, which is how the
Monitor link reports it.

Windows-only bindings are created lazily, inside `WindowsDdcPort.__init__`,
so this module can be imported on any OS.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Optional, TypeVar, Union

from .capabilities import parse_segment

T = TypeVar("T")

_logger = logging.getLogger(__name__)

#: Total read attempts (the original try plus retries) before giving up.
DEFAULT_READ_RETRIES = 3
#: Pause between read attempts, in seconds.
DEFAULT_READ_RETRY_DELAY = 0.05
#: The `model(...)` the Bridge looks for when no selector is set (issue #40).
DEFAULT_MONITOR_MODEL = "RD280UG"
#: The register the D9 probe reads: the MoonHalo's own, which only the
#: RD280UG answers with a non-zero maximum (0x070A; the PD2700U gives 0).
PROBE_VCP = 0xD9
#: How long a miss stands for an unchanged display set before detection
#: is tried again (see the module docstring).
MISS_RETRY_SECONDS = 30.0
#: What `target_label` (and so `state.monitor`) reads before any
#: resolution and after a miss.
UNKNOWN_LABEL = "unknown"
#: What a bare `FakeDdcPort()` advertises, so it is detected by model like
#: the real monitor; `cli.DRY_RUN_CAPABILITIES` is the RD280UG's full string.
DEFAULT_FAKE_CAPABILITIES = "(prot(monitor)type(LCD)model(RD280UG)vcp(D7 D9))"


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


@dataclass(frozen=True)
class Detection:
    """The outcome of picking the target monitor (see the module docstring).

    device_name: the chosen monitor's device name; None when none was chosen.
    label: what `state.monitor` reports: `"<model> on <device name>"` for a
        detected monitor, `"<description> on <device name>"` for a selector
        match, `UNKNOWN_LABEL` when none was chosen.
    rule: how it was chosen: "selector", "model", "d9-probe", "tie-break",
        "first-of-ambiguous", or "none".
    seen: the attached device names at the time, sorted -- the display set
        a later call compares against to decide whether to resolve again.
    error: why nothing was chosen; None when something was.
    candidates: every monitor detection looked at, as `"<model> (<device
        name>)"` (`no model` or `unreadable` in place of a model); empty
        for a selector match.
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
    fails. Shared by every retried read -- VCP reads and capabilities
    reads alike -- so the retry behaviour can be exercised through
    `FakeDdcPort` in tests. Generic in the return type so it serves both
    `read_vcp` (`tuple[int, int]`) and `read_capabilities` (`str`).
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


@dataclass
class _Candidate:
    """One attached monitor as detection sees it."""

    info: MonitorInfo
    #: The `model(...)` from its capabilities; None when the string has no
    #: model segment (or cannot be parsed).
    model: Optional[str] = None
    #: False when every capabilities attempt failed.
    readable: bool = True
    #: D9's maximum from the probe; None when unread or the read failed.
    d9_maximum: Optional[int] = None

    @property
    def device_name(self) -> str:
        return self.info.device_name

    def describe(self) -> str:
        """`RD280UG (\\\\.\\DISPLAY1)`, `no model (...)` or `unreadable (...)`."""
        if not self.readable:
            what = "unreadable"
        elif self.model is None:
            what = "no model"
        else:
            what = self.model
        return f"{what} ({self.device_name})"


class DdcPort(ABC):
    """Port to a monitor's DDC/CI interface.

    Subclasses provide `list_monitors` and the per-device primitives
    (`_read_vcp_on`, `_write_vcp_on`, `_read_capabilities_on`); the public
    `read_vcp`, `write_vcp` and `read_capabilities` resolve the target
    monitor here first (see the module docstring), retrying reads.
    """

    def __init__(
        self,
        monitor_selector: Optional[str] = None,
        monitor_model: str = DEFAULT_MONITOR_MODEL,
        retries: int = DEFAULT_READ_RETRIES,
        retry_delay: float = DEFAULT_READ_RETRY_DELAY,
        logger: Optional[logging.Logger] = None,
    ):
        self.monitor_selector = monitor_selector
        self.monitor_model = monitor_model
        self._retries = retries
        self._retry_delay = retry_delay
        #: Where detection lines go: `serve` passes the Bridge's file
        #: logger so they land in `bridge.log`; the CLI a stderr logger.
        self._logger = logger if logger is not None else _logger
        self._detection: Optional[Detection] = None
        #: `time.monotonic` at the last resolution; tests replace `_clock`.
        self._clock: Callable[[], float] = time.monotonic
        self._resolved_at: float = 0.0

    # -- interface -------------------------------------------------------

    @abstractmethod
    def list_monitors(self) -> list[MonitorInfo]:
        """Return every physical monitor attached to the system."""

    @abstractmethod
    def _read_vcp_on(self, device_name: str, code: int) -> tuple[int, int]:
        """One attempt at `(current, maximum)` for `code` on that display."""

    @abstractmethod
    def _write_vcp_on(self, device_name: str, code: int, value: int) -> None:
        """Write `value` to `code` on that display."""

    @abstractmethod
    def _read_capabilities_on(self, device_name: str) -> str:
        """One attempt at the raw capabilities string of that display."""

    # -- the target monitor ------------------------------------------------

    @property
    def detection(self) -> Optional[Detection]:
        """The last resolution, or None before the first."""
        return self._detection

    @property
    def target_label(self) -> str:
        """`"<model> on <device name>"` for the current target, or
        `UNKNOWN_LABEL` before the first resolution or after a miss. What
        the model reports as `state.monitor`."""
        return self._detection.label if self._detection is not None else UNKNOWN_LABEL

    def resolve_target(self) -> Detection:
        """Resolve the target monitor for the attached display set, reusing
        the last result while the set of device names is unchanged and it
        found something. Never raises for a miss: the returned Detection
        says so (and the port calls raise from it)."""
        monitors = self.list_monitors()
        seen = tuple(sorted({monitor.device_name for monitor in monitors}))
        cached = self._detection
        if cached is not None and cached.seen == seen:
            if cached.found or self._clock() - self._resolved_at < MISS_RETRY_SECONDS:
                return cached
        if not monitors:
            detection = Detection(None, UNKNOWN_LABEL, "none", seen, "No display monitors found")
        elif self.monitor_selector:
            detection = self._select(monitors, seen)
        else:
            detection = self._detect(monitors, seen)
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
        else:
            self._logger.warning("monitor not found: %s", detection.error)
        self._detection = detection
        self._resolved_at = self._clock()
        return detection

    def _target_device(self) -> str:
        detection = self.resolve_target()
        if not detection.found:
            assert detection.error is not None
            raise DdcError(detection.error)
        assert detection.device_name is not None
        return detection.device_name

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
        """Detection by identity: model first, the D9 probe as fallback
        and tie-breaker (see the module docstring)."""
        candidates = self._read_models(monitors)
        needle = self.monitor_model.lower()
        matches = [c for c in candidates if c.model is not None and needle in c.model.lower()]

        if not any(c.readable for c in candidates):
            answering = self._probe(candidates)
            if not answering:
                names = ", ".join(c.device_name for c in candidates)
                return Detection(
                    None,
                    UNKNOWN_LABEL,
                    "none",
                    seen,
                    f"no monitor with model {self.monitor_model}: capabilities unreadable on "
                    f"{names} and the D9 probe answered on none",
                    candidates=tuple(c.describe() for c in candidates),
                )
            return self._choose(
                answering,
                "d9-probe",
                candidates,
                seen,
                "answer the D9 probe (capabilities unreadable on every monitor)",
            )

        if len(matches) == 1:
            chosen = matches[0]
            self._sanity_check(chosen)
            return self._choose([chosen], "model", candidates, seen, "")

        if len(matches) > 1:
            answering = self._probe(matches)
            if answering:
                how = f"match model {self.monitor_model} and answer the D9 probe"
            else:
                how = f"match model {self.monitor_model} and none answers the D9 probe"
            return self._choose(answering or matches, "tie-break", candidates, seen, how)

        described = tuple(c.describe() for c in candidates)
        return Detection(
            None,
            UNKNOWN_LABEL,
            "none",
            seen,
            f"no monitor with model {self.monitor_model} among: {', '.join(described)}",
            candidates=described,
        )

    def _read_models(self, monitors: list[MonitorInfo]) -> list[_Candidate]:
        """One candidate per device name, with its model read from its
        capabilities (three attempts, like every read)."""
        candidates: list[_Candidate] = []
        for monitor in monitors:
            if any(c.device_name == monitor.device_name for c in candidates):
                continue
            candidate = _Candidate(monitor)
            try:
                raw = _read_with_retries(
                    lambda: self._read_capabilities_on(monitor.device_name),
                    self._retries,
                    self._retry_delay,
                )
            except DdcError:
                candidate.readable = False
            else:
                try:
                    candidate.model = parse_segment(raw, "model")
                except ValueError:
                    candidate.model = None
            candidates.append(candidate)
        return candidates

    def _read_d9_maximum(self, candidate: _Candidate) -> Optional[DdcError]:
        """One retried D9 read on that candidate, recording its maximum in
        `d9_maximum`; returns the error when every attempt failed (the
        maximum then stays None), else None."""
        try:
            _, maximum = _read_with_retries(
                lambda: self._read_vcp_on(candidate.device_name, PROBE_VCP),
                self._retries,
                self._retry_delay,
            )
        except DdcError as error:
            return error
        candidate.d9_maximum = maximum
        return None

    def _probe(self, candidates: list[_Candidate]) -> list[_Candidate]:
        """The D9 probe: those candidates whose D9 read returns a non-zero
        maximum. A failed read counts as no."""
        answering: list[_Candidate] = []
        for candidate in candidates:
            if self._read_d9_maximum(candidate) is None and candidate.d9_maximum:
                answering.append(candidate)
        return answering

    def _sanity_check(self, chosen: _Candidate) -> None:
        """After a model match, one D9 read: warn if it fails or its
        maximum is zero (model matched, halo register did not answer)."""
        error = self._read_d9_maximum(chosen)
        if error is not None:
            self._logger.warning(
                "model %s matched on %s but its D9 read failed: %s",
                chosen.model,
                chosen.device_name,
                error,
            )
            return
        if chosen.d9_maximum == 0:
            self._logger.warning(
                "model %s matched on %s but its D9 maximum is zero",
                chosen.model,
                chosen.device_name,
            )

    def _choose(
        self,
        chosen: list[_Candidate],
        rule: str,
        candidates: list[_Candidate],
        seen: tuple[str, ...],
        how: str,
    ) -> Detection:
        """Take the first of `chosen`, warning when there was more than
        one; `how` says what the several have in common, for that warning."""
        if len(chosen) > 1:
            rule = "first-of-ambiguous"
            self._logger.warning(
                "%d monitors %s, taking the first: %s",
                len(chosen),
                how,
                ", ".join(c.describe() for c in chosen),
            )
        winner = chosen[0]
        model = winner.model if winner.model is not None else self.monitor_model
        return Detection(
            winner.device_name,
            f"{model} on {winner.device_name}",
            rule,
            seen,
            candidates=tuple(c.describe() for c in candidates),
        )

    # -- reads and writes ------------------------------------------------

    def read_vcp(self, code: int) -> tuple[int, int]:
        """Return `(current, maximum)` for the given VCP feature code on
        the target monitor, retrying a transient failure."""
        device = self._target_device()
        return _read_with_retries(
            lambda: self._read_vcp_on(device, code), self._retries, self._retry_delay
        )

    def write_vcp(self, code: int, value: int) -> None:
        """Write `value` to the given VCP feature code on the target monitor."""
        self._write_vcp_on(self._target_device(), code, value)

    def read_capabilities(self) -> str:
        """Return the target monitor's raw DDC/CI capabilities string,
        retrying a transient failure.

        Microsoft documents both underlying calls as "usually returns
        quickly, but sometimes it can take several seconds to complete";
        issue #28 saw the first `GetCapabilitiesStringLength` call on the
        RD280UG fail with `GetLastError()` -1071241845, with the retry
        50ms later succeeding. So this goes through the same three-attempt
        retry as `read_vcp`.
        """
        device = self._target_device()
        return _read_with_retries(
            lambda: self._read_capabilities_on(device), self._retries, self._retry_delay
        )


class WindowsDdcPort(DdcPort):
    """Real DDC/CI port using the Windows Monitor Configuration API.

    Opens a physical monitor handle for each operation and destroys it
    with `DestroyPhysicalMonitors` afterwards. Which display the handle is
    opened on is the target resolved by `DdcPort` (selector or detection).
    """

    def __init__(
        self,
        monitor_selector: Optional[str] = None,
        monitor_model: str = DEFAULT_MONITOR_MODEL,
        retries: int = DEFAULT_READ_RETRIES,
        retry_delay: float = DEFAULT_READ_RETRY_DELAY,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(monitor_selector, monitor_model, retries, retry_delay, logger)
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
        self._dxva2.GetCapabilitiesStringLength.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._dxva2.CapabilitiesRequestAndCapabilitiesReply.argtypes = [
            wintypes.HANDLE,
            ctypes.c_char_p,
            wintypes.DWORD,
        ]

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

    # -- capabilities -----------------------------------------------------

    def _read_capabilities_on(self, device_name: str) -> str:
        """`GetCapabilitiesStringLength` then
        `CapabilitiesRequestAndCapabilitiesReply` on that display."""
        ctypes = self._ctypes
        wintypes = self._wintypes
        arr = self._open_physical_monitor(device_name)
        try:
            handle = arr[0].hPhysicalMonitor
            length = wintypes.DWORD()
            if not self._dxva2.GetCapabilitiesStringLength(handle, ctypes.byref(length)):
                raise DdcError("GetCapabilitiesStringLength failed", ctypes.get_last_error())
            buffer = ctypes.create_string_buffer(length.value)
            if not self._dxva2.CapabilitiesRequestAndCapabilitiesReply(handle, buffer, length.value):
                raise DdcError(
                    "CapabilitiesRequestAndCapabilitiesReply failed", ctypes.get_last_error()
                )
            # buffer.value stops at the first NUL, so the trailing
            # terminator counted in `length` is already gone here.
            return buffer.value.decode("latin-1")
        finally:
            self._destroy(arr)


@dataclass
class FakeMonitor:
    """One monitor of a `FakeDdcPort`: its identity plus its own
    capabilities string, registers, scripted failures and writes.

    `registers` maps VCP code -> `(current, maximum)`; a write updates it
    (preserving the maximum) so a following read reflects it. `fail_reads`
    maps VCP code -> a count of scripted read failures still owed; each
    read of that code consumes one before falling through to `registers`,
    which is how tests exercise the retry path without hardware.
    `fail_capabilities` is the same counter for capabilities reads.
    `writes` records this monitor's `(code, value)` writes in order.
    """

    info: MonitorInfo
    registers: dict[int, tuple[int, int]] = field(default_factory=dict)
    capabilities: str = DEFAULT_FAKE_CAPABILITIES
    fail_reads: dict[int, int] = field(default_factory=dict)
    fail_capabilities: int = 0
    writes: list[tuple[int, int]] = field(default_factory=list)

    @property
    def device_name(self) -> str:
        return self.info.device_name


class FakeDdcPort(DdcPort):
    """In-memory DDC port for tests and `--dry-run`.

    `monitors` lists the attached monitors as `FakeMonitor`s, or as
    `MonitorInfo`s that all get a copy of `registers` and `capabilities`;
    the default is one primary "Generic PnP Monitor" that answers as the
    RD280UG. `fake_monitors` is that list, editable between calls to stand
    for a cable swap. `writes` records every `write_vcp` call port-wide as
    `(code, value)`, in the order made; `monitor(device_name).writes` has
    the ones that reached each monitor.

    `registers`, `capabilities`, `fail_reads` and `fail_capabilities` are
    those of the first listed monitor, which is what a one-monitor test
    means by "the monitor".
    """

    def __init__(
        self,
        monitors: Optional[list[Union[MonitorInfo, FakeMonitor]]] = None,
        registers: Optional[dict[int, tuple[int, int]]] = None,
        retries: int = DEFAULT_READ_RETRIES,
        retry_delay: float = 0.0,
        capabilities: str = DEFAULT_FAKE_CAPABILITIES,
        monitor_selector: Optional[str] = None,
        monitor_model: str = DEFAULT_MONITOR_MODEL,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(monitor_selector, monitor_model, retries, retry_delay, logger)
        if monitors is None:
            monitors = [
                MonitorInfo(device_name="DRYRUN1", primary=True, description="Generic PnP Monitor"),
            ]
        self.fake_monitors: list[FakeMonitor] = [
            entry
            if isinstance(entry, FakeMonitor)
            else FakeMonitor(entry, registers=dict(registers) if registers else {}, capabilities=capabilities)
            for entry in monitors
        ]
        self.writes: list[tuple[int, int]] = []

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

    @property
    def capabilities(self) -> str:
        return self._first.capabilities

    @capabilities.setter
    def capabilities(self, value: str) -> None:
        self._first.capabilities = value

    @property
    def fail_capabilities(self) -> int:
        return self._first.fail_capabilities

    @fail_capabilities.setter
    def fail_capabilities(self, value: int) -> None:
        self._first.fail_capabilities = value

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
        self.writes.append((code, value))
        monitor.writes.append((code, value))
        _, existing_max = monitor.registers.get(code, (value, value))
        monitor.registers[code] = (value, existing_max)

    def _read_capabilities_on(self, device_name: str) -> str:
        monitor = self._attached(device_name)
        if monitor.fail_capabilities > 0:
            monitor.fail_capabilities -= 1
            raise DdcError("simulated capabilities read failure")
        return monitor.capabilities
