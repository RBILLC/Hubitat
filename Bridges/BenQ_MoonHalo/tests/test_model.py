"""Tests for moonhalo_bridge.config and moonhalo_bridge.model: config
defaults, the MoonHalo model's on/off/status behaviour and state
persistence, and the colour-temperature band maths.

All model tests use FakeDdcPort and a temporary directory for the state
file; no DDC port exception here can reach real hardware.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from moonhalo_bridge.config import DEFAULTS, Config, load_config
from moonhalo_bridge.ddc import DdcError, FakeDdcPort
from moonhalo_bridge.model import (
    POWER_OFF_VALUE,
    POWER_ON_VALUE,
    VCP_D9,
    VCP_POWER,
    MoonHaloModel,
    brightness_step_to_level,
    colortemp_step_to_kelvin,
    kelvin_to_colortemp_step,
    level_to_brightness_step,
    pack_d9,
)


def make_config(tmp_dir: Path, **overrides) -> Config:
    """A Config with every field defaulted, state/log files under `tmp_dir`,
    for tests that want to bypass `load_config` entirely."""
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


class TestLoadConfigDefaults(unittest.TestCase):
    def test_missing_file_uses_all_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(Path(tmp) / "does-not-exist.json")
            self.assertEqual(config.host, DEFAULTS["host"])
            self.assertEqual(config.port, DEFAULTS["port"])
            self.assertEqual(config.default_on_level, DEFAULTS["default_on_level"])
            self.assertIsNone(config.monitor_selector)
            self.assertEqual(config.state_file, Path(tmp) / "state.json")
            self.assertEqual(config.log_file.name, "bridge.log")
        self.assertEqual(config.log_file.parent, config.state_file.parent)
            self.assertEqual(config.default_brightness_step, DEFAULTS["default_brightness_step"])
            self.assertEqual(config.default_colortemp_step, DEFAULTS["default_colortemp_step"])
            self.assertEqual(config.kelvin_min, DEFAULTS["kelvin_min"])
            self.assertEqual(config.kelvin_max, DEFAULTS["kelvin_max"])
            self.assertFalse(config.invert_colortemp)
            self.assertEqual(config.allowed_macs, [])
            self.assertEqual(config.allowed_ips, [])
            self.assertTrue(config.allow_loopback)

    def test_partial_file_fills_missing_keys_with_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(json.dumps({"port": 9001, "default_on_level": 80}), encoding="utf-8")
            config = load_config(config_path)
            self.assertEqual(config.port, 9001)
            self.assertEqual(config.default_on_level, 80)
            # everything else still defaulted
            self.assertEqual(config.host, DEFAULTS["host"])
            self.assertEqual(config.kelvin_min, DEFAULTS["kelvin_min"])

    def test_relative_state_file_resolves_next_to_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(json.dumps({"state_file": "my_state.json"}), encoding="utf-8")
            config = load_config(config_path)
            self.assertEqual(config.state_file, Path(tmp) / "my_state.json")


class TestColortempStepToKelvin(unittest.TestCase):
    def test_endpoints_within_range(self):
        low = colortemp_step_to_kelvin(1, 2700, 6500)
        high = colortemp_step_to_kelvin(7, 2700, 6500)
        self.assertGreaterEqual(low, 2700)
        self.assertLessEqual(high, 6500)

    def test_monotonically_increasing(self):
        values = [colortemp_step_to_kelvin(step, 2700, 6500) for step in range(1, 8)]
        self.assertEqual(values, sorted(values))
        self.assertEqual(len(set(values)), 7)  # all seven bands distinct

    def test_out_of_range_step_raises(self):
        with self.assertRaises(ValueError):
            colortemp_step_to_kelvin(0, 2700, 6500)
        with self.assertRaises(ValueError):
            colortemp_step_to_kelvin(8, 2700, 6500)


class TestKelvinToColortempStep(unittest.TestCase):
    def test_reference_points(self):
        self.assertEqual(kelvin_to_colortemp_step(2700, 2700, 6500), 1)
        self.assertEqual(kelvin_to_colortemp_step(4600, 2700, 6500), 4)
        self.assertEqual(kelvin_to_colortemp_step(6500, 2700, 6500), 7)

    def test_every_kelvin_in_range_maps_to_a_step_1_to_7(self):
        for kelvin in range(2700, 6501):
            step = kelvin_to_colortemp_step(kelvin, 2700, 6500)
            self.assertGreaterEqual(step, 1)
            self.assertLessEqual(step, 7)

    def test_round_trip_with_colortemp_step_to_kelvin(self):
        for step in range(1, 8):
            centre = colortemp_step_to_kelvin(step, 2700, 6500)
            self.assertEqual(kelvin_to_colortemp_step(centre, 2700, 6500), step)

    def test_below_range_clamps_to_step_1(self):
        self.assertEqual(kelvin_to_colortemp_step(0, 2700, 6500), 1)
        self.assertEqual(kelvin_to_colortemp_step(2699, 2700, 6500), 1)

    def test_above_range_clamps_to_step_7(self):
        self.assertEqual(kelvin_to_colortemp_step(6501, 2700, 6500), 7)
        self.assertEqual(kelvin_to_colortemp_step(10000, 2700, 6500), 7)

    def test_invert_flips_reference_points(self):
        self.assertEqual(kelvin_to_colortemp_step(2700, 2700, 6500, invert=True), 7)
        self.assertEqual(kelvin_to_colortemp_step(6500, 2700, 6500, invert=True), 1)

    def test_invert_round_trip_with_colortemp_step_to_kelvin(self):
        for step in range(1, 8):
            centre = colortemp_step_to_kelvin(step, 2700, 6500, invert=True)
            self.assertEqual(kelvin_to_colortemp_step(centre, 2700, 6500, invert=True), step)


class TestBrightnessScaling(unittest.TestCase):
    def test_level_to_brightness_step_reference_points(self):
        self.assertEqual(level_to_brightness_step(1), 1)
        self.assertEqual(level_to_brightness_step(50), 5)
        self.assertEqual(level_to_brightness_step(100), 10)

    def test_brightness_step_to_level_reference_points(self):
        self.assertEqual(brightness_step_to_level(1), 1)
        self.assertEqual(brightness_step_to_level(10), 100)

    def test_round_trip_is_monotonic(self):
        levels = list(range(1, 101))
        round_tripped = [brightness_step_to_level(level_to_brightness_step(level)) for level in levels]
        self.assertEqual(round_tripped, sorted(round_tripped))

    def test_round_trip_exact_at_endpoints(self):
        self.assertEqual(brightness_step_to_level(level_to_brightness_step(1)), 1)
        self.assertEqual(brightness_step_to_level(level_to_brightness_step(100)), 100)

    def test_pack_d9_high_and_low_bytes(self):
        self.assertEqual(pack_d9(4, 5), 0x0405)
        self.assertEqual(pack_d9(1, 1), 0x0101)
        self.assertEqual(pack_d9(7, 10), 0x070A)


class TestMoonHaloModelPower(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.port = FakeDdcPort()
        self.config = make_config(self.tmp_dir)
        self.model = MoonHaloModel(self.port, self.config)

    def test_turn_on_writes_power_then_d9(self):
        # No remembered colour step and an empty register: the D9 read
        # fails after retries, so the default colour step (4) is used.
        state = self.model.turn_on()
        expected_brightness_step = level_to_brightness_step(self.config.default_on_level)
        expected_d9 = pack_d9(self.config.default_colortemp_step, expected_brightness_step)
        self.assertEqual(
            self.port.writes,
            [(VCP_POWER, POWER_ON_VALUE), (VCP_D9, expected_d9)],
        )
        self.assertEqual(state["power"], "on")
        self.assertEqual(state["level"], self.config.default_on_level)

    def test_turn_on_with_level_records_that_level(self):
        state = self.model.turn_on(70)
        expected_d9 = pack_d9(self.config.default_colortemp_step, level_to_brightness_step(70))
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_ON_VALUE), (VCP_D9, expected_d9)])
        self.assertEqual(state["level"], 70)

    def test_turn_off_writes_exactly_power_off(self):
        self.model.turn_on(70)
        writes_before_off = list(self.port.writes)
        state = self.model.turn_off()
        self.assertEqual(self.port.writes, writes_before_off + [(VCP_POWER, POWER_OFF_VALUE)])
        self.assertEqual(state["power"], "off")
        self.assertEqual(state["level"], 0)

    def test_status_performs_no_write(self):
        self.model.status()
        self.assertEqual(self.port.writes, [])

    def test_state_dict_always_has_six_keys(self):
        state = self.model.status()
        self.assertEqual(
            set(state.keys()),
            {"power", "level", "brightnessStep", "colorTemperature", "colorTempStep", "monitor"},
        )

    def test_monitor_description_from_list_monitors(self):
        state = self.model.status()
        self.assertEqual(state["monitor"], "Generic PnP Monitor")

    def test_monitor_unknown_when_no_monitors(self):
        class NoMonitorsPort(FakeDdcPort):
            def list_monitors(self):
                return []

        port = NoMonitorsPort()
        model = MoonHaloModel(port, make_config(self.tmp_dir, state_file=self.tmp_dir / "state2.json"))
        self.assertEqual(model.status()["monitor"], "unknown")


class TestMoonHaloModelSetLevel(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.port = FakeDdcPort()
        self.config = make_config(self.tmp_dir)
        self.model = MoonHaloModel(self.port, self.config)

    def test_brightness_1_50_100_keep_remembered_colour_step(self):
        self.model.turn_on(50)  # establishes power "on" and a remembered colour step
        remembered_colour_step = self.port.registers[VCP_D9][0] >> 8
        self.port.writes.clear()

        for level, expected_step in ((1, 1), (50, 5), (100, 10)):
            self.port.writes.clear()
            state = self.model.set_level(level)
            expected_d9 = pack_d9(remembered_colour_step, expected_step)
            self.assertEqual(self.port.writes, [(VCP_D9, expected_d9)])
            self.assertEqual(state["brightnessStep"], expected_step)

    def test_brightness_0_writes_only_power_off(self):
        self.model.turn_on(50)
        self.port.writes.clear()
        state = self.model.set_level(0)
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_OFF_VALUE)])
        self.assertEqual(state["power"], "off")
        self.assertEqual(state["level"], 0)

    def test_brightness_while_off_writes_power_on_then_d9_in_order(self):
        self.model.turn_off()
        self.port.writes.clear()
        self.model.set_level(50)
        self.assertEqual(len(self.port.writes), 2)
        self.assertEqual(self.port.writes[0], (VCP_POWER, POWER_ON_VALUE))
        self.assertEqual(self.port.writes[1][0], VCP_D9)

    def test_no_remembered_colour_step_reads_d9_and_preserves_high_byte(self):
        self.port.registers[VCP_D9] = (0x0305, 0x070A)  # high byte 3
        state = self.model.set_level(50)
        self.assertEqual(state["colorTempStep"], 3)
        expected_d9 = pack_d9(3, level_to_brightness_step(50))
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_ON_VALUE), (VCP_D9, expected_d9)])

    def test_failing_read_falls_back_to_default_colour_step_and_warns(self):
        self.port.fail_reads[VCP_D9] = 3  # exhaust every retry
        with self.assertLogs(level="WARNING") as logs:
            state = self.model.set_level(50)
        self.assertEqual(state["colorTempStep"], self.config.default_colortemp_step)
        self.assertTrue(any("colour step" in message for message in logs.output))

    def test_on_with_level_query_writes_power_then_d9_with_step(self):
        state = self.model.turn_on(70)
        expected_d9 = pack_d9(self.config.default_colortemp_step, level_to_brightness_step(70))
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_ON_VALUE), (VCP_D9, expected_d9)])
        self.assertEqual(state["level"], 70)

    def test_on_after_off_restores_last_level(self):
        self.model.turn_on(70)
        self.model.turn_off()
        state = self.model.turn_on()
        self.assertEqual(state["level"], 70)

    def test_last_writes_recorded_for_brightness(self):
        self.model.turn_on(50)
        self.port.writes.clear()
        self.model.set_level(80)
        self.assertEqual(self.model.last_writes, self.port.writes)


class TestMoonHaloModelSetColortemp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.port = FakeDdcPort()
        self.config = make_config(self.tmp_dir)
        self.model = MoonHaloModel(self.port, self.config)

    def test_keeps_remembered_brightness_step(self):
        self.model.turn_on(50)  # establishes power "on" and brightness step 5
        self.port.writes.clear()
        state = self.model.set_colortemp(7)
        expected_d9 = pack_d9(7, level_to_brightness_step(50))
        self.assertEqual(self.port.writes, [(VCP_D9, expected_d9)])
        self.assertEqual(state["colorTempStep"], 7)

    def test_no_remembered_brightness_reads_d9_and_keeps_low_byte(self):
        self.port.registers[VCP_D9] = (0x0105, 0x070A)  # low byte 5
        state = self.model.set_colortemp(7)
        expected_d9 = pack_d9(7, 5)
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_ON_VALUE), (VCP_D9, expected_d9)])
        self.assertEqual(state["brightnessStep"], 5)

    def test_failing_read_falls_back_to_default_brightness_step_and_warns(self):
        self.port.fail_reads[VCP_D9] = 3  # exhaust every retry
        with self.assertLogs(level="WARNING") as logs:
            state = self.model.set_colortemp(7)
        self.assertEqual(state["brightnessStep"], self.config.default_brightness_step)
        self.assertTrue(any("brightness step" in message for message in logs.output))

    def test_colour_while_off_writes_power_on_then_d9_in_order(self):
        self.model.turn_off()
        self.port.writes.clear()
        self.model.set_colortemp(7)
        self.assertEqual(len(self.port.writes), 2)
        self.assertEqual(self.port.writes[0], (VCP_POWER, POWER_ON_VALUE))
        self.assertEqual(self.port.writes[1][0], VCP_D9)

    def test_stage_records_step_with_no_writes_and_power_stays_off(self):
        state = self.model.set_colortemp(7, stage=True)
        self.assertEqual(self.port.writes, [])
        self.assertEqual(self.model.last_writes, [])
        self.assertEqual(state["colorTempStep"], 7)
        self.assertEqual(state["power"], "unknown")

    def test_staged_step_used_by_a_following_turn_on(self):
        self.model.set_colortemp(7, stage=True)
        self.port.writes.clear()
        state = self.model.turn_on()
        expected_d9 = pack_d9(7, level_to_brightness_step(self.config.default_on_level))
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_ON_VALUE), (VCP_D9, expected_d9)])
        self.assertEqual(state["colorTempStep"], 7)

    def test_last_writes_recorded_for_colortemp(self):
        self.model.turn_on(50)
        self.port.writes.clear()
        self.model.set_colortemp(2)
        self.assertEqual(self.model.last_writes, self.port.writes)

    def test_derives_last_level_from_brightness_when_unknown(self):
        self.port.registers[VCP_D9] = (0x0105, 0x070A)  # low byte 5
        state = self.model.set_colortemp(7)
        self.assertEqual(state["level"], brightness_step_to_level(5))


class RaisingDdcPort(FakeDdcPort):
    """A FakeDdcPort whose write_vcp always raises, to exercise the 500 path."""

    def write_vcp(self, code: int, value: int) -> None:
        raise DdcError("simulated hardware failure")


class TestMoonHaloModelWriteFailure(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.port = RaisingDdcPort()
        self.config = make_config(self.tmp_dir)
        self.model = MoonHaloModel(self.port, self.config)

    def test_turn_on_raises_and_leaves_state_unchanged(self):
        with self.assertRaises(DdcError):
            self.model.turn_on(70)
        state = self.model.status()
        self.assertEqual(state["power"], "unknown")
        self.assertFalse(self.config.state_file.exists())

    def test_turn_off_raises_and_leaves_state_unchanged(self):
        with self.assertRaises(DdcError):
            self.model.turn_off()
        state = self.model.status()
        self.assertEqual(state["power"], "unknown")
        self.assertFalse(self.config.state_file.exists())

    def test_set_colortemp_raises_and_leaves_state_unchanged(self):
        with self.assertRaises(DdcError):
            self.model.set_colortemp(7)
        state = self.model.status()
        self.assertEqual(state["power"], "unknown")
        self.assertFalse(self.config.state_file.exists())


class TestMoonHaloModelStatePersistence(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.config = make_config(self.tmp_dir)

    def test_state_survives_a_second_model_on_the_same_state_file(self):
        first_port = FakeDdcPort()
        first_model = MoonHaloModel(first_port, self.config)
        first_model.turn_on(70)

        self.assertTrue(self.config.state_file.exists())

        second_port = FakeDdcPort()
        second_model = MoonHaloModel(second_port, self.config)
        state = second_model.status()

        self.assertEqual(state["power"], "on")
        self.assertEqual(state["level"], 70)
        # the second model's own port has recorded no writes yet
        self.assertEqual(second_port.writes, [])

    def test_colortemp_state_survives_a_second_model_on_the_same_state_file(self):
        first_port = FakeDdcPort()
        first_model = MoonHaloModel(first_port, self.config)
        first_model.set_colortemp(7)

        second_port = FakeDdcPort()
        second_model = MoonHaloModel(second_port, self.config)
        state = second_model.status()

        self.assertEqual(state["colorTempStep"], 7)
        self.assertEqual(state["colorTemperature"], colortemp_step_to_kelvin(7, 2700, 6500))

    def test_missing_state_file_starts_unknown(self):
        model = MoonHaloModel(FakeDdcPort(), self.config)
        state = model.status()
        self.assertEqual(state["power"], "unknown")
        # level is 0 only when power is "off"; with no remembered state and
        # power "unknown" it falls back to the configured default.
        self.assertEqual(state["level"], self.config.default_on_level)


if __name__ == "__main__":
    unittest.main()
