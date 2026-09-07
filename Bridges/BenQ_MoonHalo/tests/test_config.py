"""Tests for moonhalo_bridge.config: the Maker API announcement keys added
for the announcer, on top of the documented defaults.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from moonhalo_bridge.config import DEFAULTS, load_config

MAKER_VALUES = {
    "hub_ip": "192.168.86.73",
    "maker_api_app_id": 12,
    "maker_api_device_id": 345,
    "maker_api_token": "secret-token",
}


class ConfigTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_dir = Path(self._tmp.name)

    def write(self, data: dict) -> Path:
        path = self.tmp_dir / "config.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path


class TestAnnounceDefaults(ConfigTestCase):
    def test_missing_file_gives_announcer_disabled(self):
        config = load_config(self.tmp_dir / "absent.json")
        self.assertIsNone(config.hub_ip)
        self.assertIsNone(config.maker_api_app_id)
        self.assertIsNone(config.maker_api_device_id)
        self.assertIsNone(config.maker_api_token)
        self.assertEqual(config.announce_seconds, 60)
        self.assertFalse(config.maker_configured)
        self.assertFalse(config.announce_enabled)

    def test_documented_defaults_include_the_announce_keys(self):
        for key in (
            "hub_ip",
            "maker_api_app_id",
            "maker_api_device_id",
            "maker_api_token",
            "announce_seconds",
            "announce_enabled",
        ):
            self.assertIn(key, DEFAULTS)

    def test_four_maker_values_enable_the_announcer(self):
        config = load_config(self.write(MAKER_VALUES))
        self.assertTrue(config.maker_configured)
        self.assertTrue(config.announce_enabled)
        # ids are carried as strings whatever the JSON type
        self.assertEqual(config.maker_api_app_id, "12")
        self.assertEqual(config.maker_api_device_id, "345")
        self.assertEqual(config.maker_api_token, "secret-token")

    def test_missing_one_maker_value_leaves_the_announcer_disabled(self):
        for key in MAKER_VALUES:
            data = dict(MAKER_VALUES)
            del data[key]
            config = load_config(self.write(data))
            self.assertFalse(config.maker_configured, key)
            self.assertFalse(config.announce_enabled, key)

    def test_explicit_false_disables_even_when_configured(self):
        config = load_config(self.write({**MAKER_VALUES, "announce_enabled": False}))
        self.assertTrue(config.maker_configured)
        self.assertFalse(config.announce_enabled)

    def test_explicit_true_without_values_stays_true_but_unconfigured(self):
        config = load_config(self.write({"announce_enabled": True}))
        self.assertTrue(config.announce_enabled)
        self.assertFalse(config.maker_configured)

    def test_announce_seconds_is_read_as_int(self):
        config = load_config(self.write({**MAKER_VALUES, "announce_seconds": "30"}))
        self.assertEqual(config.announce_seconds, 30)

    def test_announce_seconds_below_one_is_rejected(self):
        for value in (0, -5):
            with self.assertRaises(ValueError):
                load_config(self.write({**MAKER_VALUES, "announce_seconds": value}))


class TestTransitionSeconds(ConfigTestCase):
    def test_missing_file_defaults_to_0_6(self):
        config = load_config(self.tmp_dir / "absent.json")
        self.assertEqual(config.transition_seconds, 0.6)

    def test_documented_default_present(self):
        self.assertIn("transition_seconds", DEFAULTS)
        self.assertEqual(DEFAULTS["transition_seconds"], 0.6)

    def test_boundary_values_0_and_60_accepted(self):
        config = load_config(self.write({"transition_seconds": 0}))
        self.assertEqual(config.transition_seconds, 0.0)
        config = load_config(self.write({"transition_seconds": 60}))
        self.assertEqual(config.transition_seconds, 60.0)

    def test_fractional_value_accepted(self):
        config = load_config(self.write({"transition_seconds": 0.3}))
        self.assertEqual(config.transition_seconds, 0.3)

    def test_below_zero_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            load_config(self.write({"transition_seconds": -0.1}))
        self.assertIn("transition_seconds", str(ctx.exception))

    def test_above_60_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            load_config(self.write({"transition_seconds": 60.1}))
        self.assertIn("transition_seconds", str(ctx.exception))

    def test_non_numeric_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            load_config(self.write({"transition_seconds": "abc"}))
        self.assertIn("transition_seconds", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
