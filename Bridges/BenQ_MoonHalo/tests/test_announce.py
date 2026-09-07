"""Tests for moonhalo_bridge.announce: the Maker API announcer driven with a
fake HTTP sender, a fake LAN address source and a fake clock, so no network
traffic and no waiting happen here.
"""
from __future__ import annotations

import logging
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Optional

from moonhalo_bridge.announce import (
    Announcer,
    FakeSender,
    build_announce_url,
    lan_address_for,
    redact,
)
from moonhalo_bridge.config import Config

TOKEN = "s3cret-t0ken"


def make_config(tmp_dir: Path, **overrides) -> Config:
    values = dict(
        host="0.0.0.0",
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
        hub_ip="192.168.86.73",
        maker_api_app_id="12",
        maker_api_device_id="345",
        maker_api_token=TOKEN,
        announce_seconds=60,
        announce_enabled=True,
    )
    values.update(overrides)
    return Config(**values)


class FakeAddressSource:
    """Returns a settable LAN address, or raises OSError when `error` is set."""

    def __init__(self, ip: str = "192.168.86.93"):
        self.ip = ip
        self.error: Optional[str] = None
        self.calls = 0

    def __call__(self, hub_ip: str) -> str:
        self.calls += 1
        if self.error:
            raise OSError(self.error)
        return self.ip


class AnnouncerTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_dir = Path(self._tmp.name)
        self.config = make_config(self.tmp_dir)
        self.sender = FakeSender()
        self.source = FakeAddressSource()
        self.logger = logging.getLogger("test.announce")
        self.logger.addHandler(logging.NullHandler())  # keep warnings off stderr
        self.announcer = Announcer(
            self.config, sender=self.sender, address_source=self.source, logger=self.logger
        )

    def expected_url(self, ip: str) -> str:
        return build_announce_url("192.168.86.73", "12", "345", ip, 5000, TOKEN)


class TestBuildAnnounceUrl(unittest.TestCase):
    def test_maker_api_command_url_with_comma_separated_arguments(self):
        # Maker API takes several command parameters as comma-separated
        # secondary values (Hubitat staff, community.hubitat.com/t/25634).
        url = build_announce_url("192.168.86.73", "12", "345", "192.168.86.93", 5000, "tok")
        self.assertEqual(
            url,
            "http://192.168.86.73/apps/api/12/devices/345/setBridgeAddress/192.168.86.93,5000?access_token=tok",
        )

    def test_token_is_url_encoded(self):
        url = build_announce_url("h", "1", "2", "10.0.0.1", 80, "a b/c")
        self.assertTrue(url.endswith("?access_token=a%20b%2Fc"))


class TestRedact(unittest.TestCase):
    def test_token_replaced(self):
        self.assertEqual(
            redact("failed for ?access_token=abc", "abc"), "failed for ?access_token=[redacted]"
        )

    def test_empty_token_leaves_text_alone(self):
        self.assertEqual(redact("plain", ""), "plain")


class TestAnnounceOnStart(AnnouncerTestCase):
    def test_first_tick_announces_immediately(self):
        sent = self.announcer.tick(now=1000.0)
        self.assertTrue(sent)
        self.assertEqual(self.sender.urls, [self.expected_url("192.168.86.93")])

    def test_first_announcement_logs_the_address_at_info(self):
        with self.assertLogs(self.logger, level="DEBUG") as captured:
            self.announcer.tick(now=1000.0)
        self.assertTrue(
            any(
                record.levelno == logging.INFO and "192.168.86.93:5000" in record.getMessage()
                for record in captured.records
            )
        )

    def test_disabled_announcer_never_sends(self):
        announcer = Announcer(
            make_config(self.tmp_dir, announce_enabled=False),
            sender=self.sender,
            address_source=self.source,
            logger=self.logger,
        )
        self.assertFalse(announcer.enabled)
        self.assertFalse(announcer.tick(now=1000.0))
        self.assertEqual(self.sender.urls, [])

    def test_enabled_but_unconfigured_never_sends(self):
        announcer = Announcer(
            make_config(self.tmp_dir, maker_api_token=None),
            sender=self.sender,
            address_source=self.source,
            logger=self.logger,
        )
        self.assertFalse(announcer.enabled)
        self.assertFalse(announcer.tick(now=1000.0))
        self.assertEqual(self.sender.urls, [])


