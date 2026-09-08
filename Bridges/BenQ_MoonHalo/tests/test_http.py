"""Tests for moonhalo_bridge.http: the Flask test client driven against a
FakeDdcPort, exactly as the Hub would drive the real Bridge over HTTP.
"""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from typing import Optional

from moonhalo_bridge import __version__
from pathlib import Path

from moonhalo_bridge.access import FakeArpTable
from moonhalo_bridge.config import Config
from moonhalo_bridge.ddc import DdcError, FakeDdcPort
from moonhalo_bridge.http import create_app
from moonhalo_bridge.model import (
    POWER_OFF_VALUE,
    POWER_ON_VALUE,
    VCP_D9,
    VCP_POWER,
    MoonHaloModel,
    colortemp_step_to_kelvin,
    level_to_brightness_step,
    pack_d9,
)


def make_config(tmp_dir: Path, **overrides) -> Config:
    values = dict(
        host="127.0.0.1",
        port=5000,
        default_on_level=50,
        monitor_selector=None,
        state_file=tmp_dir / "state.json",
        log_file=None,
        default_brightness_step=5,
        default_colortemp_step=4,
        kelvin_min=2700,
        kelvin_max=6500,
        invert_colortemp=False,
        allowed_macs=[],
        allowed_ips=[],
        allow_loopback=True,
    )
    values.update(overrides)
    return Config(**values)


class RaisingDdcPort(FakeDdcPort):
    """A FakeDdcPort whose write_vcp always raises, to exercise the 500 path."""

    def write_vcp(self, code: int, value: int) -> None:
        raise DdcError("simulated hardware failure")


class FailOnceDdcPort(FakeDdcPort):
    """A FakeDdcPort whose write_vcp raises exactly once, for the specific
    D9 value `fail_value`, to exercise the Ramp worker's DdcError handling
    without ever failing the setup writes."""

    def __init__(self, *args, fail_value: int, **kwargs):
        super().__init__(*args, **kwargs)
        self._fail_value = fail_value
        self._failed = False

    def write_vcp(self, code: int, value: int) -> None:
        if not self._failed and code == VCP_D9 and value == self._fail_value:
            self._failed = True
            raise DdcError("simulated ramp write failure")
        super().write_vcp(code, value)


class FailingWritesDdcPort(FakeDdcPort):
    """A FakeDdcPort whose write_vcp raises for scripted D9 values a fixed
    number of times, and which logs every `read_vcp` code -- the Ramp
    equivalent of `fail_reads` -- for exercising a Ramp's final-write retry
    (issue #34) and the fresh D9 read that follows an aborted Ramp.

    `fail_writes` maps D9 value -> a count of scripted write failures still
    owed for that value; each write of that value consumes one failure
    before falling through to a real write, mirroring `FakeDdcPort.fail_reads`.
    `reads` records every VCP register passed to `read_vcp`, in call order, so a
    test can assert a command read D9 before making its first write.
    """

    def __init__(self, *args, fail_writes: Optional[dict[int, int]] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_writes: dict[int, int] = dict(fail_writes) if fail_writes else {}
        self.reads: list[int] = []

    def read_vcp(self, code: int) -> tuple[int, int]:
        self.reads.append(code)
        return super().read_vcp(code)

    def write_vcp(self, code: int, value: int) -> None:
        if code == VCP_D9:
            remaining = self.fail_writes.get(value, 0)
            if remaining > 0:
                self.fail_writes[value] = remaining - 1
                raise DdcError(f"simulated write failure for D9 value 0x{value:04X}")
        super().write_vcp(code, value)


def _wait_for_writes(port: FakeDdcPort, count: int, deadline: float = 3.0) -> list[tuple[int, int]]:
    """Poll `port.writes` until it has at least `count` entries or
    `deadline` seconds pass. The Ramp tests below run in real time against
    a background worker thread, so this replaces a fixed sleep."""
    start = time.monotonic()
    while len(port.writes) < count and time.monotonic() - start < deadline:
        time.sleep(0.01)
    return port.writes


class HttpTestCase(unittest.TestCase):
    port_class = FakeDdcPort

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.port = self.port_class()
        self.config = make_config(self.tmp_dir)
        self.model = MoonHaloModel(self.port, self.config)
        self.app = create_app(self.model, self.config)
        self.app.testing = True
        self.client = self.app.test_client()


class TestHealth(HttpTestCase):
    def test_health_ok_with_no_ddc_call(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True, "version": __version__})
        self.assertEqual(self.port.writes, [])


class TestMoonHaloOn(HttpTestCase):
    def test_on_default_level(self):
        # transition=0: this test is about the D7-then-D9 snap order and
        # level resolution, not the relight-and-Ramp sequence a non-zero
        # Transition now takes (see TestPowerTransition).
        response = self.client.get("/moonhalo/on?transition=0")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["state"]["power"], "on")
        self.assertEqual(body["state"]["level"], self.config.default_on_level)
        expected_d9 = pack_d9(
            self.config.default_colortemp_step, level_to_brightness_step(self.config.default_on_level)
        )
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_ON_VALUE), (VCP_D9, expected_d9)])

    def test_on_with_valid_level_1(self):
        # transition=0: pin the snap order, as above.
        response = self.client.get("/moonhalo/on?level=1&transition=0")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["state"]["level"], 1)
        expected_d9 = pack_d9(self.config.default_colortemp_step, level_to_brightness_step(1))
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_ON_VALUE), (VCP_D9, expected_d9)])

    def test_on_with_valid_level_100(self):
        # transition=0: pin the snap order, as above.
        response = self.client.get("/moonhalo/on?level=100&transition=0")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["state"]["level"], 100)
        expected_d9 = pack_d9(self.config.default_colortemp_step, level_to_brightness_step(100))
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_ON_VALUE), (VCP_D9, expected_d9)])

    def test_on_with_level_70_uses_step_7(self):
        # transition=0: pin the snap order, as above.
        response = self.client.get("/moonhalo/on?level=70&transition=0")
        self.assertEqual(response.status_code, 200)
        expected_d9 = pack_d9(self.config.default_colortemp_step, 7)
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_ON_VALUE), (VCP_D9, expected_d9)])

    def test_on_with_level_0_rejected(self):
        response = self.client.get("/moonhalo/on?level=0")
        self.assertEqual(response.status_code, 400)
        body = response.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("error", body)
        self.assertEqual(self.port.writes, [])

    def test_on_with_level_101_rejected(self):
        response = self.client.get("/moonhalo/on?level=101")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])
        self.assertEqual(self.port.writes, [])

    def test_on_with_non_numeric_level_rejected(self):
        response = self.client.get("/moonhalo/on?level=abc")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])
        self.assertEqual(self.port.writes, [])

    def test_on_after_off_restores_last_level(self):
        # transition=0 throughout: this test is about the remembered Level
        # surviving a round trip through off, not any Ramp: a background
        # one left running past the test would be a stray write (and, on
        # a shared logger, a stray log line) for a later test to trip over.
        self.client.get("/moonhalo/on?level=70&transition=0")
        self.client.get("/moonhalo/off?transition=0")
        response = self.client.get("/moonhalo/on?transition=0")
        self.assertEqual(response.get_json()["state"]["level"], 70)


class TestMoonHaloOff(HttpTestCase):
    def test_off_writes_power_off_only(self):
        response = self.client.get("/moonhalo/off")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["state"]["power"], "off")
        self.assertEqual(body["state"]["level"], 0)
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_OFF_VALUE)])


