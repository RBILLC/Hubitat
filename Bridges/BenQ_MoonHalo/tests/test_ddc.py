"""Tests for moonhalo_bridge.ddc: the fake port and the read-retry wrapper.

No real monitor or Windows API call is involved here except the guarded
WindowsDdcPort construction test, which only loads ctypes bindings and
never touches a physical monitor handle.
"""
import sys
import unittest

from moonhalo_bridge.ddc import (
    DdcError,
    FakeDdcPort,
    MonitorInfo,
    WindowsDdcPort,
)


class TestMonitorInfo(unittest.TestCase):
    def test_fields(self):
        info = MonitorInfo(device_name="\\\\.\\DISPLAY1", primary=True, description="Generic PnP Monitor")
        self.assertEqual(info.device_name, "\\\\.\\DISPLAY1")
        self.assertTrue(info.primary)
        self.assertEqual(info.description, "Generic PnP Monitor")


class TestFakeDdcPortBasics(unittest.TestCase):
    def test_list_monitors_defaults(self):
        port = FakeDdcPort()
        monitors = port.list_monitors()
        self.assertEqual(len(monitors), 1)
        self.assertTrue(monitors[0].primary)

    def test_list_monitors_custom(self):
        monitors = [MonitorInfo(device_name="DEV1", primary=True, description="Test Monitor")]
        port = FakeDdcPort(monitors=monitors)
        self.assertEqual(port.list_monitors(), monitors)
        # returned list must not be the same object (defensive copy)
        self.assertIsNot(port.list_monitors(), monitors)

    def test_read_vcp_from_registers(self):
        port = FakeDdcPort(registers={0xD9: (0x0105, 0x070A)})
        current, maximum = port.read_vcp(0xD9)
        self.assertEqual(current, 0x0105)
        self.assertEqual(maximum, 0x070A)

    def test_read_vcp_unknown_code_raises(self):
        port = FakeDdcPort(registers={0xD9: (1, 10)}, retry_delay=0.0)
        with self.assertRaises(DdcError):
            port.read_vcp(0x99)

    def test_write_vcp_records_in_order(self):
        port = FakeDdcPort(registers={0xD7: (0x0230, 0x0231)})
        port.write_vcp(0xD7, 0x0210)
        port.write_vcp(0xD7, 0x0220)
        self.assertEqual(port.writes, [(0xD7, 0x0210), (0xD7, 0x0220)])

    def test_write_vcp_updates_registers_preserving_max(self):
        port = FakeDdcPort(registers={0xD7: (0x0230, 0x0231)})
        port.write_vcp(0xD7, 0x0220)
        current, maximum = port.read_vcp(0xD7)
        self.assertEqual(current, 0x0220)
        self.assertEqual(maximum, 0x0231)

    def test_write_vcp_unknown_code_creates_register(self):
        port = FakeDdcPort()
        port.write_vcp(0x99, 42)
        current, maximum = port.read_vcp(0x99)
        self.assertEqual(current, 42)
        self.assertEqual(maximum, 42)


class TestReadRetryBehaviour(unittest.TestCase):
    """The retry wrapper is shared code exercised here through FakeDdcPort,
    per the ticket's acceptance criteria for the port wrapper's retry
    behaviour."""

    def test_succeeds_after_transient_failures_within_retry_budget(self):
        port = FakeDdcPort(registers={0xD9: (1, 10)}, retry_delay=0.0)
        port.fail_reads[0xD9] = 2  # fails twice, succeeds on the 3rd attempt
        current, maximum = port.read_vcp(0xD9)
        self.assertEqual((current, maximum), (1, 10))
        self.assertEqual(port.fail_reads[0xD9], 0)

    def test_raises_after_exhausting_all_three_attempts(self):
        port = FakeDdcPort(registers={0xD9: (1, 10)}, retry_delay=0.0)
        port.fail_reads[0xD9] = 5  # more failures than the retry budget
        with self.assertRaises(DdcError):
            port.read_vcp(0xD9)
        # exactly 3 attempts should have been made (3 failures consumed)
        self.assertEqual(port.fail_reads[0xD9], 2)

    def test_default_retries_is_three(self):
        port = FakeDdcPort(registers={0xD9: (1, 10)}, retry_delay=0.0)
        self.assertEqual(port._retries, 3)


class TestDdcError(unittest.TestCase):
    def test_message_without_win32_error(self):
        error = DdcError("boom")
        self.assertEqual(str(error), "boom")
        self.assertIsNone(error.win32_error)

    def test_message_with_win32_error(self):
        error = DdcError("boom", win32_error=1450)
        self.assertIn("boom", str(error))
        self.assertIn("1450", str(error))
        self.assertEqual(error.win32_error, 1450)


@unittest.skipUnless(sys.platform.startswith("win"), "WindowsDdcPort requires Windows ctypes bindings")
class TestWindowsDdcPortConstruction(unittest.TestCase):
    """Only verifies the lazy Windows-only import path loads cleanly; makes
    no physical monitor handle call."""

    def test_constructs_without_touching_hardware(self):
        port = WindowsDdcPort()
        self.assertIsNone(port.monitor_selector)
        self.assertTrue(hasattr(port, "_dxva2"))
        self.assertTrue(hasattr(port, "_user32"))

    def test_accepts_monitor_selector(self):
        port = WindowsDdcPort(monitor_selector="Generic")
        self.assertEqual(port.monitor_selector, "Generic")


if __name__ == "__main__":
    unittest.main()