class TestAnnounceOnInterval(AnnouncerTestCase):
    def test_nothing_sent_before_the_interval_elapses(self):
        self.announcer.tick(now=1000.0)
        self.assertFalse(self.announcer.tick(now=1005.0))
        self.assertFalse(self.announcer.tick(now=1059.9))
        self.assertEqual(len(self.sender.urls), 1)

    def test_sent_again_once_the_interval_elapses(self):
        self.announcer.tick(now=1000.0)
        self.assertTrue(self.announcer.tick(now=1060.0))
        self.assertEqual(len(self.sender.urls), 2)
        self.assertEqual(self.sender.urls[1], self.expected_url("192.168.86.93"))

    def test_unchanged_repeat_logs_at_debug_only(self):
        self.announcer.tick(now=1000.0)
        with self.assertLogs(self.logger, level="DEBUG") as captured:
            self.announcer.tick(now=1060.0)
        self.assertTrue(all(record.levelno == logging.DEBUG for record in captured.records))


class TestAnnounceOnChange(AnnouncerTestCase):
    def test_address_change_is_announced_before_the_interval(self):
        self.announcer.tick(now=1000.0)
        self.source.ip = "192.168.86.115"
        self.assertTrue(self.announcer.tick(now=1005.0))
        self.assertEqual(self.sender.urls[-1], self.expected_url("192.168.86.115"))

    def test_address_change_logs_at_info(self):
        self.announcer.tick(now=1000.0)
        self.source.ip = "192.168.86.115"
        with self.assertLogs(self.logger, level="INFO") as captured:
            self.announcer.tick(now=1005.0)
        self.assertIn("192.168.86.115:5000", captured.output[0])

    def test_lookup_failure_warns_once_then_debug_and_retries_next_tick(self):
        self.source.error = "network unreachable"
        with self.assertLogs(self.logger, level="DEBUG") as captured:
            self.assertFalse(self.announcer.tick(now=1000.0))
            self.assertFalse(self.announcer.tick(now=1005.0))
        levels = [record.levelno for record in captured.records]
        self.assertEqual(levels, [logging.WARNING, logging.DEBUG])
        self.assertEqual(self.sender.urls, [])
        self.source.error = None
        self.assertTrue(self.announcer.tick(now=1010.0))

    def test_specific_host_is_announced_as_typed(self):
        announcer = Announcer(
            make_config(self.tmp_dir, host="192.168.86.50"),
            sender=self.sender,
            address_source=self.source,
            logger=self.logger,
        )
        self.assertTrue(announcer.tick(now=1000.0))
        self.assertEqual(self.source.calls, 0)
        self.assertEqual(self.sender.urls, [self.expected_url("192.168.86.50")])

    def test_wildcard_hosts_use_the_route_to_the_hub(self):
        for host in ("0.0.0.0", "", "::"):
            sender = FakeSender()
            announcer = Announcer(
                make_config(self.tmp_dir, host=host),
                sender=sender,
                address_source=self.source,
                logger=self.logger,
            )
            announcer.tick(now=1000.0)
            self.assertEqual(sender.urls, [self.expected_url("192.168.86.93")], host)