class TestPowerTransition(HttpTestCase):
    """Issue #35: on and off over a Transition. Off dims the halo out --
    ramping brightness from the Applied step down to step 1 -- before
    writing D7 off; on (or a brightness/colour command while off) relights
    at the target colour and brightness step 1, writes D7 on, then ramps
    up. Retargeting across power never flashes and never writes D7 twice:
    an off arriving mid ramp-up turns into a ramp-down ending in D7 off,
    and an on/brightness/colour command arriving mid dim-out just turns
    the Ramp back around, since the halo was lit the whole time.
    """

    def _start_at_level(self, level: int) -> None:
        """Turn the halo on and drive it to `level`'s hardware brightness
        step with transition=0, so the Ramp under test starts from a
        known Applied step, then clear the setup write(s)."""
        response = self.client.get(f"/moonhalo/brightness/{level}?transition=0")
        self.assertEqual(response.status_code, 200)
        self.port.writes.clear()

    def test_off_with_transition_ramps_down_then_writes_d7_off(self):
        self._start_at_level(100)  # step 10
        colour_step = self.config.default_colortemp_step

        response = self.client.get("/moonhalo/off?transition=0.6")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["state"]["power"], "off")
        self.assertEqual(body["state"]["level"], 0)
        self.assertEqual(body["transition"], {"seconds": 0.6, "steps": 9})

        status = self.client.get("/moonhalo/status").get_json()
        self.assertEqual(status["state"]["power"], "off")
        self.assertEqual(status["state"]["level"], 0)

        writes = _wait_for_writes(self.port, 10)
        self.assertEqual(
            writes,
            [(VCP_D9, pack_d9(colour_step, step)) for step in range(9, 0, -1)]
            + [(VCP_POWER, POWER_OFF_VALUE)],
        )

    def test_off_with_transition_zero_writes_d7_off_only(self):
        self._start_at_level(100)
        response = self.client.get("/moonhalo/off?transition=0")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.0, "steps": 0})
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_OFF_VALUE)])

    def test_off_with_applied_step_one_plans_zero_d9_writes(self):
        self._start_at_level(1)  # step 1
        response = self.client.get("/moonhalo/off?transition=0.6")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.6, "steps": 0})
        writes = _wait_for_writes(self.port, 1)
        self.assertEqual(writes, [(VCP_POWER, POWER_OFF_VALUE)])

    def test_on_with_transition_while_off_relights_then_ramps_up(self):
        self.client.get("/moonhalo/brightness/100?transition=0")  # step 10
        self.client.get("/moonhalo/colortemp/4?transition=0")
        self.client.get("/moonhalo/off?transition=0")
        self.port.writes.clear()

        response = self.client.get("/moonhalo/on?transition=0.6")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["state"]["power"], "on")
        self.assertEqual(body["state"]["level"], 100)
        self.assertEqual(body["transition"], {"seconds": 0.6, "steps": 9})
        self.assertEqual(
            self.port.writes[:2],
            [(VCP_D9, pack_d9(4, 1)), (VCP_POWER, POWER_ON_VALUE)],
        )

        writes = _wait_for_writes(self.port, 11)
        self.assertEqual(writes[2:], [(VCP_D9, pack_d9(4, step)) for step in range(2, 11)])

    def test_on_with_transition_zero_while_off_keeps_the_snap(self):
        # Existing behaviour (unchanged): with transition=0, on() still
        # writes D7 then a single D9 -- see TestMoonHaloOn.
        self.client.get("/moonhalo/off?transition=0")
        self.port.writes.clear()
        response = self.client.get("/moonhalo/on?level=50&transition=0")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.port.writes[0], (VCP_POWER, POWER_ON_VALUE))
        self.assertEqual(self.port.writes[1][0], VCP_D9)

    def test_brightness_command_while_off_with_transition_follows_on_sequence(self):
        self.client.get("/moonhalo/brightness/100?transition=0")
        self.client.get("/moonhalo/colortemp/4?transition=0")
        self.client.get("/moonhalo/off?transition=0")
        self.port.writes.clear()

        response = self.client.get("/moonhalo/brightness/100?transition=0.6")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.port.writes[:2],
            [(VCP_D9, pack_d9(4, 1)), (VCP_POWER, POWER_ON_VALUE)],
        )
        writes = _wait_for_writes(self.port, 11)
        self.assertEqual(writes[2:], [(VCP_D9, pack_d9(4, step)) for step in range(2, 11)])

    def test_colortemp_command_while_off_with_transition_follows_on_sequence(self):
        self.client.get("/moonhalo/brightness/50?transition=0")  # step 5
        self.client.get("/moonhalo/off?transition=0")
        self.port.writes.clear()

        response = self.client.get("/moonhalo/colortemp/7?transition=0.6")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.port.writes[:2],
            [(VCP_D9, pack_d9(7, 1)), (VCP_POWER, POWER_ON_VALUE)],
        )
        # colour is already at the target in every write from here on --
        # only the brightness half ramps, from step 1 up to the remembered
        # step 5.
        writes = _wait_for_writes(self.port, 6)
        self.assertEqual(writes[2:], [(VCP_D9, pack_d9(7, step)) for step in range(2, 6)])

    def test_brightness_zero_with_transition_dims_out_like_off(self):
        self._start_at_level(1)  # step 1
        response = self.client.get("/moonhalo/brightness/0?transition=0.6")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["state"]["power"], "off")
        self.assertEqual(body["state"]["level"], 0)
        self.assertEqual(body["transition"], {"seconds": 0.6, "steps": 0})
        writes = _wait_for_writes(self.port, 1)
        self.assertEqual(writes, [(VCP_POWER, POWER_OFF_VALUE)])

    def test_off_during_a_ramp_up_ends_with_d7_off(self):
        self._start_at_level(1)  # step 1, on
        self.client.get("/moonhalo/brightness/100?transition=1.0")  # ramping up
        _wait_for_writes(self.port, 2)

        response = self.client.get("/moonhalo/off?transition=0.3")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["state"]["power"], "off")
        writes_at_off = list(self.port.writes)
        last_d9_before = max(value & 0xFF for code, value in writes_at_off if code == VCP_D9)

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and (
            not self.port.writes or self.port.writes[-1] != (VCP_POWER, POWER_OFF_VALUE)
        ):
            time.sleep(0.01)
        self.assertEqual(self.port.writes[-1], (VCP_POWER, POWER_OFF_VALUE))

        # the down-Ramp never overshoots past where the up-Ramp had reached
        new_d9_values = [
            value & 0xFF for code, value in self.port.writes[len(writes_at_off):] if code == VCP_D9
        ]
        for value in new_d9_values:
            self.assertLessEqual(value, last_d9_before)

    def test_on_during_an_off_ramp_turns_around_without_writing_d7(self):
        self._start_at_level(100)  # step 10, on
        self.client.get("/moonhalo/off?transition=1.0")  # dimming out
        _wait_for_writes(self.port, 2)
        count_before_on = len(self.port.writes)

        response = self.client.get("/moonhalo/on?transition=0.3")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["state"]["power"], "on")
        self.assertEqual(body["state"]["level"], 100)

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and (
            not self.port.writes or (self.port.writes[-1][1] & 0xFF) != 10
        ):
            time.sleep(0.01)

        # the halo was lit the whole time (mid dim-out): D7 off is never
        # written, and neither is a fresh D7 on.
        new_writes = self.port.writes[count_before_on:]
        self.assertNotIn((VCP_POWER, POWER_OFF_VALUE), new_writes)
        self.assertNotIn((VCP_POWER, POWER_ON_VALUE), new_writes)
        self.assertEqual(self.port.writes[-1][0], VCP_D9)
        self.assertEqual(self.port.writes[-1][1] & 0xFF, 10)

    def test_every_d7_write_is_on_or_off_value(self):
        self._start_at_level(1)
        self.client.get("/moonhalo/off?transition=0.3")
        _wait_for_writes(self.port, 1)
        self.client.get("/moonhalo/on?transition=0.3")
        _wait_for_writes(self.port, 5)
        for code, value in self.port.writes:
            if code == VCP_POWER:
                self.assertIn(value, (POWER_ON_VALUE, POWER_OFF_VALUE))

    def test_invalid_transition_on_off_rejected(self):
        for endpoint in ("/moonhalo/on", "/moonhalo/off"):
            for value in ("abc", "-1", "61"):
                with self.subTest(endpoint=endpoint, value=value):
                    response = self.client.get(f"{endpoint}?transition={value}")
                    self.assertEqual(response.status_code, 400)
                    body = response.get_json()
                    self.assertFalse(body["ok"])
                    self.assertIn("transition", body["error"])
                    self.assertEqual(self.port.writes, [])


