"""Tests for moonhalo_bridge.http: the Flask test client driven against a
FakeDdcPort, exactly as the Hub would drive the real Bridge over HTTP.
"""
from __future__ import annotations

import tempfile
import unittest

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


class TestMoonHaloColortemp(HttpTestCase):
    def test_kelvin_2700_4600_6500_produce_steps_1_4_7(self):
        for kelvin, expected_step in ((2700, 1), (4600, 4), (6500, 7)):
            self.client.get("/moonhalo/on?level=50")
            self.port.writes.clear()
            response = self.client.get(f"/moonhalo/colortemp/{kelvin}")
            self.assertEqual(response.status_code, 200)
            body = response.get_json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["state"]["colorTempStep"], expected_step)

    def test_bare_steps_1_to_7_pass_through(self):
        for step in range(1, 8):
            self.client.get("/moonhalo/on?level=50")
            self.port.writes.clear()
            response = self.client.get(f"/moonhalo/colortemp/{step}")
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

        response = client.get("/moonhalo/colortemp/2700")
        self.assertEqual(response.get_json()["state"]["colorTempStep"], 7)

        response = client.get("/moonhalo/colortemp/6500")
        self.assertEqual(response.get_json()["state"]["colorTempStep"], 1)

    def test_invert_status_kelvin_consistent(self):
        config = make_config(self.tmp_dir, invert_colortemp=True, state_file=self.tmp_dir / "inv2.json")
        model = MoonHaloModel(FakeDdcPort(), config)
        app = create_app(model, config)
        app.testing = True
        client = app.test_client()

        client.get("/moonhalo/colortemp/2700")
        status = client.get("/moonhalo/status").get_json()
        self.assertEqual(status["state"]["colorTempStep"], 7)
        self.assertEqual(
            status["state"]["colorTemperature"],
            colortemp_step_to_kelvin(7, config.kelvin_min, config.kelvin_max, invert=True),
        )

    def test_d9_write_keeps_remembered_brightness_step(self):
        self.client.get("/moonhalo/on?level=50")
        self.port.writes.clear()
        response = self.client.get("/moonhalo/colortemp/7")
        expected_d9 = pack_d9(7, level_to_brightness_step(50))
        self.assertEqual(self.port.writes, [(VCP_D9, expected_d9)])
        self.assertEqual(response.get_json()["state"]["colorTempStep"], 7)

    def test_no_remembered_brightness_reads_d9_and_keeps_low_byte(self):
        self.port.registers[VCP_D9] = (0x0105, 0x070A)  # low byte 5
        response = self.client.get("/moonhalo/colortemp/7")
        body = response.get_json()
        self.assertEqual(body["state"]["brightnessStep"], 5)
        expected_d9 = pack_d9(7, 5)
        self.assertEqual(self.port.writes, [(VCP_POWER, POWER_ON_VALUE), (VCP_D9, expected_d9)])

    def test_failing_read_falls_back_to_default_brightness_step_with_warning(self):
        self.port.fail_reads[VCP_D9] = 3  # exhaust every retry
        with self.assertLogs(level="WARNING") as logs:
            response = self.client.get("/moonhalo/colortemp/7")
        body = response.get_json()
        self.assertEqual(body["state"]["brightnessStep"], self.config.default_brightness_step)
        self.assertTrue(any("brightness step" in message for message in logs.output))

    def test_colour_while_off_writes_d7_then_d9_in_order(self):
        self.client.get("/moonhalo/off")
        self.port.writes.clear()
        response = self.client.get("/moonhalo/colortemp/7")
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

        response = self.client.get("/moonhalo/on")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.port.writes), 2)
        expected_d9 = pack_d9(staged_step, level_to_brightness_step(self.config.default_on_level))
        self.assertEqual(self.port.writes[1], (VCP_D9, expected_d9))

    def test_status_after_restart_reports_same_step_and_kelvin(self):
        self.client.get("/moonhalo/colortemp/6500")
        expected = self.client.get("/moonhalo/status").get_json()["state"]

        second_model = MoonHaloModel(FakeDdcPort(), self.config)
        second_app = create_app(second_model, self.config)
        second_app.testing = True
        second_client = second_app.test_client()
        actual = second_client.get("/moonhalo/status").get_json()["state"]

        self.assertEqual(actual["colorTempStep"], expected["colorTempStep"])
        self.assertEqual(actual["colorTemperature"], expected["colorTemperature"])


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
        response = self.client.get("/moonhalo/brightness/50")
        self.assertEqual(response.status_code, 200)

        log_text = self.config.log_file.read_text(encoding="utf-8")
        lines = [line for line in log_text.splitlines() if "/moonhalo/brightness" in line]
        self.assertEqual(len(lines), 1)
        expected_d9 = pack_d9(self.config.default_colortemp_step, level_to_brightness_step(50))
        self.assertIn(str((VCP_POWER, POWER_ON_VALUE)), lines[0])
        self.assertIn(str((VCP_D9, expected_d9)), lines[0])

    def test_colortemp_log_line_contains_the_real_writes(self):
        response = self.client.get("/moonhalo/colortemp/7")
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