class TestAnnounceFailures(AnnouncerTestCase):
    def test_send_failure_does_not_raise_and_warns_once(self):
        self.sender.fail = True
        with self.assertLogs(self.logger, level="DEBUG") as captured:
            self.assertFalse(self.announcer.tick(now=1000.0))
            self.assertFalse(self.announcer.tick(now=1060.0))
            self.assertFalse(self.announcer.tick(now=1120.0))
        warnings = [record for record in captured.records if record.levelno == logging.WARNING]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(len(self.sender.urls), 3)

    def test_send_failure_retries_on_the_interval_not_every_tick(self):
        self.sender.fail = True
        self.announcer.tick(now=1000.0)
        self.assertFalse(self.announcer.tick(now=1005.0))
        self.assertEqual(len(self.sender.urls), 1)
        self.announcer.tick(now=1060.0)
        self.assertEqual(len(self.sender.urls), 2)

    def test_recovery_after_failure_logs_at_info(self):
        self.sender.fail = True
        self.announcer.tick(now=1000.0)
        self.sender.fail = False
        with self.assertLogs(self.logger, level="INFO") as captured:
            self.assertTrue(self.announcer.tick(now=1060.0))
        self.assertIn("192.168.86.93:5000", captured.output[0])

    def test_token_never_appears_in_log_lines(self):
        self.sender.fail = True
        self.sender.error_text = f"HTTP Error 401 for ?access_token={TOKEN}"
        with self.assertLogs(self.logger, level="DEBUG") as captured:
            self.announcer.tick(now=1000.0)
            self.announcer.tick(now=1060.0)
            self.sender.fail = False
            self.announcer.tick(now=1120.0)
            self.source.ip = "192.168.86.115"
            self.announcer.tick(now=1125.0)
        for line in captured.output:
            self.assertNotIn(TOKEN, line)
        self.assertTrue(any("[redacted]" in line for line in captured.output))


class TestLanAddressFor(unittest.TestCase):
    def test_route_to_loopback_is_loopback(self):
        # No packet is sent: a connected UDP socket only picks the route.
        self.assertEqual(lan_address_for("127.0.0.1"), "127.0.0.1")

    def test_invalid_hub_ip_raises_oserror(self):
        with self.assertRaises(OSError):
            lan_address_for("not-an-address")


class TestStartAnnouncer(AnnouncerTestCase):
    """cli.start_announcer: the wiring decisions, with the output captured."""

    def start(self, **overrides):
        import io

        from moonhalo_bridge.cli import start_announcer

        out = io.StringIO()
        announcer = start_announcer(make_config(self.tmp_dir, **overrides), out)
        if announcer is not None:
            announcer.stop()
        return announcer, out.getvalue()

    def test_disabled_returns_none_silently(self):
        announcer, output = self.start(announce_enabled=False)
        self.assertIsNone(announcer)
        self.assertEqual(output, "")

    def test_unconfigured_warns_and_returns_none(self):
        announcer, output = self.start(maker_api_token=None)
        self.assertIsNone(announcer)
        self.assertIn("warning:", output)
        self.assertIn("maker_api_token", output)

    def test_loopback_host_warns_and_returns_none(self):
        announcer, output = self.start(host="127.0.0.1")
        self.assertIsNone(announcer)
        self.assertIn("cannot reach", output)

    def test_configured_starts_and_reports(self):
        announcer, output = self.start(hub_ip="127.0.0.1")
        self.assertIsNotNone(announcer)
        self.assertIn("Announcing the Bridge address to hub 127.0.0.1 every 60s", output)


class TestRunLoop(AnnouncerTestCase):
    def test_start_announces_then_stops_cleanly(self):
        announcer = Announcer(
            self.config,
            sender=self.sender,
            address_source=self.source,
            logger=self.logger,
            check_seconds=0.01,
        )
        thread = announcer.start()
        self.assertIsInstance(thread, threading.Thread)
        self.assertTrue(thread.daemon)
        pause = threading.Event()
        for _ in range(100):
            if self.sender.urls:
                break
            pause.wait(0.01)
        announcer.stop()
        thread.join(timeout=1.0)
        self.assertFalse(thread.is_alive())
        self.assertGreaterEqual(len(self.sender.urls), 1)


if __name__ == "__main__":
    unittest.main()