class TestMoonHaloBrightness(HttpTestCase):
    def test_brightness_1_50_100_write_expected_low_byte(self):
        # establish a remembered colour step distinct from the default;
        # transition=0 so no background Ramp write can land between the
        # clear()s below and the single-write assertions they guard.
        self.client.get("/moonhalo/on?level=50&transition=0")
        self.port.writes.clear()
        colour_step = self.config.default_colortemp_step

        for level, expected_step in ((1, 1), (50, 5), (100, 10)):
            self.port.writes.clear()
            # transition=0: this test is about D9 packing/colour preservation,
            # not Ramps, so pin every write synchronous and deterministic.
            response = self.client.get(f"/moonhalo/brightness/{level}?transition=0")
            self.assertEqual(response.status_code, 200)
            body = response.get_json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["state"]["brightnessStep"], expected_step)
            expected_d9 = pack_d9(colour_step, expected_step)
            self.assertEqual(self.port.writes, [(VCP_D9, expected_d9)])

    def test_brightness_0_behaves_as_off(self):
        # transition=0 throughout: this test is about brightness 0
        # behaving as a plain off, not the dim-out a non-zero Transition
        # now gives it (see TestPowerTransition).
        self.client.get("/moonhalo/on?level=50&transition=0")
        self.port.writes.clear()
        response = self.client.get("/moonhalo/brightness/0?transition=0")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["state"]["power"], "off")
        self.assertEqual(body["state"]["level"], 0)
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_OFF_VALUE)])

    def test_brightness_while_off_writes_power_on_then_d9_in_order(self):
        self.client.get("/moonhalo/off")
        self.port.writes.clear()
        # transition=0: this test is about the D7-then-D9 snap order, not
        # the relight-and-Ramp sequence a non-zero Transition now takes.
        response = self.client.get("/moonhalo/brightness/50?transition=0")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.port.writes), 2)
        self.assertEqual(self.port.writes[0], (VCP_POWER, POWER_ON_VALUE))
        self.assertEqual(self.port.writes[1][0], VCP_D9)

    def test_no_remembered_colour_step_reads_d9_and_preserves_high_byte(self):
        self.port.registers[VCP_D9] = (0x0305, 0x070A)  # high byte 3
        # transition=0: pin the snap order, as above.
        response = self.client.get("/moonhalo/brightness/50?transition=0")
        body = response.get_json()
        self.assertEqual(body["state"]["colorTempStep"], 3)
        expected_d9 = pack_d9(3, level_to_brightness_step(50))
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_ON_VALUE), (VCP_D9, expected_d9)])

    def test_failing_read_falls_back_to_default_colour_step(self):
        self.port.fail_reads[VCP_D9] = 3  # exhaust every retry
        response = self.client.get("/moonhalo/brightness/50")
        body = response.get_json()
        self.assertEqual(body["state"]["colorTempStep"], self.config.default_colortemp_step)

    def test_value_101_rejected(self):
        response = self.client.get("/moonhalo/brightness/101")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])
        self.assertEqual(self.port.writes, [])

    def test_value_negative_one_rejected(self):
        response = self.client.get("/moonhalo/brightness/-1")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])
        self.assertEqual(self.port.writes, [])

    def test_value_non_numeric_rejected(self):
        response = self.client.get("/moonhalo/brightness/abc")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])
        self.assertEqual(self.port.writes, [])


class TestMoonHaloBrightnessTransition(HttpTestCase):
    """Issue #31: brightness moves over HTTP with a configurable Transition."""

    def _start_at_level(self, level: int) -> None:
        """Turn the halo on and drive it to `level`'s hardware step with
        transition=0, so the Ramp under test starts from a known Applied
        step, then clear the setup write(s)."""
        response = self.client.get(f"/moonhalo/brightness/{level}?transition=0")
        self.assertEqual(response.status_code, 200)
        self.port.writes.clear()

    def test_default_transition_ramps_nine_writes_and_replies_before_it_finishes(self):
        self._start_at_level(1)  # step 1
        colour_step = self.config.default_colortemp_step

        start = time.monotonic()
        response = self.client.get("/moonhalo/brightness/100?transition=0.6")  # step 10
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["state"]["level"], 100)
        self.assertEqual(body["transition"], {"seconds": 0.6, "steps": 9})
        # the reply comes back well before the ramp (0.6s) has finished
        self.assertLess(len(self.port.writes), 9)

        writes = _wait_for_writes(self.port, 9)
        elapsed = time.monotonic() - start
        self.assertEqual(writes, [(VCP_D9, pack_d9(colour_step, step)) for step in range(2, 11)])
        self.assertGreaterEqual(elapsed, 0.6)
        self.assertLess(elapsed, 1.2)

    def test_transition_zero_is_one_synchronous_write(self):
        self._start_at_level(10)
        response = self.client.get("/moonhalo/brightness/100?transition=0")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.0, "steps": 1})
        self.assertEqual(len(self.port.writes), 1)

    def test_one_hardware_step_change_is_one_synchronous_write(self):
        self._start_at_level(50)  # step 5
        response = self.client.get("/moonhalo/brightness/60?transition=0.6")  # step 6
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.6, "steps": 1})
        self.assertEqual(len(self.port.writes), 1)

    def test_configured_default_is_a_sweep_time(self):
        # Issue #37: with no query the configured `transition_seconds` is a
        # Sweep time. 0.3 s is too short for nine writes at the 60 ms
        # floor, so a full sweep is six writes one floor apart (0.30 s).
        port = FakeDdcPort()
        config = make_config(
            self.tmp_dir, transition_seconds=0.3, state_file=self.tmp_dir / "default03.json"
        )
        model = MoonHaloModel(port, config)
        client = create_app(model, config).test_client()
        client.get("/moonhalo/brightness/1?transition=0")  # step 1
        port.writes.clear()

        response = client.get("/moonhalo/brightness/100")  # step 10, no query
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.3, "steps": 6})
        writes = _wait_for_writes(port, 6)
        self.assertEqual(len(writes), 6)

    def test_configured_default_transition_zero_is_synchronous(self):
        port = FakeDdcPort()
        config = make_config(
            self.tmp_dir, transition_seconds=0, state_file=self.tmp_dir / "default0.json"
        )
        model = MoonHaloModel(port, config)
        client = create_app(model, config).test_client()
        client.get("/moonhalo/brightness/10?transition=0")
        port.writes.clear()

        response = client.get("/moonhalo/brightness/100")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.0, "steps": 1})
        self.assertEqual(len(port.writes), 1)

    def test_too_short_transition_drops_intermediate_steps_evenly(self):
        self._start_at_level(1)  # step 1
        colour_step = self.config.default_colortemp_step

        start = time.monotonic()
        response = self.client.get("/moonhalo/brightness/100?transition=0.2")  # step 10
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.2, "steps": 3})

        writes = _wait_for_writes(self.port, 3)
        elapsed = time.monotonic() - start
        self.assertEqual(
            writes,
            [(VCP_D9, pack_d9(colour_step, step)) for step in (4, 7, 10)],
        )
        self.assertGreaterEqual(elapsed, 0.2)

    def test_ramp_down_writes_descending_steps(self):
        self._start_at_level(100)  # step 10
        response = self.client.get("/moonhalo/brightness/10?transition=0.3")  # step 2
        self.assertEqual(response.status_code, 200)

        writes = _wait_for_writes(self.port, 5)
        self.assertEqual(len(writes), 5)
        brightness_values = [value & 0xFF for _, value in writes]
        self.assertEqual(brightness_values, sorted(brightness_values, reverse=True))
        self.assertEqual(brightness_values[-1], level_to_brightness_step(10))

    def test_status_during_a_ramp_reports_the_target_level(self):
        self._start_at_level(10)
        response = self.client.get("/moonhalo/brightness/100?transition=1.0")
        self.assertEqual(response.status_code, 200)

        status = self.client.get("/moonhalo/status").get_json()
        self.assertEqual(status["state"]["level"], 100)
        _wait_for_writes(self.port, 9, deadline=1.5)  # let the ramp settle

    def test_retarget_mid_ramp_continues_from_the_applied_step(self):
        self._start_at_level(1)  # step 1
        self.client.get("/moonhalo/brightness/100?transition=1.0")  # step 10
        _wait_for_writes(self.port, 2)
        writes_before_retarget = list(self.port.writes)
        highest_before = max(value & 0xFF for _, value in writes_before_retarget)

        response = self.client.get("/moonhalo/brightness/1?transition=0.3")  # step 1
        self.assertEqual(response.status_code, 200)

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if self.port.writes and (self.port.writes[-1][1] & 0xFF) == 1:
                break
            time.sleep(0.01)

        new_writes = self.port.writes[len(writes_before_retarget):]
        self.assertTrue(new_writes)
        for _, value in new_writes:
            self.assertLessEqual(value & 0xFF, highest_before)
        self.assertEqual(self.port.writes[-1][1] & 0xFF, 1)

    def test_same_target_mid_ramp_adds_no_writes(self):
        self._start_at_level(1)  # step 1
        self.client.get("/moonhalo/brightness/100?transition=1.0")  # step 10
        _wait_for_writes(self.port, 2)

        response = self.client.get("/moonhalo/brightness/100?transition=1.0")
        self.assertEqual(response.status_code, 200)

        writes = _wait_for_writes(self.port, 9, deadline=2.0)
        self.assertEqual(len(writes), 9)

    def test_same_target_with_transition_zero_mid_ramp_snaps(self):
        self._start_at_level(1)  # step 1
        self.client.get("/moonhalo/brightness/100?transition=1.0")  # step 10
        _wait_for_writes(self.port, 2)

        with self.assertLogs("moonhalo_bridge.model", level="INFO") as logs:
            response = self.client.get("/moonhalo/brightness/100?transition=0")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.0, "steps": 1})
        self.assertEqual(self.port.writes[-1], (VCP_D9, pack_d9(self.config.default_colortemp_step, 10)))
        self.assertTrue(any("ramp cancelled" in line for line in logs.output))

        count_after_snap = len(self.port.writes)
        time.sleep(0.3)  # a cancelled ramp writes nothing more
        self.assertEqual(len(self.port.writes), count_after_snap)

    def test_colortemp_command_mid_ramp_with_default_transition_retargets(self):
        # Issue #33: a colortemp command now carries its own Transition
        # (default `config.transition_seconds`, here 0.6s) like brightness
        # always has, so an unqualified call no longer snaps -- it
        # retargets the running Ramp into a combined move instead.
        self._start_at_level(1)  # step 1
        self.client.get("/moonhalo/brightness/100?transition=1.0")  # step 10
        _wait_for_writes(self.port, 2)

        response = self.client.get("/moonhalo/colortemp/7")
        self.assertEqual(response.status_code, 200)
        # a cancel-and-snap would write pack_d9(7, 10) immediately; a
        # retarget does not -- it continues from wherever the Ramp has
        # reached, so the very next write is not yet the final target.
        self.assertNotEqual(self.port.writes[-1], (VCP_D9, pack_d9(7, 10)))

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and self.port.writes[-1] != (VCP_D9, pack_d9(7, 10)):
            time.sleep(0.01)
        self.assertEqual(self.port.writes[-1], (VCP_D9, pack_d9(7, 10)))

    def test_colortemp_command_with_transition_zero_mid_ramp_cancels_it_and_writes_the_target(self):
        self._start_at_level(1)  # step 1
        self.client.get("/moonhalo/brightness/100?transition=1.0")  # step 10
        _wait_for_writes(self.port, 2)

        response = self.client.get("/moonhalo/colortemp/7?transition=0")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.port.writes[-1], (VCP_D9, pack_d9(7, 10)))

        count_after = len(self.port.writes)
        time.sleep(0.3)
        self.assertEqual(len(self.port.writes), count_after)

    def test_same_step_different_level_mid_ramp_updates_the_level_only(self):
        self._start_at_level(1)  # step 1
        self.client.get("/moonhalo/brightness/100?transition=1.0")  # step 10
        _wait_for_writes(self.port, 2)

        response = self.client.get("/moonhalo/brightness/95?transition=1.0")  # also step 10
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["state"]["level"], 95)
        self.assertEqual(self.client.get("/moonhalo/status").get_json()["state"]["level"], 95)

        writes = _wait_for_writes(self.port, 9, deadline=2.0)
        self.assertEqual(len(writes), 9)

    def test_state_file_holds_target_immediately_after_the_reply(self):
        self._start_at_level(10)
        response = self.client.get("/moonhalo/brightness/100?transition=0.6")
        self.assertEqual(response.status_code, 200)

        with open(self.config.state_file, "r", encoding="utf-8") as handle:
            persisted = json.load(handle)
        self.assertEqual(persisted["brightness_step"], 10)
        self.assertEqual(persisted["last_level"], 100)

        second_model = MoonHaloModel(FakeDdcPort(), self.config)
        second_client = create_app(second_model, self.config).test_client()
        status = second_client.get("/moonhalo/status").get_json()["state"]
        self.assertEqual(status["level"], 100)

        _wait_for_writes(self.port, 9, deadline=1.5)  # let the ramp settle

    def test_invalid_transition_values_rejected_with_no_write(self):
        self._start_at_level(10)
        for value in ("abc", "-1", "61"):
            with self.subTest(value=value):
                response = self.client.get(f"/moonhalo/brightness/50?transition={value}")
                self.assertEqual(response.status_code, 400)
                body = response.get_json()
                self.assertFalse(body["ok"])
                self.assertIn("transition", body["error"])
                self.assertEqual(self.port.writes, [])


