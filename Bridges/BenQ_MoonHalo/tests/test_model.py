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
    VCP_POWER,
    MoonHaloModel,
    colortemp_step_to_kelvin,
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
            self.assertIsNone(config.log_file)
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


class TestMoonHaloModelPower(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.port = FakeDdcPort()
        self.config = make_config(self.tmp_dir)
        self.model = MoonHaloModel(self.port, self.config)

    def test_turn_on_writes_exactly_power_on(self):
        state = self.model.turn_on()
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_ON_VALUE)])
        self.assertEqual(state["power"], "on")
        self.assertEqual(state["level"], self.config.default_on_level)

    def test_turn_on_with_level_records_that_level(self):
        state = self.model.turn_on(70)
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_ON_VALUE)])
        self.assertEqual(state["level"], 70)

    def test_turn_off_writes_exactly_power_off(self):
        self.model.turn_on(70)
        state = self.model.turn_off()
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_ON_VALUE), (VCP_POWER, POWER_OFF_VALUE)])
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

    def test_missing_state_file_starts_unknown(self):
        model = MoonHaloModel(FakeDdcPort(), self.config)
        state = model.status()
        self.assertEqual(state["power"], "unknown")
        # level is 0 only when power is "off"; with no remembered state and
        # power "unknown" it falls back to the configured default.
        self.assertEqual(state["level"], self.config.default_on_level)


if __name__ == "__main__":
    unittest.main()
