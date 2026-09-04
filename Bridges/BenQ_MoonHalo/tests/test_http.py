"""Tests for moonhalo_bridge.http: the Flask test client driven against a
FakeDdcPort, exactly as the Hub would drive the real Bridge over HTTP.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from moonhalo_bridge.config import Config
from moonhalo_bridge.ddc import DdcError, FakeDdcPort
from moonhalo_bridge.http import create_app
from moonhalo_bridge.model import (
    POWER_OFF_VALUE,
    POWER_ON_VALUE,
    VCP_D9,
    VCP_POWER,
    MoonHaloModel,
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
        self.assertEqual(response.get_json(), {"ok": True})
        self.assertEqual(self.port.writes, [])


class TestMoonHaloOn(HttpTestCase):
    def test_on_default_level(self):
        response = self.client.get("/moonhalo/on")
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
        response = self.client.get("/moonhalo/on?level=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["state"]["level"], 1)
        expected_d9 = pack_d9(self.config.default_colortemp_step, level_to_brightness_step(1))
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_ON_VALUE), (VCP_D9, expected_d9)])

    def test_on_with_valid_level_100(self):
        response = self.client.get("/moonhalo/on?level=100")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["state"]["level"], 100)
        expected_d9 = pack_d9(self.config.default_colortemp_step, level_to_brightness_step(100))
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_ON_VALUE), (VCP_D9, expected_d9)])

    def test_on_with_level_70_uses_step_7(self):
        response = self.client.get("/moonhalo/on?level=70")
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
        self.client.get("/moonhalo/on?level=70")
        self.client.get("/moonhalo/off")
        response = self.client.get("/moonhalo/on")
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


class TestMoonHaloBrightness(HttpTestCase):
    def test_brightness_1_50_100_write_expected_low_byte(self):
        # establish a remembered colour step distinct from the default
        self.client.get("/moonhalo/on?level=50")
        self.port.writes.clear()
        colour_step = self.config.default_colortemp_step

        for level, expected_step in ((1, 1), (50, 5), (100, 10)):
            self.port.writes.clear()
            response = self.client.get(f"/moonhalo/brightness/{level}")
            self.assertEqual(response.status_code, 200)
            body = response.get_json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["state"]["brightnessStep"], expected_step)
            expected_d9 = pack_d9(colour_step, expected_step)
            self.assertEqual(self.port.writes, [(VCP_D9, expected_d9)])

    def test_brightness_0_behaves_as_off(self):
        self.client.get("/moonhalo/on?level=50")
        self.port.writes.clear()
        response = self.client.get("/moonhalo/brightness/0")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["state"]["power"], "off")
        self.assertEqual(body["state"]["level"], 0)
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_OFF_VALUE)])

    def test_brightness_while_off_writes_power_on_then_d9_in_order(self):
        self.client.get("/moonhalo/off")
        self.port.writes.clear()
        response = self.client.get("/moonhalo/brightness/50")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.port.writes), 2)
        self.assertEqual(self.port.writes[0], (VCP_POWER, POWER_ON_VALUE))
        self.assertEqual(self.port.writes[1][0], VCP_D9)

    def test_no_remembered_colour_step_reads_d9_and_preserves_high_byte(self):
        self.port.registers[VCP_D9] = (0x0305, 0x070A)  # high byte 3
        response = self.client.get("/moonhalo/brightness/50")
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
        self.client.get("/moonhalo/on?level=42")
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
        response = self.client.get("/moonhalo/brightness/50")
        self.assertEqual(response.status_code, 200)

        log_text = self.config.log_file.read_text(encoding="utf-8")
        lines = [line for line in log_text.splitlines() if "/moonhalo/brightness" in line]
        self.assertEqual(len(lines), 1)
        expected_d9 = pack_d9(self.config.default_colortemp_step, level_to_brightness_step(50))
        self.assertIn(str((VCP_POWER, POWER_ON_VALUE)), lines[0])
        self.assertIn(str((VCP_D9, expected_d9)), lines[0])


if __name__ == "__main__":
    unittest.main()