class TestSweepPacing(HttpTestCase):
    """Issue #37: every default-paced move runs at one pace. The configured
    `transition_seconds` (or a `sweep` query) is a Sweep time -- what a full
    nine-step brightness move takes -- so the interval between writes is
    `max(sweep / 9, WRITE_FLOOR_SECONDS)` and a k-write move ends after
    (k - 1) intervals. At 0.54 s or more every step is written; below
    that the writes stay at the floor and steps are dropped evenly (the
    2026-09-08 amendment on #30). An explicit `transition` keeps its
    total-time meaning and wins over `sweep`.
    """

    def _client_with_sweep(self, sweep: float):
        port = FakeDdcPort()
        config = make_config(
            self.tmp_dir, transition_seconds=sweep, state_file=self.tmp_dir / f"sweep{sweep}.json"
        )
        model = MoonHaloModel(port, config)
        return port, create_app(model, config).test_client()

    def _start_at_level(self, client, port, level: int) -> None:
        response = client.get(f"/moonhalo/brightness/{level}?transition=0")
        self.assertEqual(response.status_code, 200)
        port.writes.clear()

    def test_sweep_of_nine_floors_writes_all_nine_steps_at_the_floor(self):
        port, client = self._client_with_sweep(0.54)
        self._start_at_level(client, port, 1)  # step 1
        colour_step = self.config.default_colortemp_step

        start = time.monotonic()
        response = client.get("/moonhalo/brightness/100")  # step 10
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.48, "steps": 9})

        writes = _wait_for_writes(port, 9)
        elapsed = time.monotonic() - start
        self.assertEqual(writes, [(VCP_D9, pack_d9(colour_step, step)) for step in range(2, 11)])
        self.assertGreaterEqual(elapsed, 0.48)
        self.assertLess(elapsed, 1.0)

    def test_two_step_move_ends_after_one_interval(self):
        port, client = self._client_with_sweep(0.54)
        self._start_at_level(client, port, 50)  # step 5
        colour_step = self.config.default_colortemp_step

        start = time.monotonic()
        response = client.get("/moonhalo/brightness/23")  # step 3
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.06, "steps": 2})

        writes = _wait_for_writes(port, 2)
        elapsed = time.monotonic() - start
        self.assertEqual(writes, [(VCP_D9, pack_d9(colour_step, step)) for step in (4, 3)])
        self.assertLess(elapsed, 0.4)

    def test_short_sweep_keeps_the_floor_pace_and_drops_steps(self):
        # 0.3 s: a full sweep is six writes 60 ms apart; a five-step move
        # gets its share, three writes; a two-step move is one write.
        port, client = self._client_with_sweep(0.3)
        self._start_at_level(client, port, 1)  # step 1
        colour_step = self.config.default_colortemp_step

        start = time.monotonic()
        response = client.get("/moonhalo/brightness/100")  # step 10
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.3, "steps": 6})
        writes = _wait_for_writes(port, 6)
        elapsed = time.monotonic() - start
        self.assertEqual(writes[-1], (VCP_D9, pack_d9(colour_step, 10)))
        self.assertEqual(len(writes), 6)
        self.assertGreaterEqual(elapsed, 0.3)
        self.assertLess(elapsed, 0.8)
        port.writes.clear()

        response = client.get("/moonhalo/brightness/50")  # step 5, five steps down
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.12, "steps": 3})
        writes = _wait_for_writes(port, 3)
        self.assertEqual(writes[-1], (VCP_D9, pack_d9(colour_step, 5)))
        port.writes.clear()

        response = client.get("/moonhalo/brightness/23")  # step 3, two steps down
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.0, "steps": 1})
        self.assertEqual(port.writes, [(VCP_D9, pack_d9(colour_step, 3))])

    def test_sweep_0_9_paces_writes_100ms_apart(self):
        port, client = self._client_with_sweep(0.9)
        self._start_at_level(client, port, 1)  # step 1

        start = time.monotonic()
        response = client.get("/moonhalo/brightness/100")  # step 10
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.8, "steps": 9})

        writes = _wait_for_writes(port, 9)
        elapsed = time.monotonic() - start
        self.assertEqual(len(writes), 9)
        self.assertGreaterEqual(elapsed, 0.8)
        self.assertLess(elapsed, 1.4)

    def test_sweep_query_overrides_the_configured_sweep_time(self):
        self._start_at_level(self.client, self.port, 1)  # config sweep is 0.6
        response = self.client.get("/moonhalo/brightness/100?sweep=0.9")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.8, "steps": 9})
        _wait_for_writes(self.port, 9, deadline=1.5)

    def test_sweep_query_zero_snaps(self):
        self._start_at_level(self.client, self.port, 1)
        response = self.client.get("/moonhalo/brightness/100?sweep=0")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.0, "steps": 1})
        self.assertEqual(len(self.port.writes), 1)

    def test_transition_wins_over_sweep_when_both_are_present(self):
        self._start_at_level(self.client, self.port, 1)
        response = self.client.get("/moonhalo/brightness/100?transition=0.2&sweep=0.9")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.2, "steps": 3})
        _wait_for_writes(self.port, 3)

    def test_explicit_transition_still_drops_steps_and_lands_on_time(self):
        port, client = self._client_with_sweep(0.9)
        self._start_at_level(client, port, 1)
        start = time.monotonic()
        response = client.get("/moonhalo/brightness/100?transition=0.2")
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.2, "steps": 3})
        writes = _wait_for_writes(port, 3)
        elapsed = time.monotonic() - start
        self.assertEqual(len(writes), 3)
        self.assertGreaterEqual(elapsed, 0.2)
        self.assertLess(elapsed, 0.6)

    def test_invalid_sweep_values_rejected_on_every_endpoint_with_no_write(self):
        self._start_at_level(self.client, self.port, 50)
        for path in ("/moonhalo/on", "/moonhalo/off", "/moonhalo/brightness/100", "/moonhalo/colortemp/7"):
            for value in ("abc", "-1", "61"):
                with self.subTest(path=path, value=value):
                    response = self.client.get(f"{path}?sweep={value}")
                    self.assertEqual(response.status_code, 400)
                    body = response.get_json()
                    self.assertFalse(body["ok"])
                    self.assertIn("sweep", body["error"])
                    self.assertEqual(self.port.writes, [])

    def test_off_dims_out_at_the_sweep_interval(self):
        port, client = self._client_with_sweep(0.54)
        self._start_at_level(client, port, 100)  # step 10
        colour_step = self.config.default_colortemp_step

        start = time.monotonic()
        response = client.get("/moonhalo/off")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.48, "steps": 9})

        writes = _wait_for_writes(port, 10)
        elapsed = time.monotonic() - start
        self.assertEqual(
            writes,
            [(VCP_D9, pack_d9(colour_step, step)) for step in range(9, 0, -1)]
            + [(VCP_POWER, POWER_OFF_VALUE)],
        )
        self.assertGreaterEqual(elapsed, 0.48)
        self.assertLess(elapsed, 1.0)

    def test_off_from_step_two_is_one_write_then_d7_off_at_once(self):
        port, client = self._client_with_sweep(0.54)
        self._start_at_level(client, port, 12)  # step 2
        colour_step = self.config.default_colortemp_step
        response = client.get("/moonhalo/off")
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.0, "steps": 1})
        writes = _wait_for_writes(port, 2)
        self.assertEqual(writes, [(VCP_D9, pack_d9(colour_step, 1)), (VCP_POWER, POWER_OFF_VALUE)])

    def test_on_rises_at_the_sweep_interval(self):
        port, client = self._client_with_sweep(0.54)
        client.get("/moonhalo/brightness/100?transition=0")  # step 10
        client.get("/moonhalo/colortemp/4?transition=0")
        client.get("/moonhalo/off?transition=0")
        port.writes.clear()

        start = time.monotonic()
        response = client.get("/moonhalo/on")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.48, "steps": 9})
        self.assertEqual(port.writes[:2], [(VCP_D9, pack_d9(4, 1)), (VCP_POWER, POWER_ON_VALUE)])

        writes = _wait_for_writes(port, 11)
        elapsed = time.monotonic() - start
        self.assertEqual(writes[2:], [(VCP_D9, pack_d9(4, step)) for step in range(2, 11)])
        self.assertGreaterEqual(elapsed, 0.48)
        self.assertLess(elapsed, 1.0)

    def test_on_to_the_lowest_level_from_dark_is_the_relight_write_alone(self):
        # The relight D9 write at step 1 already is the target: one step,
        # no interval, so a Sweep-paced reply reports 0.0 seconds.
        port, client = self._client_with_sweep(0.54)
        client.get("/moonhalo/colortemp/4?transition=0")
        client.get("/moonhalo/off?transition=0")
        port.writes.clear()

        response = client.get("/moonhalo/on?level=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.0, "steps": 1})
        self.assertEqual(port.writes, [(VCP_D9, pack_d9(4, 1)), (VCP_POWER, POWER_ON_VALUE)])

    def test_on_and_off_accept_the_sweep_query(self):
        self._start_at_level(self.client, self.port, 100)
        response = self.client.get("/moonhalo/off?sweep=0.9")
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.8, "steps": 9})
        _wait_for_writes(self.port, 10, deadline=1.5)
        self.port.writes.clear()

        response = self.client.get("/moonhalo/on?sweep=0.9")
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.8, "steps": 9})
        _wait_for_writes(self.port, 11, deadline=1.5)

    def test_colortemp_move_runs_at_the_sweep_interval(self):
        port, client = self._client_with_sweep(0.54)
        client.get("/moonhalo/brightness/50?transition=0")  # step 5
        client.get("/moonhalo/colortemp/1?transition=0")
        port.writes.clear()

        response = client.get("/moonhalo/colortemp/7")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.3, "steps": 6})
        writes = _wait_for_writes(port, 6)
        self.assertEqual(writes, [(VCP_D9, pack_d9(c, 5)) for c in range(2, 8)])

    def test_retarget_mid_ramp_keeps_the_pace(self):
        # sweep=9 gives a 1 s interval: the first write (step 2) lands at
        # once and step 3 is due a second later, so a retarget at 0.3 s
        # starts from Applied step 2 -- a three-step move to step 5, still
        # one write per second, planned as two intervals.
        self._start_at_level(self.client, self.port, 1)
        self.client.get("/moonhalo/brightness/100?sweep=9")
        _wait_for_writes(self.port, 1)
        time.sleep(0.3)

        response = self.client.get("/moonhalo/brightness/50?sweep=9")  # step 5
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["transition"], {"seconds": 2.0, "steps": 3})
        colour_step = self.config.default_colortemp_step
        writes = _wait_for_writes(self.port, 2)  # the retargeted Ramp's first write, step 3
        self.assertEqual(writes[:2], [(VCP_D9, pack_d9(colour_step, 2)), (VCP_D9, pack_d9(colour_step, 3))])

        self.client.get("/moonhalo/brightness/50?transition=0")  # cancel the slow ramp

    def test_same_target_mid_ramp_leaves_it_alone(self):
        self._start_at_level(self.client, self.port, 1)
        first = self.client.get("/moonhalo/brightness/100?sweep=9").get_json()["transition"]
        self.assertEqual(first, {"seconds": 8.0, "steps": 9})
        _wait_for_writes(self.port, 1)

        second = self.client.get("/moonhalo/brightness/100?sweep=9").get_json()["transition"]
        self.assertEqual(second, first)
        self.assertEqual(len(self.port.writes), 1)

        self.client.get("/moonhalo/brightness/100?transition=0")  # cancel the slow ramp


