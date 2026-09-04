"""The MoonHalo model: remembered state, DDC writes, and the state -> API
conversions the HTTP layer serialises.

VCP register D7 (power) is always written in 360 degree mode. VCP register
D9 packs brightness and colour temperature into one 16-bit value, high byte
colour step (1-7) and low byte brightness step (1-10); every D9 write sends
both halves, using the remembered value for whichever half is not changing.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from .config import Config
from .ddc import DdcError, DdcPort, MonitorInfo

_logger = logging.getLogger(__name__)

#: VCP register for MoonHalo power.
VCP_POWER = 0xD7
#: D7 value that turns the MoonHalo on in 360 degree mode.
POWER_ON_VALUE = 0x0220
#: D7 value that turns the MoonHalo off (360 degree mode bit still set).
POWER_OFF_VALUE = 0x0210
#: VCP register shared by MoonHalo brightness and colour temperature (packed
#: scheme): high byte colour step 1-7, low byte brightness step 1-10.
VCP_D9 = 0xD9


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


def colortemp_step_to_kelvin(
    step: int, kelvin_min: int, kelvin_max: int, invert: bool = False
) -> int:
    """Centre Kelvin of colour step `step` (1-7, 1 warmest) when
    `kelvin_min..kelvin_max` is divided into seven equal bands. With
    `invert`, the step is flipped (`8 - step`) before the band is looked
    up, so this stays the inverse of `kelvin_to_colortemp_step` called
    with the same `invert`.
    """
    if not 1 <= step <= 7:
        raise ValueError(f"colour step must be 1-7, got {step}")
    effective_step = 8 - step if invert else step
    band_width = (kelvin_max - kelvin_min) / 7
    centre = kelvin_min + band_width * (effective_step - 1) + band_width / 2
    return round(centre)


def kelvin_to_colortemp_step(
    kelvin: int, kelvin_min: int, kelvin_max: int, invert: bool = False
) -> int:
    """Map a Kelvin value to the hardware colour step (1-7, 1 warmest) whose
    band it falls in, dividing `kelvin_min..kelvin_max` into seven equal
    bands. `kelvin` is clamped into the range first, so anything at or
    below `kelvin_min` is step 1 and anything at or above `kelvin_max` is
    step 7; this never returns 0 or 8. With `invert`, the step is flipped
    (`8 - step`) after the band lookup, so `colortemp_step_to_kelvin(step,
    ..., invert=invert)` maps back into the same band for every step 1-7.
    """
    clamped = max(kelvin_min, min(kelvin_max, kelvin))
    band_width = (kelvin_max - kelvin_min) / 7
    if band_width <= 0:
        step = 1
    else:
        step = int((clamped - kelvin_min) / band_width) + 1
        step = max(1, min(7, step))
    return 8 - step if invert else step


def level_to_brightness_step(level: int) -> int:
    """Map Level 1-100 to hardware brightness step 1-10: round(1 + (level -
    1) * 9 / 99), so 1 -> 1, 50 -> 5, 100 -> 10."""
    return round(1 + (level - 1) * 9 / 99)


def brightness_step_to_level(step: int) -> int:
    """Map hardware brightness step 1-10 back to Level 1-100: round((step -
    1) * 99 / 9 + 1), the inverse of `level_to_brightness_step`."""
    return round((step - 1) * 99 / 9 + 1)


def pack_d9(colortemp_step: int, brightness_step: int) -> int:
    """Pack VCP D9's 16-bit value: colour step (1-7) in the high byte,
    brightness step (1-10) in the low byte."""
    return ((colortemp_step & 0xFF) << 8) | (brightness_step & 0xFF)


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
        #: The VCP writes the most recently completed call actually
        #: performed, in order, for the HTTP layer to log accurately.
        self.last_writes: list[tuple[int, int]] = []

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
        """Resolve the level to apply -- `level` if given, else the
        remembered last level, else the configured default -- and apply it
        exactly as `set_level` would: D7 On (if not already on) followed by
        a D9 write, so `/moonhalo/on` writes power then brightness."""
        with self._lock:
            resolved_level = (
                level
                if level is not None
                else (
                    self._state.last_level
                    if self._state.last_level is not None
                    else self._config.default_on_level
                )
            )
            return self._apply_level_locked(resolved_level)

    def turn_off(self) -> dict[str, Any]:
        """Write D7 off (360 degree mode bit preserved) and remember power
        "off". The remembered `last_level` and D9 steps are left untouched."""
        with self._lock:
            self._port.write_vcp(VCP_POWER, POWER_OFF_VALUE)
            self.last_writes = [(VCP_POWER, POWER_OFF_VALUE)]
            self._state.power = "off"
            self._save_state()
            return self._status_locked()

    def set_level(self, level: int) -> dict[str, Any]:
        """Set MoonHalo brightness to `level` (0-100). Level 0 delegates to
        `turn_off`. Otherwise, powers on first if not already on, then
        writes D9 with the new brightness step and the colour step to keep
        (see `_resolve_colortemp_step_locked`), remembering both steps and
        `last_level`."""
        if level == 0:
            return self.turn_off()
        with self._lock:
            return self._apply_level_locked(level)

    def _apply_level_locked(self, level: int) -> dict[str, Any]:
        """Shared body of `turn_on` and `set_level` once a concrete level
        1-100 is known. Caller holds `self._lock`."""
        writes: list[tuple[int, int]] = []
        self._ensure_power_on_locked(writes)

        brightness_step = level_to_brightness_step(level)
        colortemp_step = self._resolve_colortemp_step_locked()
        d9_value = pack_d9(colortemp_step, brightness_step)
        self._port.write_vcp(VCP_D9, d9_value)
        writes.append((VCP_D9, d9_value))

        self._state.brightness_step = brightness_step
        self._state.colortemp_step = colortemp_step
        self._state.last_level = level
        self.last_writes = writes
        self._save_state()
        return self._status_locked()

    def set_colortemp(self, step: int, stage: bool = False) -> dict[str, Any]:
        """Set MoonHalo colour temperature to hardware step `step` (1-7).

        If `stage` is true, only the remembered `colortemp_step` changes:
        no DDC writes happen and the halo's power is untouched. Otherwise,
        powers on first if not already on, then writes D9 with `step` and
        the brightness step to keep (see `_resolve_brightness_step_locked`),
        remembering both steps. If `last_level` was not yet known, it is
        derived from the brightness step kept.
        """
        with self._lock:
            if stage:
                self._state.colortemp_step = step
                self.last_writes = []
                self._save_state()
                return self._status_locked()

            writes: list[tuple[int, int]] = []
            self._ensure_power_on_locked(writes)

            brightness_step = self._resolve_brightness_step_locked()
            d9_value = pack_d9(step, brightness_step)
            self._port.write_vcp(VCP_D9, d9_value)
            writes.append((VCP_D9, d9_value))

            self._state.colortemp_step = step
            self._state.brightness_step = brightness_step
            if self._state.last_level is None:
                self._state.last_level = brightness_step_to_level(brightness_step)
            self.last_writes = writes
            self._save_state()
            return self._status_locked()

    def _ensure_power_on_locked(self, writes: list[tuple[int, int]]) -> None:
        """Write D7 On and remember power "on" if not already on, appending
        the write to `writes`. Caller holds `self._lock`."""
        if self._state.power != "on":
            self._port.write_vcp(VCP_POWER, POWER_ON_VALUE)
            writes.append((VCP_POWER, POWER_ON_VALUE))
            self._state.power = "on"

    def _resolve_colortemp_step_locked(self) -> int:
        """The colour step to keep when writing D9 for a brightness-only
        change: the remembered step, else read from the monitor (see
        `_resolve_d9_half_locked`)."""
        return self._resolve_d9_half_locked(
            self._state.colortemp_step,
            is_high_byte=True,
            value_max=7,
            default=self._config.default_colortemp_step,
            label="colour step",
        )

    def _resolve_brightness_step_locked(self) -> int:
        """The brightness step to keep when writing D9 for a colour-only
        change: the remembered step, else read from the monitor (see
        `_resolve_d9_half_locked`)."""
        return self._resolve_d9_half_locked(
            self._state.brightness_step,
            is_high_byte=False,
            value_max=10,
            default=self._config.default_brightness_step,
            label="brightness step",
        )

    def _resolve_d9_half_locked(
        self,
        remembered: Optional[int],
        *,
        is_high_byte: bool,
        value_max: int,
        default: int,
        label: str,
    ) -> int:
        """The value to keep for one half of D9 (colour step in the high
        byte, brightness step in the low byte) when the other half is
        being written: `remembered` if not None; else the relevant byte of
        a fresh D9 read (clamped to `1..value_max`, or `default` if that
        byte is 0, i.e. unknown); else, if the read fails after retries,
        `default` (with a warning logged, naming the half by `label`)."""
        if remembered is not None:
            return remembered
        try:
            current, _maximum = self._port.read_vcp(VCP_D9)
        except DdcError as error:
            _logger.warning(
                "D9 read failed after retries (%s); using default %s %d",
                error,
                label,
                default,
            )
            return default
        raw_byte = (current >> 8) & 0xFF if is_high_byte else current & 0xFF
        if raw_byte == 0:
            return default
        return max(1, min(value_max, raw_byte))

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
                colortemp_step,
                self._config.kelvin_min,
                self._config.kelvin_max,
                self._config.invert_colortemp,
            ),
            "monitor": self._monitor_description,
        }
