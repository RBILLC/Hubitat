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
from moonhalo_bridge.model import POWER_OFF_VALUE, POWER_ON_VALUE, VCP_POWER, MoonHaloModel


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
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_ON_VALUE)])

    def test_on_with_valid_level_1(self):
        response = self.client.get("/moonhalo/on?level=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["state"]["level"], 1)
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_ON_VALUE)])

    def test_on_with_valid_level_100(self):
        response = self.client.get("/moonhalo/on?level=100")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["state"]["level"], 100)
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_ON_VALUE)])

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


class TestMoonHaloOff(HttpTestCase):
    def test_off_writes_power_off_only(self):
        response = self.client.get("/moonhalo/off")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["state"]["power"], "off")
        self.assertEqual(body["state"]["level"], 0)
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_OFF_VALUE)])


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


if __name__ == "__main__":
    unittest.main()