class TestRampWriteFailure(HttpTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.config = make_config(self.tmp_dir)
        fail_value = pack_d9(self.config.default_colortemp_step, 5)  # one of the planned writes
        self.port = FailOnceDdcPort(fail_value=fail_value)
        self.model = MoonHaloModel(self.port, self.config)
        self.app = create_app(self.model, self.config)
        self.app.testing = True
        self.client = self.app.test_client()

    def test_a_failed_write_is_logged_and_skipped_and_the_ramp_completes(self):
        self.client.get("/moonhalo/brightness/1?transition=0")  # step 1
        self.port.writes.clear()

        with self.assertLogs(level="WARNING") as logs:
            response = self.client.get("/moonhalo/brightness/100?transition=0.6")  # step 10
            self.assertEqual(response.status_code, 200)
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and len(self.port.writes) < 8:
                time.sleep(0.01)

        # 9 writes were planned; the one for step 5 raised and was skipped.
        self.assertEqual(len(self.port.writes), 8)
        self.assertTrue(any("ramp write failed" in message for message in logs.output))


class TestRampFinalWriteFailure(HttpTestCase):
    """Issue #34: a Ramp survives a DDC/CI failure mid-way. The final write
    of a Ramp gets a retry the intermediate writes do not; if the retry
    also fails the Ramp aborts and the Applied state becomes unknown, so
    the next command reads D9 fresh instead of trusting the stale Target.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.config = make_config(self.tmp_dir)
        # The last of the 9 writes a 1 -> 100 (step 1 -> step 10) Ramp plans.
        self.final_value = pack_d9(self.config.default_colortemp_step, 10)
        self.port = FailingWritesDdcPort()
        self.model = MoonHaloModel(self.port, self.config)
        self.app = create_app(self.model, self.config)
        self.app.testing = True
        self.client = self.app.test_client()

    def _start_at_level(self, level: int) -> None:
        """Drive the halo to `level`'s hardware step with transition=0 (no
        scripted failures armed yet), then clear the setup write(s)."""
        response = self.client.get(f"/moonhalo/brightness/{level}?transition=0")
        self.assertEqual(response.status_code, 200)
        self.port.writes.clear()

    def test_final_write_failing_once_is_retried_and_lands(self):
        self._start_at_level(1)  # step 1
        self.port.fail_writes = {self.final_value: 1}

        with self.assertLogs("moonhalo_bridge.model", level="INFO") as logs:
            response = self.client.get("/moonhalo/brightness/100?transition=0.6")  # step 10
            self.assertEqual(response.status_code, 200)
            writes = _wait_for_writes(self.port, 9)

        # All 9 planned writes land, ending on the target -- the failed
        # attempt was retried rather than skipped like an intermediate one.
        self.assertEqual(len(writes), 9)
        self.assertEqual(writes[-1], (VCP_D9, self.final_value))

        warning_lines = [line for line in logs.output if "WARNING" in line]
        self.assertEqual(len(warning_lines), 1)
        complete_lines = [line for line in logs.output if "ramp complete" in line]
        self.assertEqual(len(complete_lines), 1)
        self.assertIn("target=10", complete_lines[0])
        self.assertIn(f"writes={writes}", complete_lines[0])

    def test_final_write_failing_twice_aborts_and_forgets_applied(self):
        self._start_at_level(1)  # step 1
        self.port.fail_writes = {self.final_value: 2}

        with self.assertLogs("moonhalo_bridge.model", level="WARNING") as logs:
            response = self.client.get("/moonhalo/brightness/100?transition=0.6")  # step 10
            self.assertEqual(response.status_code, 200)
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and len(self.port.writes) < 8:
                time.sleep(0.01)
            time.sleep(0.2)  # give the failed retry time to (not) write again

        # 9 writes were planned; the 8 before the target land, the target
        # itself never does -- neither the first attempt nor the retry.
        self.assertEqual(len(self.port.writes), 8)
        performed = list(self.port.writes)

        abort_lines = [line for line in logs.output if "ramp aborted" in line]
        self.assertEqual(len(abort_lines), 1)
        self.assertIn("target=10", abort_lines[0])
        self.assertIn(f"writes={performed}", abort_lines[0])
        self.assertFalse(any("ramp complete" in line for line in logs.output))

        # The Applied state is now unknown. Make the monitor's register hold
        # a step distinct from both the 8 landed writes and the failed
        # target of 10, so the next command can only be planning from a
        # fresh read of it, not from the stale Target step of 10.
        self.port.registers[VCP_D9] = (pack_d9(self.config.default_colortemp_step, 3), 100)
        self.port.reads.clear()

        response = self.client.get("/moonhalo/brightness/80?transition=0.6")  # step 8
        self.assertEqual(response.status_code, 200)

        # The read happens synchronously while resolving the Applied step,
        # inside the request handler, strictly before the plan (and so the
        # first Ramp write) is even computed -- the write sequence checked
        # below is the proof: it could only start from the register's step
        # 3 if this read's value was what got used.
        self.assertIn(VCP_D9, self.port.reads)

        new_writes = _wait_for_writes(self.port, len(performed) + 5)[len(performed):]
        # Starting from the register's step 3 towards target step 8 over
        # 0.6s gives 5 writes counting up 4, 5, 6, 7, 8; starting from the
        # stale Target step of 10 would instead count down from 9.
        self.assertEqual([value & 0xFF for _, value in new_writes], [4, 5, 6, 7, 8])


class TestBrightnessTransitionLogging(HttpTestCase):
    """The brightness log line names the target level and the Transition
    applied, in addition to the immediate writes (see TestBrightnessLogging
    below for that base format)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.port = FakeDdcPort()
        self.config = make_config(self.tmp_dir, log_file=self.tmp_dir / "bridge.log")
        self.model = MoonHaloModel(self.port, self.config)
        self.app = create_app(self.model, self.config)
        self.app.testing = True
        self.client = self.app.test_client()
        self.addCleanup(self._close_log_handlers)

    def _close_log_handlers(self) -> None:
        import logging

        for name in (f"moonhalo_bridge.http.{id(self.config)}", "moonhalo_bridge.model.test"):
            logger = logging.getLogger(name)
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)

    def test_ramp_completion_line_lands_in_the_log_file(self):
        # `serve` builds the model with the Bridge's file logger, so the
        # worker's completion line sits next to the request lines.
        from moonhalo_bridge.logs import file_logger

        model = MoonHaloModel(self.port, self.config, logger=file_logger("moonhalo_bridge.model.test", self.config))
        client = create_app(model, self.config).test_client()
        client.get("/moonhalo/brightness/1?transition=0")  # step 1
        client.get("/moonhalo/brightness/100?transition=0.3")  # step 10, 5 writes
        _wait_for_writes(self.port, 7)  # D7 on + D9 step 1, then the 5 ramp writes
        time.sleep(0.05)  # the log line follows the last write

        log_text = self.config.log_file.read_text(encoding="utf-8")
        complete_lines = [line for line in log_text.splitlines() if "ramp complete" in line]
        self.assertEqual(len(complete_lines), 1)
        self.assertIn("target=10", complete_lines[0])
        self.assertIn(f"writes={self.port.writes[2:]}", complete_lines[0])

    def test_log_line_names_the_target_and_the_transition(self):
        self.client.get("/moonhalo/brightness/1?transition=0")  # step 1
        response = self.client.get("/moonhalo/brightness/100?transition=0.6")  # step 10
        self.assertEqual(response.status_code, 200)

        log_text = self.config.log_file.read_text(encoding="utf-8")
        lines = [line for line in log_text.splitlines() if "/moonhalo/brightness" in line]
        self.assertEqual(len(lines), 2)
        ramp_line = lines[-1]
        self.assertIn("target=100", ramp_line)
        self.assertIn("transition=0.6s", ramp_line)
        self.assertIn("steps=9", ramp_line)

        _wait_for_writes(self.port, 9, deadline=1.5)  # let the ramp settle

    def test_sweep_paced_log_line_shows_the_planned_duration_and_write_count(self):
        self.client.get("/moonhalo/brightness/1?transition=0")  # step 1
        response = self.client.get("/moonhalo/brightness/100?sweep=0.3")  # step 10
        self.assertEqual(response.status_code, 200)

        log_text = self.config.log_file.read_text(encoding="utf-8")
        ramp_line = [line for line in log_text.splitlines() if "/moonhalo/brightness" in line][-1]
        self.assertIn("transition=0.3s", ramp_line)
        self.assertIn("steps=6", ramp_line)

        _wait_for_writes(self.port, 9, deadline=1.5)  # let the ramp settle

    def test_colortemp_log_line_names_the_target_and_the_transition(self):
        self.client.get("/moonhalo/colortemp/1?transition=0")  # step 1
        response = self.client.get("/moonhalo/colortemp/7?transition=0.6")  # six writes
        self.assertEqual(response.status_code, 200)

        log_text = self.config.log_file.read_text(encoding="utf-8")
        lines = [line for line in log_text.splitlines() if "/moonhalo/colortemp" in line]
        self.assertEqual(len(lines), 2)
        ramp_line = lines[-1]
        self.assertIn("target=7", ramp_line)
        self.assertIn("transition=0.6s", ramp_line)
        self.assertIn("steps=6", ramp_line)

        _wait_for_writes(self.port, 6, deadline=1.5)  # let the ramp settle


