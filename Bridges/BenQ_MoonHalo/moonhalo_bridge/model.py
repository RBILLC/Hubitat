"""The MoonHalo model: remembered state, DDC writes, and the state -> API
conversions the HTTP layer serialises.

VCP register D7 (power) is always written in 360 degree mode. VCP register
D9 packs brightness and colour temperature into one 16-bit value, high byte
colour step (1-7) and low byte brightness step (1-10); every D9 write sends
both halves, using the remembered value for whichever half is not changing.

Two states matter here (see CONTEXT.md's glossary): the **Target state**
(`MoonHaloState`, persisted) is what was most recently commanded and what
every reply reports; the **Applied state** is what the monitor was last
actually written with, tracked as one hardware step per byte
(`_applied_colortemp_step`, `_applied_brightness_step`). A brightness or
colour change with a non-zero Transition schedules a **Ramp** -- a series
of D9 writes spreading the move from the Applied state to the Target one
across the Transition, both bytes moved together so a combined move
(brightness and colour changing at once) is one sequence of writes -- run
by one background worker thread owned by the model, so Target and Applied
can differ while a Ramp is in flight. A newer command retargets the plan
from wherever the Applied state currently is, rather than restarting it;
a command whose Target already matches a Ramp in flight leaves it alone.

A DDC/CI failure mid-Ramp does not fail the Hub's already-answered request
(see `_perform_ramp_write_locked`): an intermediate write is skipped, but
the final write gets one retry, and if that also fails the Applied state
becomes unknown (`_forget_applied_locked`) until the next Ramp reads D9 for
itself.

`turn_on` and `turn_off` (issue #35) share this Ramp machinery: a lit halo
(power "on", or mid dim-out -- see below) turning off with a non-zero
Transition gets a brightness-down Ramp to step 1 whose true final write is
D7 off, not another D9 write (`_RampPlan.power_off_after`; see
`_worker_loop` and `_perform_ramp_write_locked`'s `vcp_code` parameter). A
dark halo turning on (or taking a brightness/colour command) with a
non-zero Transition writes D9 at the target colour and brightness step 1,
then D7 on -- issue #29 showed a D9 write while off is applied and relights
the halo at the new value with no flash on the following D7 write -- and
then Ramps brightness up from there. `_halo_lit_locked` is what tells the
two ends of this apart from "off and dark": while a power_off_after Ramp
is still running, Target power already reads "off" but the halo is still
lit, so an on/brightness/colour command arriving mid dim-out must not
repeat the relight sequence (that would flash) -- it just retargets the
Ramp upward and D7 off is never written; the mirror case, an off arriving
mid ramp-up, retargets down to a fresh D7 off instead of restarting.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from .config import Config
from .ddc import DEFAULT_READ_RETRY_DELAY, DdcError, DdcPort, MonitorInfo

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
#: Measured cost of one SetVCPFeature write on this monitor (55-65ms, issue
#: #29): a Ramp never schedules writes closer together than this.
WRITE_FLOOR_SECONDS = 0.06


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


@dataclass(frozen=True)
class Transition:
    """The Transition the Bridge applied (or is applying) for a brightness reply:
    `seconds` is the Transition used, `steps` the number of D9 writes it
    takes (always 1 for an immediate change)."""

    seconds: float
    steps: int

    def to_dict(self) -> dict[str, Any]:
        return {"seconds": self.seconds, "steps": self.steps}


@dataclass
class _RampPlan:
    """A brightness/colour Ramp in flight, owned by the worker thread.

    `steps` is every write the Ramp makes, in order, each a `(due_at,
    colortemp_step, brightness_step)` triple with `due_at` a
    `time.monotonic()` deadline; `next_index` is the index of the next one
    not yet performed. `target_colortemp_step` and `target_brightness_step`
    are the Ramp's destination on each axis, for the completion/cancel log
    lines. `performed` records the writes actually made (a failed write is
    skipped, not recorded) for the completion log line.

    `power_off_after` (issue #35) marks a `turn_off` Ramp: once every step
    in `steps` is done (`next_index >= len(steps)`, possibly true from the
    start, with an empty `steps` list), the worker's next action is one
    D7 `POWER_OFF_VALUE` write -- the plan's true final write, not another
    D9 one, so none of `steps` is ever treated as final (see
    `_worker_loop`'s `is_final` and `_perform_ramp_write_locked`'s
    `vcp_code` parameter).
    """

    target_colortemp_step: int
    target_brightness_step: int
    transition_seconds: float
    steps: list[tuple[float, int, int]]
    start_time: float
    next_index: int = 0
    performed: list[tuple[int, int]] = field(default_factory=list)
    power_off_after: bool = False


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
    """Owns remembered Target state, persists it to `config.state_file`, and
    performs the DDC writes for `turn_on` / `turn_off` / `set_colortemp`,
    and (immediately, or via a background Ramp) `set_level`. Every DDC port
    call from the handler thread is serialised behind one lock; the Ramp
    worker thread takes the same lock only around each write it makes.
    """

    def __init__(self, port: DdcPort, config: Config, logger: Optional[logging.Logger] = None):
        self._port = port
        self._config = config
        #: Where the Ramp worker's completion and failure lines go. `serve`
        #: passes the Bridge's file logger so they land in `bridge.log`
        #: next to the request lines; tests leave the module logger.
        self._logger = logger if logger is not None else _logger
        self._state_file = Path(config.state_file)
        self._lock = threading.Lock()
        #: Shares `self._lock` so the worker can `wait()` on it (releasing
        #: the lock while asleep) and a new command can `notify_all()` it
        #: awake the moment a Ramp is planned, retargeted, or cancelled.
        self._condition = threading.Condition(self._lock)
        self._state = self._load_state()
        self._monitor_description = self._load_monitor_description()
        #: The VCP writes the most recently completed call actually
        #: performed *synchronously*, in order, for the HTTP layer to log
        #: accurately. A Ramp's writes happen later, on the worker thread,
        #: and are not added here (see `_RampPlan.performed`).
        self.last_writes: list[tuple[int, int]] = []
        #: The Transition the most recently completed call reported, for
        #: the HTTP layer's brightness reply.
        self.last_transition: Transition = Transition(seconds=0.0, steps=1)
        #: Applied brightness/colour steps (see the module docstring): the
        #: Target's remembered step to start, resolved lazily (D9 read +
        #: default fallback) the first time either is needed and unknown --
        #: see `_resolve_applied_brightness_step_locked` and
        #: `_resolve_applied_colortemp_step_locked`.
        self._applied_brightness_step: Optional[int] = self._state.brightness_step
        self._applied_colortemp_step: Optional[int] = self._state.colortemp_step
        self._ramp_plan: Optional[_RampPlan] = None
        self._worker_thread: Optional[threading.Thread] = None

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

    def turn_on(self, level: Optional[int] = None, transition: Optional[float] = None) -> dict[str, Any]:
        """Resolve the level to apply -- `level` if given, else the
        remembered last level, else the configured default -- and reach it
        through the shared planner (`_plan_move_locked`), keeping the
        current Target colour step, exactly as `set_level` does (issue
        #35): when the halo is already on this behaves like a `set_level`
        to that level (the same-target-Ramp rule included, which is what
        keeps a Google Home setLevel-then-on pair from stuttering); when
        it is dark, `transition` decides between today's D7-then-D9 snap
        (0, the default `resolved_transition` when the caller wants an
        immediate change) and the D9-then-D7 relight-and-Ramp sequence
        (non-zero; see the module docstring)."""
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
            resolved_transition = self._resolve_transition(transition)
            return self._plan_move_locked(
                None,
                level_to_brightness_step(resolved_level),
                resolved_transition,
                last_level=resolved_level,
            )

    def turn_off(self, transition: Optional[float] = None) -> dict[str, Any]:
        """Turn the MoonHalo off over `transition` seconds (default
        `config.transition_seconds`); see CONTEXT.md's Transition/Ramp
        glossary and issue #35.

        Not lit right now (`_halo_lit_locked` false: Target power not
        "on", and no dim-out Ramp with `power_off_after` still in flight)
        -- including the very first call on a freshly loaded model, whose
        Target power is "unknown": write D7 off alone, a harmless re-sync,
        regardless of `transition`.

        Lit, with `transition` resolving to 0: cancel any Ramp and snap
        straight to D7 off, exactly as before #35.

        Otherwise (lit, non-zero transition): Target power becomes "off"
        at once -- `brightness_step`, `colortemp_step` and `last_level`
        are left untouched, so `status` already reports level 0 and a
        following `turn_on` restores the level -- and a Ramp is planned
        from the Applied state down to brightness step 1, holding the
        Applied colour step, with `power_off_after=True` so the worker's
        true final write is D7 off (see `_RampPlan`/`_worker_loop`); this
        is never collapsed to a synchronous write, even for a single D9
        write or none at all (`_plan_power_off_ramp_locked`). A Ramp
        already running -- up or down -- is replaced, continuing from
        wherever the Applied state currently is: this is how an off
        arriving mid ramp-up retargets into a ramp-down ending in D7 off.
        """
        with self._lock:
            resolved_transition = self._resolve_transition(transition)
            if not self._halo_lit_locked() or resolved_transition == 0:
                self._cancel_ramp_locked()
                return self._write_power_off_now_locked()

            self._cancel_ramp_locked()
            applied_colortemp_step = self._resolve_applied_colortemp_step_locked()
            applied_brightness_step = self._resolve_applied_brightness_step_locked()
            self._plan_power_off_ramp_locked(
                applied_colortemp_step, applied_brightness_step, resolved_transition
            )
            self._state.power = "off"
            self.last_writes = []
            self._save_state()
            self._condition.notify_all()
            return self._status_locked()

    def _resolve_transition(self, transition: Optional[float]) -> float:
        """The Transition a command runs with: the one it carried, else
        `config.transition_seconds`. An explicit 0 stays 0 (a snap)."""
        return self._config.transition_seconds if transition is None else transition

    def _halo_lit_locked(self) -> bool:
        """Whether the monitor is actually emitting light right now, as
        opposed to "off and dark" (issue #35): Target power "on", or
        Target power "off" while a dim-out Ramp (`power_off_after`) is
        still in flight -- D7 off has not been written yet, so the halo is
        still lit at whatever step that Ramp has reached. This is what
        lets an on/brightness/colour command arriving mid dim-out retarget
        upward without repeating the relight sequence (which would flash)
        or ever writing D7 off, and what lets `turn_off` tell a genuinely
        dark halo (skip the Ramp, just re-sync D7 off) apart from a lit
        one. Caller holds `self._lock`."""
        if self._state.power == "on":
            return True
        return self._ramp_plan is not None and self._ramp_plan.power_off_after

    def _write_power_off_now_locked(self) -> dict[str, Any]:
        """Write D7 off alone: the snap path for an already-dark halo (a
        harmless re-sync) and for a lit halo with an explicit `transition`
        of 0. No D9 write ever happens here, so the reply's Transition
        always reports zero steps. Caller holds `self._lock`."""
        self._port.write_vcp(VCP_POWER, POWER_OFF_VALUE)
        self.last_writes = [(VCP_POWER, POWER_OFF_VALUE)]
        self.last_transition = Transition(seconds=0.0, steps=0)
        self._state.power = "off"
        self._save_state()
        return self._status_locked()

    def set_level(self, level: int, transition: Optional[float] = None) -> dict[str, Any]:
        """Set MoonHalo brightness to `level` (0-100) over `transition`
        seconds (default `config.transition_seconds`). Level 0 delegates
        to `turn_off` with the same `transition` (issue #35: a Transition
        applies to dimming out too, not just to snapping off). Otherwise
        goes through the shared planner (see `_plan_move_locked`), keeping
        the current Target colour step, powering on first if not already
        on.
        """
        if level == 0:
            return self.turn_off(transition)
        with self._lock:
            resolved_transition = self._resolve_transition(transition)
            return self._plan_move_locked(
                None, level_to_brightness_step(level), resolved_transition, last_level=level
            )

    def _write_move_now_locked(
        self,
        colortemp_step: int,
        brightness_step: int,
        writes: list[tuple[int, int]],
        transition_seconds: float,
        last_level: Optional[int],
    ) -> dict[str, Any]:
        """Perform one synchronous D9 write to `(colortemp_step,
        brightness_step)`, used by `_plan_move_locked` when
        `transition_seconds` is 0, the move collapses to one write, or
        there is no delta on either axis. `writes` already holds any
        immediate D7 write (or, per issue #35, the D9-then-D7 relight
        pair a power-on-with-Transition sequence just made);
        `transition_seconds` is echoed back in `last_transition` even
        though only one write happens here. `last_level`, when given,
        replaces the remembered Level. Caller holds `self._lock`."""
        d9_value = pack_d9(colortemp_step, brightness_step)
        self._port.write_vcp(VCP_D9, d9_value)
        writes.append((VCP_D9, d9_value))

        self._applied_colortemp_step = colortemp_step
        self._applied_brightness_step = brightness_step
        self._state.colortemp_step = colortemp_step
        self._state.brightness_step = brightness_step
        if last_level is not None:
            self._state.last_level = last_level
        self.last_writes = writes
        self.last_transition = Transition(seconds=float(transition_seconds), steps=1)
        self._save_state()
        return self._status_locked()

    def _plan_move_locked(
        self,
        new_colortemp_step: Optional[int],
        new_brightness_step: Optional[int],
        transition_seconds: float,
        *,
        last_level: Optional[int] = None,
    ) -> dict[str, Any]:
        """Reach a new Target, given `transition_seconds`, either
        synchronously or by (re)planning a Ramp from the current Applied
        state. Shared by `turn_on`, `set_level` and `set_colortemp`.
        Caller holds `self._lock`.

        Exactly one of `new_colortemp_step` / `new_brightness_step` is the
        axis being commanded; the other is `None`, meaning "keep the
        current Target", resolved here the same way a colour- or
        brightness-only write always has (`_resolve_colortemp_step_locked`
        / `_resolve_brightness_step_locked`). `last_level`, given by
        `turn_on` and `set_level`, replaces the remembered Level outright;
        left `None` (by `set_colortemp`), the remembered Level is instead
        derived from the brightness step kept, the first time it is not
        yet known.

        - A command whose Target already equals a Ramp already in flight
          on *both* axes leaves that Ramp completely untouched: no new
          writes, and the reply reports the running Ramp's own Transition.
          (A command that changes either axis retargets the plan instead,
          and an explicit `transition_seconds` of 0 always snaps.)
        - Lit already (`_halo_lit_locked`, issue #35) -- genuinely on, or
          mid dim-out with D7 off not yet written -- retargets straight to
          "on" with no D7 write at all: repeating the relight sequence
          below would flash, and a genuinely-on halo needs no D7 write
          anyway.
        - Dark, with `transition_seconds == 0`: today's D7-then-D9 snap,
          unchanged since #29.
        - Dark, with a non-zero `transition_seconds` (issue #35): D9 is
          written at the target colour step and brightness step 1, then
          D7 on -- issue #29 showed a D9 write while off is applied and
          relights the halo at the new value with no flash on the
          following D7 write -- and the Applied state becomes exactly
          that (colour target, brightness 1), from which the Ramp below
          runs up to the full target. When the target brightness step is
          already 1 (turning on to the lowest level), that immediate D9
          write already reached the target: this returns at once,
          reporting the Transition as one step (the immediate write) with
          no further Ramp -- a second, identical D9 write would be a
          wasted DDC call.
        - `transition_seconds == 0`, or no delta on either axis, writes
          once, synchronously.
        - Otherwise a Ramp is planned from the current Applied state to
          the new Target: the step count is the larger of the two axes'
          deltas in hardware steps, both bytes spread evenly
          across it and rounded, dropping intermediate steps evenly so no
          write is scheduled closer than `WRITE_FLOOR_SECONDS` to the last
          -- so a Ramp already running is retargeted (continuing from
          wherever it has reached) rather than restarted, and a lone
          colour change or one landing mid-brightness-Ramp both become one
          combined sequence of D9 writes.
        """
        target_colortemp_step = (
            new_colortemp_step
            if new_colortemp_step is not None
            else self._resolve_colortemp_step_locked()
        )
        target_brightness_step = (
            new_brightness_step
            if new_brightness_step is not None
            else self._resolve_brightness_step_locked()
        )
        if last_level is None and self._state.last_level is None:
            last_level = brightness_step_to_level(target_brightness_step)

        if (
            self._ramp_plan is not None
            and not self._ramp_plan.power_off_after
            and target_colortemp_step == self._state.colortemp_step
            and target_brightness_step == self._state.brightness_step
            and transition_seconds != 0
        ):
            # An explicit 0 is a request to snap, so it falls through to
            # cancel the Ramp and write the target at once. A running
            # power_off_after plan is excluded even on a coincidental
            # match: turn_off deliberately leaves brightness_step and
            # colortemp_step at their pre-dim-out Target (issue #35), so
            # this equality says nothing about what that plan is actually
            # heading towards -- the halo-lit branch below is what
            # retargets a dim-out into a ramp-up correctly.
            plan = self._ramp_plan
            if last_level is not None and self._state.last_level != last_level:
                # Same hardware steps, different Level (95 and 100 both
                # land on brightness step 10): the Ramp is untouched but
                # status must report the Level last commanded.
                self._state.last_level = last_level
                self._save_state()
            self.last_writes = []
            self.last_transition = Transition(
                seconds=plan.transition_seconds, steps=len(plan.steps)
            )
            return self._status_locked()

        writes: list[tuple[int, int]] = []
        was_lit = self._halo_lit_locked()
        self._cancel_ramp_locked()

        if was_lit:
            # Genuinely on already, or mid dim-out (a power_off_after Ramp
            # that has not yet written D7 off): issue #35's "no flash"
            # case. Retarget straight to "on" with no D7 write.
            self._state.power = "on"
            applied_colortemp_step = self._resolve_applied_colortemp_step_locked()
            applied_brightness_step = self._resolve_applied_brightness_step_locked()
        elif transition_seconds == 0:
            # Dark, snapping: today's D7-then-D9 order, unchanged since #29.
            self._ensure_power_on_locked(writes)
            applied_colortemp_step = self._resolve_applied_colortemp_step_locked()
            applied_brightness_step = self._resolve_applied_brightness_step_locked()
        else:
            # Dark, with a Transition (issue #35): relight at the target
            # colour and brightness step 1 first, then Ramp up from there.
            d9_value = pack_d9(target_colortemp_step, 1)
            self._port.write_vcp(VCP_D9, d9_value)
            writes.append((VCP_D9, d9_value))
            self._port.write_vcp(VCP_POWER, POWER_ON_VALUE)
            writes.append((VCP_POWER, POWER_ON_VALUE))
            self._applied_colortemp_step = target_colortemp_step
            self._applied_brightness_step = 1
            self._state.power = "on"
            applied_colortemp_step = target_colortemp_step
            applied_brightness_step = 1
            if applied_brightness_step == target_brightness_step:
                # Turning on to the lowest level: the immediate D9 write
                # above already is the target, so it -- not a further,
                # identical write -- counts as the Transition's one step.
                if last_level is not None:
                    self._state.last_level = last_level
                self.last_writes = writes
                self.last_transition = Transition(seconds=float(transition_seconds), steps=1)
                self._save_state()
                return self._status_locked()

        colour_delta = target_colortemp_step - applied_colortemp_step
        brightness_delta = target_brightness_step - applied_brightness_step
        steps_delta = max(abs(colour_delta), abs(brightness_delta))

        step_count = 1
        if transition_seconds != 0 and steps_delta > 0:
            step_count = max(1, min(steps_delta, int(transition_seconds // WRITE_FLOOR_SECONDS)))

        if step_count <= 1:
            return self._write_move_now_locked(
                target_colortemp_step,
                target_brightness_step,
                writes,
                transition_seconds,
                last_level,
            )

        now = time.monotonic()
        plan_steps = [
            (
                now + (k * transition_seconds / (step_count - 1)),
                round(applied_colortemp_step + colour_delta * (k + 1) / step_count),
                round(applied_brightness_step + brightness_delta * (k + 1) / step_count),
            )
            for k in range(step_count)
        ]
        self._ramp_plan = _RampPlan(
            target_colortemp_step=target_colortemp_step,
            target_brightness_step=target_brightness_step,
            transition_seconds=transition_seconds,
            steps=plan_steps,
            start_time=now,
        )
        self._ensure_worker_started_locked()

        self._state.colortemp_step = target_colortemp_step
        self._state.brightness_step = target_brightness_step
        if last_level is not None:
            self._state.last_level = last_level
        self.last_writes = writes
        self.last_transition = Transition(seconds=float(transition_seconds), steps=step_count)
        self._save_state()
        self._condition.notify_all()
        return self._status_locked()

    def _plan_power_off_ramp_locked(
        self,
        applied_colortemp_step: int,
        applied_brightness_step: int,
        transition_seconds: float,
    ) -> None:
        """Plan the brightness-down Ramp a lit `turn_off` makes with a
        non-zero `transition`: from `applied_brightness_step` down to
        step 1, holding `applied_colortemp_step`, ending in a D7 off write
        the worker performs as the plan's true final write
        (`power_off_after=True`; see `_RampPlan`/`_worker_loop`). Uses the
        same step-count rule as `_plan_move_locked` -- the brightness
        delta, capped by `transition_seconds // WRITE_FLOOR_SECONDS` -- but,
        unlike that planner, this is never collapsed to a synchronous
        write: an Applied step of 1 plans zero D9 writes (the worker's
        only action is the D7 off write, performed at once), and a delta
        of one hardware step is a one-write plan followed by D7 off, not a
        synchronous write. Caller holds `self._lock` and is responsible
        for `self._state.power` and persisting it.
        """
        delta = applied_brightness_step - 1
        step_count = 0
        if delta > 0:
            step_count = max(1, min(delta, int(transition_seconds // WRITE_FLOOR_SECONDS)))

        now = time.monotonic()
        if step_count == 0:
            plan_steps: list[tuple[float, int, int]] = []
        else:
            denom = max(step_count - 1, 1)
            plan_steps = [
                (
                    now + (k * transition_seconds / denom),
                    applied_colortemp_step,
                    applied_brightness_step - round(delta * (k + 1) / step_count),
                )
                for k in range(step_count)
            ]

        self._ramp_plan = _RampPlan(
            target_colortemp_step=applied_colortemp_step,
            target_brightness_step=1,
            transition_seconds=transition_seconds,
            steps=plan_steps,
            start_time=now,
            power_off_after=True,
        )
        self._ensure_worker_started_locked()
        self.last_transition = Transition(seconds=float(transition_seconds), steps=step_count)

    def _cancel_ramp_locked(self) -> None:
        """Clear any in-flight Ramp plan, logging the writes it got to make.
        `power_off=True` names a dim-out Ramp cancelled before it ever
        wrote D7 off (issue #35) -- an on/brightness/colour command
        arriving mid dim-out, or a second `turn_off` retargeting it.
        Caller holds `self._lock`; the worker thread notices on its next
        wake and finds nothing to do."""
        plan = self._ramp_plan
        if plan is not None:
            self._ramp_plan = None
            self._logger.info(
                "ramp cancelled target=%d colour=%d writes=%s elapsed=%.2fs power_off=%s",
                plan.target_brightness_step,
                plan.target_colortemp_step,
                plan.performed,
                time.monotonic() - plan.start_time,
                plan.power_off_after,
            )
            self._condition.notify_all()

    def _resolve_applied_brightness_step_locked(self) -> int:
        """The brightness step currently on the monitor: the tracked
        Applied step if already known, else a fresh D9 read (with the
        existing retry and default fallback -- see `_resolve_d9_half_locked`),
        cached for next time.

        Deliberately does not fall back to the remembered Target step the
        way `_resolve_brightness_step_locked` does for a colour-only write:
        the Applied step is None only at startup with no persisted state
        (where the Target is equally unknown, so a fresh read is the same
        thing `_resolve_brightness_step_locked` would do anyway) or after a
        Ramp's final write failed twice, in which case the Target is
        exactly the step the monitor may not actually hold -- only a fresh
        read (or the default) may be trusted.
        """
        if self._applied_brightness_step is None:
            self._applied_brightness_step = self._resolve_d9_half_locked(
                None,
                is_high_byte=False,
                value_max=10,
                default=self._config.default_brightness_step,
                label="applied brightness step",
            )
        return self._applied_brightness_step

    def _resolve_applied_colortemp_step_locked(self) -> int:
        """The colour step currently on the monitor: the tracked Applied
        step if already known, else a fresh D9 read (with the existing
        retry and default fallback -- see `_resolve_d9_half_locked`),
        cached for next time. Like `_resolve_applied_brightness_step_locked`,
        this never trusts the remembered Target step: Applied is None only
        when the Target is unknown too, or after a Ramp's final write
        failed twice, when the Target is exactly what the monitor may not
        hold."""
        if self._applied_colortemp_step is None:
            self._applied_colortemp_step = self._resolve_d9_half_locked(
                None,
                is_high_byte=True,
                value_max=7,
                default=self._config.default_colortemp_step,
                label="applied colour step",
            )
        return self._applied_colortemp_step

    def _ensure_worker_started_locked(self) -> None:
        """Start the single daemon Ramp worker thread the first time a Ramp
        is planned. It needs no shutdown protocol: as a daemon it never
        blocks process exit, and it is harmless to leave running idle."""
        if self._worker_thread is None:
            self._worker_thread = threading.Thread(
                target=self._worker_loop, name="moonhalo-ramp-worker", daemon=True
            )
            self._worker_thread.start()

    def _worker_loop(self) -> None:
        """Runs for the model's lifetime: sleeps (via `self._condition`,
        which releases `self._lock` while waiting) until the next due Ramp
        write, performs it, and loops. A cancelled or retargeted plan is
        simply a different (or absent) `self._ramp_plan` by the time this
        wakes, which the identity check below catches. Write failures are
        handled by `_perform_ramp_write_locked` (see there for the
        intermediate-vs-final distinction); this loop only decides what
        happens next based on whether that write actually landed.

        A `power_off_after` plan (issue #35) has no D9 write treated as
        final -- its true final write is the D7 off `_perform_power_off_after_locked`
        makes once every D9 step is done, possibly none at all.
        """
        while True:
            with self._condition:
                plan = self._ramp_plan
                if plan is None:
                    self._condition.wait()
                    continue
                if plan.next_index >= len(plan.steps):
                    if plan.power_off_after:
                        self._perform_power_off_after_locked(plan)
                    self._condition.wait()
                    continue
                due_at, colortemp_step, brightness_step = plan.steps[plan.next_index]
                remaining = due_at - time.monotonic()
                if remaining > 0:
                    self._condition.wait(timeout=remaining)
                    continue
                if self._ramp_plan is not plan:
                    continue  # cancelled or replaced while we were waiting

                is_final = plan.next_index == len(plan.steps) - 1 and not plan.power_off_after
                value = pack_d9(colortemp_step, brightness_step)
                if self._perform_ramp_write_locked(plan, value, is_final):
                    self._applied_colortemp_step = colortemp_step
                    self._applied_brightness_step = brightness_step
                    plan.performed.append((VCP_D9, value))
                    plan.next_index += 1
                    if plan.next_index >= len(plan.steps) and not plan.power_off_after:
                        elapsed = time.monotonic() - plan.start_time
                        self._logger.info(
                            "ramp complete target=%d colour=%d writes=%s elapsed=%.2fs",
                            plan.target_brightness_step,
                            plan.target_colortemp_step,
                            plan.performed,
                            elapsed,
                        )
                        if self._ramp_plan is plan:
                            self._ramp_plan = None
                elif is_final:
                    # The final write failed even after its retry (already
                    # logged, and the Applied state already forgotten, by
                    # _perform_ramp_write_locked): the Ramp ends here.
                    if self._ramp_plan is plan:
                        self._ramp_plan = None
                else:
                    # An intermediate write failed and was skipped (already
                    # logged); the Ramp carries on towards the target (or,
                    # for a power_off_after plan, towards the D7 off write).
                    plan.next_index += 1

    def _perform_power_off_after_locked(self, plan: _RampPlan) -> None:
        """Perform the D7 off write a `power_off_after` Ramp ends in
        (issue #35), once its D9 writes (zero or more) are done -- the
        plan's true final write (see `_RampPlan`), so it gets the same
        final-write retry as any other, by passing `vcp_code=VCP_POWER`
        to `_perform_ramp_write_locked`. Whether it lands, or is
        abandoned after the retry (already logged, and the Applied D9
        state forgotten, by that method), the plan ends here either way:
        this is only ever attempted once. Caller holds `self._lock` (via
        `self._condition`)."""
        if self._perform_ramp_write_locked(plan, POWER_OFF_VALUE, True, vcp_code=VCP_POWER):
            plan.performed.append((VCP_POWER, POWER_OFF_VALUE))
            elapsed = time.monotonic() - plan.start_time
            self._logger.info(
                "ramp complete target=%d colour=%d writes=%s elapsed=%.2fs power_off=True",
                plan.target_brightness_step,
                plan.target_colortemp_step,
                plan.performed,
                elapsed,
            )
        if self._ramp_plan is plan:
            self._ramp_plan = None

    def _perform_ramp_write_locked(
        self, plan: _RampPlan, value: int, is_final: bool, vcp_code: int = VCP_D9
    ) -> bool:
        """Perform one Ramp write, handling a `DdcError` per the ticket:
        an intermediate write (`is_final` False) that fails is logged at
        warning and given up on immediately -- the Ramp just skips that
        hardware step. The final write instead gets one retry, after
        pausing `DEFAULT_READ_RETRY_DELAY` (the same pause the DDC read
        retry uses); if the retry also fails, the Ramp aborts: an error is
        logged naming the writes actually performed, and the Applied D9
        state is forgotten (`_forget_applied_locked`), so the next Ramp
        starts from a fresh D9 read rather than the Target step this write
        could not reach. Returns whether the value ended up written.

        `vcp_code` defaults to D9, every ordinary Ramp write; a
        `power_off_after` plan's true final write (issue #35) reuses this
        same retry-then-abort logic for D7 by passing `VCP_POWER` and
        `is_final=True` (`_perform_power_off_after_locked`) -- forgetting
        the Applied D9 state on that failure is a little imprecise (D9
        itself did not fail), but it is what "as for any final write"
        calls for, and it is a harmless extra D9 read next time either way.

        Caller holds `self._lock` (via `self._condition`) and is
        responsible for recording a successful write in `plan.performed`
        and, for a D9 write, `self._applied_brightness_step` /
        `self._applied_colortemp_step`.
        """
        try:
            self._port.write_vcp(vcp_code, value)
            return True
        except DdcError as error:
            if not is_final:
                self._logger.warning(
                    "ramp write failed for target=%d value=0x%04X: %s",
                    plan.target_brightness_step,
                    value,
                    error,
                )
                return False
            self._logger.warning(
                "ramp final write failed for target=%d value=0x%04X: %s; retrying",
                plan.target_brightness_step,
                value,
                error,
            )

        time.sleep(DEFAULT_READ_RETRY_DELAY)
        try:
            self._port.write_vcp(vcp_code, value)
            return True
        except DdcError as error:
            self._logger.error(
                "ramp aborted target=%d writes=%s error=%s",
                plan.target_brightness_step,
                plan.performed,
                error,
            )
            self._forget_applied_locked()
            return False

    def _forget_applied_locked(self) -> None:
        """The Applied state is unknown: every `_applied_*` attribute is
        set to None. Called when a Ramp's final write fails even after its
        retry, so the next Ramp resolves its starting step from a fresh D9
        read (see `_resolve_applied_brightness_step_locked`) instead of
        trusting a Target step the monitor may never have received.
        Caller holds `self._lock`."""
        self._applied_brightness_step = None
        self._applied_colortemp_step = None

    def set_colortemp(
        self, step: int, stage: bool = False, transition: Optional[float] = None
    ) -> dict[str, Any]:
        """Set MoonHalo colour temperature to hardware step `step` (1-7)
        over `transition` seconds (default `config.transition_seconds`).

        If `stage` is true, only the remembered `colortemp_step` changes:
        no DDC writes happen, the halo's power is untouched, `transition`
        is ignored, and a running Ramp is left alone entirely; the reply's
        Transition reports zero steps since nothing was written. Otherwise
        this goes through the shared planner (see `_plan_move_locked`),
        aimed at `step` and the brightness step to keep (see
        `_resolve_brightness_step_locked`) -- so a Ramp already in flight
        is retargeted into a combined move rather than restarted, an
        identical Target leaves it alone, and an explicit `transition` of
        0 snaps. If `last_level` was not yet known, it is derived from the
        brightness step kept.
        """
        with self._lock:
            if stage:
                self._state.colortemp_step = step
                self.last_writes = []
                self.last_transition = Transition(seconds=0.0, steps=0)
                self._save_state()
                return self._status_locked()

            resolved_transition = self._resolve_transition(transition)
            return self._plan_move_locked(step, None, resolved_transition)

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
            self._logger.warning(
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
