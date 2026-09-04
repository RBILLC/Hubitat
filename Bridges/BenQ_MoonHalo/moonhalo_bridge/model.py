"""The MoonHalo model: remembered state, DDC writes, and the state -> API
conversions the HTTP layer serialises.

This ticket writes only VCP register D7 (power), always in 360 degree mode.
Brightness and colour-temperature writes to D9 arrive in later tickets; the
model already remembers `brightness_step` and `colortemp_step` so those
tickets can build on this state without a format change.
"""
from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from .config import Config
from .ddc import DdcPort, MonitorInfo

#: VCP register for MoonHalo power.
VCP_POWER = 0xD7
#: D7 value that turns the MoonHalo on in 360 degree mode.
POWER_ON_VALUE = 0x0220
#: D7 value that turns the MoonHalo off (360 degree mode bit still set).
POWER_OFF_VALUE = 0x0210


@dataclass
class MoonHaloState:
    """Remembered MoonHalo state, persisted verbatim to the state file."""

    power: str = "unknown"  # "on" | "off" | "auto" | "unknown"
    brightness_step: Optional[int] = None  # 1-10
    colortemp_step: Optional[int] = None  # 1-7
    last_level: Optional[int] = None  # 1-100

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MoonHaloState":
        return cls(
            power=data.get("power", "unknown"),
            brightness_step=data.get("brightness_step"),
            colortemp_step=data.get("colortemp_step"),
            last_level=data.get("last_level"),
        )


def colortemp_step_to_kelvin(step: int, kelvin_min: int, kelvin_max: int) -> int:
    """Centre Kelvin of colour step `step` (1-7, 1 warmest) when
    `kelvin_min..kelvin_max` is divided into seven equal bands. A pure
    function so later tickets (Kelvin -> nearest step) can reuse the same
    band maths.
    """
    if not 1 <= step <= 7:
        raise ValueError(f"colour step must be 1-7, got {step}")
    band_width = (kelvin_max - kelvin_min) / 7
    centre = kelvin_min + band_width * (step - 1) + band_width / 2
    return round(centre)


def _select_monitor_description(monitors: list[MonitorInfo], selector: Optional[str]) -> str:
    """Pick the description of the selected monitor from an already-fetched
    `list_monitors()` result, mirroring `WindowsDdcPort`'s own selection
    rule: a case-insensitive substring match on `selector` if given, else
    the primary monitor, else the first monitor, else "unknown"."""
    if not monitors:
        return "unknown"
    if selector:
        needle = selector.lower()
        for monitor in monitors:
            if needle in monitor.device_name.lower() or needle in monitor.description.lower():
                return monitor.description
    for monitor in monitors:
        if monitor.primary:
            return monitor.description
    return monitors[0].description


class MoonHaloModel:
    """Owns remembered MoonHalo state, persists it to `config.state_file`,
    and performs the DDC writes for `turn_on` / `turn_off`. Every DDC port
    call is serialised behind one lock.
    """

    def __init__(self, port: DdcPort, config: Config):
        self._port = port
        self._config = config
        self._state_file = Path(config.state_file)
        self._lock = threading.Lock()
        self._state = self._load_state()
        self._monitor_description = self._load_monitor_description()

    def _load_monitor_description(self) -> str:
        try:
            monitors = self._port.list_monitors()
        except Exception:
            return "unknown"
        return _select_monitor_description(monitors, self._config.monitor_selector)

    def _load_state(self) -> MoonHaloState:
        if self._state_file.exists():
            try:
                with open(self._state_file, "r", encoding="utf-8") as handle:
                    return MoonHaloState.from_dict(json.load(handle))
            except (OSError, json.JSONDecodeError):
                return MoonHaloState()
        return MoonHaloState()

    def _save_state(self) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._state_file.with_name(self._state_file.name + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(self._state.to_dict(), handle)
        tmp_path.replace(self._state_file)

    def turn_on(self, level: Optional[int] = None) -> dict[str, Any]:
        """Write D7 on (360 degree mode) and remember power "on" and the
        resulting level: `level` if given, else the remembered last level,
        else the configured default."""
        with self._lock:
            self._port.write_vcp(VCP_POWER, POWER_ON_VALUE)
            resolved_level = (
                level
                if level is not None
                else (
                    self._state.last_level
                    if self._state.last_level is not None
                    else self._config.default_on_level
                )
            )
            self._state.power = "on"
            self._state.last_level = resolved_level
            self._save_state()
            return self._status_locked()

    def turn_off(self) -> dict[str, Any]:
        """Write D7 off (360 degree mode bit preserved) and remember power
        "off". The remembered `last_level` is left untouched."""
        with self._lock:
            self._port.write_vcp(VCP_POWER, POWER_OFF_VALUE)
            self._state.power = "off"
            self._save_state()
            return self._status_locked()

    def status(self) -> dict[str, Any]:
        """Return the remembered state; performs no DDC call."""
        with self._lock:
            return self._status_locked()

    def _status_locked(self) -> dict[str, Any]:
        if self._state.power == "off":
            level = 0
        else:
            level = (
                self._state.last_level
                if self._state.last_level is not None
                else self._config.default_on_level
            )
        brightness_step = (
            self._state.brightness_step
            if self._state.brightness_step is not None
            else self._config.default_brightness_step
        )
        colortemp_step = (
            self._state.colortemp_step
            if self._state.colortemp_step is not None
            else self._config.default_colortemp_step
        )
        return {
            "power": self._state.power,
            "level": level,
            "brightnessStep": brightness_step,
            "colorTempStep": colortemp_step,
            "colorTemperature": colortemp_step_to_kelvin(
                colortemp_step, self._config.kelvin_min, self._config.kelvin_max
            ),
            "monitor": self._monitor_description,
        }