class TestMoonHaloColortemp(HttpTestCase):
    def test_kelvin_2700_4600_6500_produce_steps_1_4_7(self):
        for kelvin, expected_step in ((2700, 1), (4600, 4), (6500, 7)):
            # transition=0 on both calls: this test is about the Kelvin ->
            # step mapping, not any Ramp -- one left running past the test
            # would be a stray write for a later test to trip over.
            self.client.get("/moonhalo/on?level=50&transition=0")
            self.port.writes.clear()
            response = self.client.get(f"/moonhalo/colortemp/{kelvin}?transition=0")
            self.assertEqual(response.status_code, 200)
            body = response.get_json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["state"]["colorTempStep"], expected_step)

    def test_bare_steps_1_to_7_pass_through(self):
        for step in range(1, 8):
            # transition=0 on both calls, as above.
            self.client.get("/moonhalo/on?level=50&transition=0")
            self.port.writes.clear()
            response = self.client.get(f"/moonhalo/colortemp/{step}?transition=0")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["state"]["colorTempStep"], step)

    def test_invalid_values_rejected_with_no_write(self):
        for value in ("0", "8", "999", "-1", "abc"):
            self.port.writes.clear()
            response = self.client.get(f"/moonhalo/colortemp/{value}")
            self.assertEqual(response.status_code, 400)
            body = response.get_json()
            self.assertFalse(body["ok"])
            self.assertIn("error", body)
            self.assertEqual(self.port.writes, [])

    def test_invert_flips_direction(self):
        self.config_inverted = make_config(self.tmp_dir, invert_colortemp=True, state_file=self.tmp_dir / "inv.json")
        model = MoonHaloModel(FakeDdcPort(), self.config_inverted)
        app = create_app(model, self.config_inverted)
        app.testing = True
        client = app.test_client()

        # transition=0: this test is about the inverted Kelvin -> step
        # mapping, not any Ramp -- one left running past the test would be
        # a stray write for a later test to trip over.
        response = client.get("/moonhalo/colortemp/2700?transition=0")
        self.assertEqual(response.get_json()["state"]["colorTempStep"], 7)

        response = client.get("/moonhalo/colortemp/6500?transition=0")
        self.assertEqual(response.get_json()["state"]["colorTempStep"], 1)

    def test_invert_status_kelvin_consistent(self):
        config = make_config(self.tmp_dir, invert_colortemp=True, state_file=self.tmp_dir / "inv2.json")
        model = MoonHaloModel(FakeDdcPort(), config)
        app = create_app(model, config)
        app.testing = True
        client = app.test_client()

        # transition=0: as above.
        client.get("/moonhalo/colortemp/2700?transition=0")
        status = client.get("/moonhalo/status").get_json()
        self.assertEqual(status["state"]["colorTempStep"], 7)
        self.assertEqual(
            status["state"]["colorTemperature"],
            colortemp_step_to_kelvin(7, config.kelvin_min, config.kelvin_max, invert=True),
        )

    def test_d9_write_keeps_remembered_brightness_step(self):
        # transition=0: no background Ramp write can then land between the
        # clear() and the single-write assertion below.
        self.client.get("/moonhalo/on?level=50&transition=0")
        self.port.writes.clear()
        # transition=0: this test is about D9 packing/brightness preservation,
        # not Ramps, so pin the write synchronous and deterministic.
        response = self.client.get("/moonhalo/colortemp/7?transition=0")
        expected_d9 = pack_d9(7, level_to_brightness_step(50))
        self.assertEqual(self.port.writes, [(VCP_D9, expected_d9)])
        self.assertEqual(response.get_json()["state"]["colorTempStep"], 7)

    def test_no_remembered_brightness_reads_d9_and_keeps_low_byte(self):
        self.port.registers[VCP_D9] = (0x0105, 0x070A)  # low byte 5
        # transition=0: pin the write synchronous, as above.
        response = self.client.get("/moonhalo/colortemp/7?transition=0")
        body = response.get_json()
        self.assertEqual(body["state"]["brightnessStep"], 5)
        expected_d9 = pack_d9(7, 5)
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_ON_VALUE), (VCP_D9, expected_d9)])

    def test_failing_read_falls_back_to_default_brightness_step_with_warning(self):
        self.port.fail_reads[VCP_D9] = 3  # exhaust every retry
        # transition=0: no Ramp needed for this test, and a background one
        # left running past it would be a stray write for a later test.
        with self.assertLogs(level="WARNING") as logs:
            response = self.client.get("/moonhalo/colortemp/7?transition=0")
        body = response.get_json()
        self.assertEqual(body["state"]["brightnessStep"], self.config.default_brightness_step)
        self.assertTrue(any("brightness step" in message for message in logs.output))

    def test_colour_while_off_writes_d7_then_d9_in_order(self):
        self.client.get("/moonhalo/off")
        self.port.writes.clear()
        # transition=0: pin the write synchronous, as above.
        response = self.client.get("/moonhalo/colortemp/7?transition=0")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.port.writes), 2)
        self.assertEqual(self.port.writes[0], (VCP_POWER, POWER_ON_VALUE))
        self.assertEqual(self.port.writes[1][0], VCP_D9)

    def test_stage_while_off_records_step_with_no_write_then_on_uses_it(self):
        self.client.get("/moonhalo/off")
        self.port.writes.clear()

        response = self.client.get("/moonhalo/colortemp/3000?stage=1")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(self.port.writes, [])
        self.assertEqual(body["state"]["power"], "off")
        staged_step = body["state"]["colorTempStep"]

        # transition=0: pin the D7-then-D9 snap order, as elsewhere -- this
        # test is about the staged step being used, not the relight-and-
        # Ramp sequence a non-zero Transition now takes.
        response = self.client.get("/moonhalo/on?transition=0")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.port.writes), 2)
        expected_d9 = pack_d9(staged_step, level_to_brightness_step(self.config.default_on_level))
        self.assertEqual(self.port.writes[1], (VCP_D9, expected_d9))

    def test_status_after_restart_reports_same_step_and_kelvin(self):
        # transition=0: no Ramp needed for this test.
        self.client.get("/moonhalo/colortemp/6500?transition=0")
        expected = self.client.get("/moonhalo/status").get_json()["state"]

        second_model = MoonHaloModel(FakeDdcPort(), self.config)
        second_app = create_app(second_model, self.config)
        second_app.testing = True
        second_client = second_app.test_client()
        actual = second_client.get("/moonhalo/status").get_json()["state"]

        self.assertEqual(actual["colorTempStep"], expected["colorTempStep"])
        self.assertEqual(actual["colorTemperature"], expected["colorTemperature"])


class TestMoonHaloColortempTransition(HttpTestCase):
    """Issue #33: colour Ramps, combined brightness/colour moves, and
    retargeting a Ramp already in flight."""

    def _start_at(self, level: int, colortemp_step: int) -> None:
        """Turn the halo on and drive it to `colortemp_step` and `level`'s
        hardware brightness step with transition=0, so the Ramp under test
        starts from a known Applied state, then clear the setup writes."""
        self.client.get(f"/moonhalo/brightness/{level}?transition=0")
        self.client.get(f"/moonhalo/colortemp/{colortemp_step}?transition=0")
        self.port.writes.clear()

    def test_colour_step_1_to_7_writes_six_steps_brightness_preserved(self):
        self._start_at(50, 1)  # brightness step 5, colour step 1

        start = time.monotonic()
        response = self.client.get("/moonhalo/colortemp/7?transition=0.6")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.6, "steps": 6})

        writes = _wait_for_writes(self.port, 6)
        elapsed = time.monotonic() - start
        self.assertEqual(writes, [(VCP_D9, pack_d9(c, 5)) for c in range(2, 8)])
        self.assertGreaterEqual(elapsed, 0.6)

    def test_brightness_then_colour_commands_combine_into_one_ramp(self):
        self._start_at(10, 4)  # brightness step 1, colour step 4

        self.client.get("/moonhalo/brightness/100?transition=1.0")  # brightness target step 10
        time.sleep(0.1)
        response = self.client.get("/moonhalo/colortemp/7?transition=1.0")  # colour target step 7
        self.assertEqual(response.status_code, 200)

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and self.port.writes[-1] != (VCP_D9, pack_d9(7, 10)):
            time.sleep(0.01)
        self.assertEqual(self.port.writes[-1], (VCP_D9, pack_d9(7, 10)))

        # the brightness byte never decreases, and no packed value is
        # written twice in a row, on the way to the combined target.
        brightness_values = [value & 0xFF for _, value in self.port.writes]
        self.assertEqual(brightness_values, sorted(brightness_values))
        for previous, current in zip(self.port.writes, self.port.writes[1:]):
            self.assertNotEqual(previous, current)

    def test_stage_with_transition_writes_nothing(self):
        self.client.get("/moonhalo/off")
        self.port.writes.clear()

        response = self.client.get("/moonhalo/colortemp/3000?stage=1&transition=5")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.port.writes, [])
        self.assertEqual(response.get_json()["transition"], {"seconds": 0.0, "steps": 0})

    def test_invalid_transition_values_rejected_with_no_write(self):
        self._start_at(50, 4)
        for value in ("abc", "-1", "61"):
            with self.subTest(value=value):
                response = self.client.get(f"/moonhalo/colortemp/7?transition={value}")
                self.assertEqual(response.status_code, 400)
                body = response.get_json()
                self.assertFalse(body["ok"])
                self.assertIn("transition", body["error"])
                self.assertEqual(self.port.writes, [])


class TestMoonHaloStatus(HttpTestCase):
    def test_status_performs_no_write(self):
        response = self.client.get("/moonhalo/status")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(
            set(body["state"].keys()),
            {"power", "level", "brightnessStep", "colorTemperature", "colorTempStep", "monitor"},
        )
        self.assertEqual(self.port.writes, [])

    def test_status_reflects_prior_on(self):
        # transition=0: no Ramp needed for this test, and a background one
        # left running past it would be a stray write for a later test.
        self.client.get("/moonhalo/on?level=42&transition=0")
        response = self.client.get("/moonhalo/status")
        body = response.get_json()
        self.assertEqual(body["state"]["power"], "on")
        self.assertEqual(body["state"]["level"], 42)


class TestUnknownRoute(HttpTestCase):
    def test_404_is_json(self):
        response = self.client.get("/does-not-exist")
        self.assertEqual(response.status_code, 404)
        body = response.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("error", body)


class TestDdcFailure(HttpTestCase):
    port_class = RaisingDdcPort

    def test_on_failure_returns_500_and_leaves_state_unchanged(self):
        response = self.client.get("/moonhalo/on?level=70")
        self.assertEqual(response.status_code, 500)
        body = response.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("simulated hardware failure", body["error"])

        status = self.client.get("/moonhalo/status").get_json()
        self.assertEqual(status["state"]["power"], "unknown")

    def test_off_failure_returns_500_and_leaves_state_unchanged(self):
        response = self.client.get("/moonhalo/off")
        self.assertEqual(response.status_code, 500)
        body = response.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("simulated hardware failure", body["error"])

        status = self.client.get("/moonhalo/status").get_json()
        self.assertEqual(status["state"]["power"], "unknown")

    def test_brightness_failure_returns_500(self):
        response = self.client.get("/moonhalo/brightness/50")
        self.assertEqual(response.status_code, 500)
        body = response.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("simulated hardware failure", body["error"])

    def test_colortemp_failure_returns_500(self):
        response = self.client.get("/moonhalo/colortemp/7")
        self.assertEqual(response.status_code, 500)
        body = response.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("simulated hardware failure", body["error"])


class TestBrightnessLogging(HttpTestCase):
    """The log line for /moonhalo/brightness reports the writes the model
    actually performed, not a fixed constant."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.port = FakeDdcPort()
        self.config = make_config(self.tmp_dir, log_file=self.tmp_dir / "bridge.log")
        self.model = MoonHaloModel(self.port, self.config)
        self.app = create_app(self.model, self.config)
        self.app.testing = True
        self.client = self.app.test_client()
        # The FileHandler keeps `bridge.log` open; close it before the
        # TemporaryDirectory cleanup tries to delete the file (Windows).
        self.addCleanup(self._close_log_handlers)

    def _close_log_handlers(self) -> None:
        import logging

        logger = logging.getLogger(f"moonhalo_bridge.http.{id(self.config)}")
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)

    def test_log_line_contains_the_real_writes(self):
        # transition=0: this test is about the log line naming the real
        # applied D9 value, not the relight-and-Ramp sequence a non-zero
        # Transition now takes (whose immediate D9 write is only step 1).
        response = self.client.get("/moonhalo/brightness/50?transition=0")
        self.assertEqual(response.status_code, 200)

        log_text = self.config.log_file.read_text(encoding="utf-8")
        lines = [line for line in log_text.splitlines() if "/moonhalo/brightness" in line]
        self.assertEqual(len(lines), 1)
        expected_d9 = pack_d9(self.config.default_colortemp_step, level_to_brightness_step(50))
        self.assertIn(str((VCP_POWER, POWER_ON_VALUE)), lines[0])
        self.assertIn(str((VCP_D9, expected_d9)), lines[0])

    def test_colortemp_log_line_contains_the_real_writes(self):
        # transition=0: pin the write synchronous, as above.
        response = self.client.get("/moonhalo/colortemp/7?transition=0")
        self.assertEqual(response.status_code, 200)

        log_text = self.config.log_file.read_text(encoding="utf-8")
        lines = [line for line in log_text.splitlines() if "/moonhalo/colortemp" in line]
        self.assertEqual(len(lines), 1)
        expected_d9 = pack_d9(7, self.config.default_brightness_step)
        self.assertIn(str((VCP_POWER, POWER_ON_VALUE)), lines[0])
        self.assertIn(str((VCP_D9, expected_d9)), lines[0])


class AccessControlTestCase(unittest.TestCase):
    """Builds an app with a non-empty allowlist and a FakeArpTable, per the
    ticket's testing decisions: everything is driven through the Flask test
    client, with the caller set via `environ_base={"REMOTE_ADDR": ...}`.
    """

    ALLOWED_MAC = "ec:b5:fa:82:2d:1d"
    ALLOWED_IP = "192.168.86.27"
    HUB_IP = "192.168.86.27"
    OTHER_IP = "192.168.86.50"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.port = FakeDdcPort()

    def build(self, arp_entries=None, **config_overrides):
        overrides = dict(allowed_macs=[self.ALLOWED_MAC], allowed_ips=[], allow_loopback=True)
        overrides.update(config_overrides)
        config = make_config(self.tmp_dir, **overrides)
        model = MoonHaloModel(self.port, config)
        arp = FakeArpTable(arp_entries or {})
        app = create_app(model, config, arp=arp)
        app.testing = True
        return app.test_client(), config

    def get(self, client, path, remote_addr):
        return client.get(path, environ_base={"REMOTE_ADDR": remote_addr})


class TestAccessAllowedMac(AccessControlTestCase):
    def test_allowed_mac_succeeds(self):
        client, _ = self.build(arp_entries={self.HUB_IP: self.ALLOWED_MAC})
        response = self.get(client, "/moonhalo/status", self.HUB_IP)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])


class TestAccessDifferentMac(AccessControlTestCase):
    def test_different_mac_gets_403(self):
        client, _ = self.build(arp_entries={self.OTHER_IP: "aa:bb:cc:dd:ee:ff"})
        response = self.get(client, "/moonhalo/status", self.OTHER_IP)
        self.assertEqual(response.status_code, 403)
        body = response.get_json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "forbidden")


class TestAccessIpAbsentFromArp(AccessControlTestCase):
    def test_ip_with_no_arp_entry_gets_403(self):
        client, _ = self.build(arp_entries={})
        response = self.get(client, "/moonhalo/status", self.OTHER_IP)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.get_json()["ok"])


class TestAccessIpAllowlist(AccessControlTestCase):
    def test_ip_allowlist_admits_without_arp_entry(self):
        config = make_config(
            self.tmp_dir,
            allowed_macs=[],
            allowed_ips=[self.ALLOWED_IP],
            allow_loopback=True,
        )
        model = MoonHaloModel(self.port, config)
        app = create_app(model, config, arp=FakeArpTable({}))
        app.testing = True
        client = app.test_client()

        response = self.get(client, "/moonhalo/status", self.ALLOWED_IP)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])


class TestAccessMacFormats(AccessControlTestCase):
    def test_mac_formats_compare_equal(self):
        for raw_mac in ("EC-B5-FA-82-2D-1D", "ec:b5:fa:82:2d:1d", "ecb5.fa82.2d1d", "Ec:B5:fA:82:2D:1d"):
            with self.subTest(raw_mac=raw_mac):
                client, _ = self.build(arp_entries={self.HUB_IP: raw_mac})
                response = self.get(client, "/moonhalo/status", self.HUB_IP)
                self.assertEqual(response.status_code, 200)


class TestAccessLoopback(AccessControlTestCase):
    def test_loopback_admitted_when_allowed(self):
        client, _ = self.build(arp_entries={})
        response = self.get(client, "/moonhalo/status", "127.0.0.1")
        self.assertEqual(response.status_code, 200)

    def test_loopback_rejected_when_disallowed(self):
        client, _ = self.build(arp_entries={}, allow_loopback=False)
        response = self.get(client, "/moonhalo/status", "127.0.0.1")
        self.assertEqual(response.status_code, 403)


class TestAccessOpenPolicy(AccessControlTestCase):
    def test_open_policy_admits_anyone_and_logs_startup_warning(self):
        config = make_config(
            self.tmp_dir,
            allowed_macs=[],
            allowed_ips=[],
            allow_loopback=True,
        )
        model = MoonHaloModel(self.port, config)
        with self.assertLogs(level="WARNING") as logs:
            app = create_app(model, config, arp=FakeArpTable({}))
        self.assertTrue(any("open" in message.lower() for message in logs.output))

        app.testing = True
        client = app.test_client()
        response = self.get(client, "/moonhalo/status", self.OTHER_IP)
        self.assertEqual(response.status_code, 200)


class TestAccessHealthBypasses(AccessControlTestCase):
    def test_health_bypasses_policy_from_denied_caller(self):
        client, _ = self.build(arp_entries={})
        response = self.get(client, "/health", self.OTHER_IP)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])


class TestAccessEnforcedOnEveryEndpoint(AccessControlTestCase):
    def test_every_moonhalo_endpoint_is_enforced(self):
        client, _ = self.build(arp_entries={})
        paths = [
            "/moonhalo/on",
            "/moonhalo/off",
            "/moonhalo/status",
            "/moonhalo/brightness/50",
            "/moonhalo/colortemp/4",
        ]
        for path in paths:
            with self.subTest(path=path):
                response = self.get(client, path, self.OTHER_IP)
                self.assertEqual(response.status_code, 403)
                self.assertFalse(response.get_json()["ok"])
        self.assertEqual(self.port.writes, [])


class TestAccessDenialLogging(AccessControlTestCase):
    def test_denied_request_logs_ip_and_mac_and_performs_no_ddc_write(self):
        config = make_config(
            self.tmp_dir,
            allowed_macs=[self.ALLOWED_MAC],
            allowed_ips=[],
            allow_loopback=True,
            log_file=self.tmp_dir / "bridge.log",
        )
        model = MoonHaloModel(self.port, config)
        arp = FakeArpTable({self.OTHER_IP: "aa:bb:cc:dd:ee:ff"})
        app = create_app(model, config, arp=arp)
        app.testing = True
        client = app.test_client()
        self.addCleanup(self._close_log_handlers, config)

        response = self.get(client, "/moonhalo/on", self.OTHER_IP)
        self.assertEqual(response.status_code, 403)

        log_text = config.log_file.read_text(encoding="utf-8")
        lines = [line for line in log_text.splitlines() if "access denied" in line]
        self.assertEqual(len(lines), 1)
        self.assertIn(self.OTHER_IP, lines[0])
        self.assertIn("aa:bb:cc:dd:ee:ff", lines[0])
        self.assertEqual(self.port.writes, [])

    def _close_log_handlers(self, config: Config) -> None:
        import logging

        logger = logging.getLogger(f"moonhalo_bridge.http.{id(config)}")
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)


if __name__ == "__main__":
    unittest.main()
