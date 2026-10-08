"""Tests for monitor detection (issues #40 and #44): the Bridge picks the
MoonHalo monitor by its EDID identity -- the product `BNQ80BB` Windows
cached when the monitor was plugged in -- with no DDC/CI call, and says
which monitors are attached when it is absent. Every rule runs through
FakeDdcPort's per-monitor identity; no real monitor is involved.
"""
import unittest

from moonhalo_bridge.ddc import (
    DEFAULT_MONITOR_PRODUCT,
    DdcError,
    Detection,
    FakeDdcPort,
    FakeMonitor,
    MonitorInfo,
)

DISPLAY1 = "\\\\.\\DISPLAY1"
DISPLAY2 = "\\\\.\\DISPLAY2"
DISPLAY3 = "\\\\.\\DISPLAY3"
GENERIC = "Generic PnP Monitor"
#: The RD280UG's D9 as read on 2026-09-16.
RD280UG_D9 = (0x0101, 0x070A)
#: The PD2700U's D9 as read the same day: it answers, with zeros.
PD2700U_D9 = (0x0000, 0x0000)
#: The two monitors' EDID identities as cached on this PC (2026-10-08).
RD280UG_IDENTITY = dict(product="BNQ80BB", name="BenQ RD280UG", serial="EMS6T00258087")
PD2700U_IDENTITY = dict(product="BNQ802E", name="BenQ PD2700U", serial="ETSCL07402SL0")
#: 0xC0262582, ERROR_GRAPHICS_I2C_ERROR_TRANSMITTING_DATA, as GetLastError returns it.
I2C_ERROR = -1071241854

NOT_ATTACHED = "BenQ RD280UG (BNQ80BB) is not attached: asleep, off or unplugged; attached: "


def rd280ug(device_name: str, primary: bool = False, **identity) -> FakeMonitor:
    return FakeMonitor(
        MonitorInfo(device_name, primary, GENERIC, **{**RD280UG_IDENTITY, **identity}),
        registers={0xD9: RD280UG_D9, 0xD7: (0x0230, 0x0231)},
    )


def pd2700u(device_name: str, primary: bool = False) -> FakeMonitor:
    return FakeMonitor(
        MonitorInfo(device_name, primary, GENERIC, **PD2700U_IDENTITY),
        registers={0xD9: PD2700U_D9},
    )


def no_edid(device_name: str, primary: bool = False) -> FakeMonitor:
    """A display whose registry key has no EDID value."""
    return FakeMonitor(MonitorInfo(device_name, primary, GENERIC))


class TestFakeDdcPortPerMonitor(unittest.TestCase):
    """FakeDdcPort holds one FakeMonitor per attached monitor; the old
    single-monitor attributes stand for the first one."""

    def test_monitor_info_entries_get_the_shared_registers(self):
        infos = [
            MonitorInfo(DISPLAY1, True, GENERIC, **RD280UG_IDENTITY),
            MonitorInfo(DISPLAY2, False, GENERIC, **PD2700U_IDENTITY),
        ]
        port = FakeDdcPort(monitors=infos, registers={0xD9: RD280UG_D9})
        self.assertEqual(port.list_monitors(), infos)
        for device in (DISPLAY1, DISPLAY2):
            self.assertEqual(port.monitor(device).registers, {0xD9: RD280UG_D9})
        # each monitor owns its own dict
        port.monitor(DISPLAY1).registers[0xD7] = (1, 1)
        self.assertNotIn(0xD7, port.monitor(DISPLAY2).registers)

    def test_single_monitor_attributes_are_the_first_monitors(self):
        port = FakeDdcPort(monitors=[pd2700u(DISPLAY2, primary=True), rd280ug(DISPLAY1)])
        self.assertIs(port.registers, port.monitor(DISPLAY2).registers)
        self.assertIs(port.fail_reads, port.monitor(DISPLAY2).fail_reads)
        port.fail_reads[0xD9] = 2
        self.assertEqual(port.monitor(DISPLAY2).fail_reads, {0xD9: 2})

    def test_the_default_monitor_carries_the_rd280ug_identity(self):
        # So a bare FakeDdcPort() (and --dry-run) is detected by edid like
        # the real monitor.
        port = FakeDdcPort()
        (monitor,) = port.list_monitors()
        self.assertEqual(monitor.product, DEFAULT_MONITOR_PRODUCT)
        self.assertEqual(monitor.name, "BenQ RD280UG")
        self.assertIsInstance(monitor.serial, str)
        self.assertEqual(port.resolve_target().rule, "edid")

    def test_writes_are_recorded_per_monitor_and_port_wide(self):
        port = FakeDdcPort(monitors=[pd2700u(DISPLAY2, primary=True), rd280ug(DISPLAY1)])
        port.write_vcp(0xD7, 0x0220)
        self.assertEqual(port.writes, [(0xD7, 0x0220)])
        self.assertEqual(port.monitor(DISPLAY1).writes, [(0xD7, 0x0220)])
        self.assertEqual(port.monitor(DISPLAY2).writes, [])

    def test_unknown_device_raises(self):
        port = FakeDdcPort()
        with self.assertRaises(KeyError):
            port.monitor("nope")


class TestDetectionByEdid(unittest.TestCase):
    """The one monitor whose EDID product is `monitor_product` wins,
    whatever port it is on and whether or not it is primary."""

    def test_found_whatever_its_device_name_and_whether_or_not_primary(self):
        layouts = {
            "not primary, listed second": [pd2700u(DISPLAY2, primary=True), rd280ug(DISPLAY1)],
            "primary, listed first": [rd280ug(DISPLAY2, primary=True), pd2700u(DISPLAY1)],
            "after the 2026-10-07 swap": [pd2700u(DISPLAY1, primary=True), rd280ug(DISPLAY2)],
            "alone on a third port": [rd280ug(DISPLAY3)],
        }
        for layout, monitors in layouts.items():
            with self.subTest(layout=layout):
                port = FakeDdcPort(monitors=monitors)
                expected = next(m for m in monitors if m.info.product == "BNQ80BB").device_name
                detection = port.resolve_target()
                self.assertEqual(detection.device_name, expected)
                self.assertEqual(detection.rule, "edid")
                self.assertEqual(detection.label, f"BenQ RD280UG on {expected}")
                self.assertIsNone(detection.error)
                port.write_vcp(0xD9, 0x0405)
                self.assertEqual(port.monitor(expected).writes, [(0xD9, 0x0405)])
                for other in monitors:
                    if other.device_name != expected:
                        self.assertEqual(other.writes, [])

    def test_product_match_is_case_insensitive(self):
        port = FakeDdcPort(monitors=[rd280ug(DISPLAY1, primary=True)], monitor_product="bnq80bb")
        self.assertEqual(port.resolve_target().rule, "edid")

    def test_default_product_is_the_rd280ug(self):
        self.assertEqual(DEFAULT_MONITOR_PRODUCT, "BNQ80BB")
        self.assertEqual(FakeDdcPort().monitor_product, "BNQ80BB")

    def test_no_ddc_ci_call_happens_during_detection(self):
        first, second = pd2700u(DISPLAY2, primary=True), rd280ug(DISPLAY1)
        del second.registers[0xD9]  # a D9 probe would fail
        port = FakeDdcPort(monitors=[first, second])
        self.assertEqual(port.resolve_target().device_name, DISPLAY1)
        self.assertEqual(port.reads, [])

    def test_logs_one_line_naming_the_choice_rule_and_candidates(self):
        port = FakeDdcPort(monitors=[pd2700u(DISPLAY2, primary=True), rd280ug(DISPLAY1)])
        with self.assertLogs("moonhalo_bridge.ddc", level="INFO") as logs:
            port.resolve_target()
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(logs.records[0].levelname, "INFO")
        self.assertEqual(
            logs.records[0].getMessage(),
            f"monitor BenQ RD280UG on {DISPLAY1} by edid; candidates: "
            f"BenQ PD2700U BNQ802E ({DISPLAY2}), BenQ RD280UG BNQ80BB ({DISPLAY1})",
        )

    def test_a_match_with_no_name_descriptor_is_labelled_by_its_product(self):
        port = FakeDdcPort(monitors=[rd280ug(DISPLAY1, primary=True, name=None)])
        detection = port.resolve_target()
        self.assertEqual(detection.label, f"BNQ80BB on {DISPLAY1}")
        self.assertEqual(detection.candidates, (f"BNQ80BB ({DISPLAY1})",))

    def test_two_rd280ugs_take_the_first_in_enumeration_order_with_one_warning(self):
        port = FakeDdcPort(monitors=[rd280ug(DISPLAY2, primary=True), rd280ug(DISPLAY1)])
        with self.assertLogs("moonhalo_bridge.ddc", level="INFO") as logs:
            detection = port.resolve_target()
        self.assertEqual(detection.device_name, DISPLAY2)
        self.assertEqual(detection.rule, "first-of-ambiguous")
        self.assertEqual(detection.label, f"BenQ RD280UG on {DISPLAY2}")
        warnings = [r for r in logs.records if r.levelname == "WARNING"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(
            warnings[0].getMessage(),
            f"2 monitors have product BNQ80BB, taking the first: "
            f"BenQ RD280UG BNQ80BB ({DISPLAY2}), BenQ RD280UG BNQ80BB ({DISPLAY1})",
        )
        port.write_vcp(0xD9, 0x0405)
        self.assertEqual(port.monitor(DISPLAY2).writes, [(0xD9, 0x0405)])
        self.assertEqual(port.monitor(DISPLAY1).writes, [])


class TestDetectionNotFound(unittest.TestCase):
    def test_pd2700u_only_is_not_attached_naming_what_is(self):
        port = FakeDdcPort(monitors=[pd2700u(DISPLAY2, primary=True)])
        detection = port.resolve_target()
        self.assertFalse(detection.found)
        self.assertIsNone(detection.device_name)
        self.assertEqual(detection.label, "unknown")
        self.assertEqual(detection.rule, "none")
        self.assertEqual(detection.error, NOT_ATTACHED + f"BenQ PD2700U BNQ802E ({DISPLAY2})")
        with self.assertRaises(DdcError) as caught:
            port.write_vcp(0xD9, 0x0405)
        self.assertEqual(str(caught.exception), detection.error)
        self.assertEqual(port.writes, [])
        self.assertEqual(port.monitor(DISPLAY2).writes, [])

    def test_reads_fail_the_same_way(self):
        port = FakeDdcPort(monitors=[pd2700u(DISPLAY2, primary=True)])
        with self.assertRaises(DdcError):
            port.read_vcp(0xD9)

    def test_a_display_with_no_edid_is_listed_as_no_edid(self):
        port = FakeDdcPort(monitors=[pd2700u(DISPLAY2, primary=True), no_edid(DISPLAY3)])
        error = port.resolve_target().error
        self.assertEqual(error, NOT_ATTACHED + f"BenQ PD2700U BNQ802E ({DISPLAY2}), no EDID ({DISPLAY3})")

    def test_a_product_other_than_the_rd280ug_is_named_by_its_code(self):
        port = FakeDdcPort(monitors=[rd280ug(DISPLAY1, primary=True)], monitor_product="BNQ802E")
        self.assertEqual(
            port.resolve_target().error,
            f"BNQ802E is not attached: asleep, off or unplugged; attached: BenQ RD280UG BNQ80BB ({DISPLAY1})",
        )
        port.fake_monitors.append(pd2700u(DISPLAY2))
        self.assertEqual(port.resolve_target().label, f"BenQ PD2700U on {DISPLAY2}")

    def test_no_monitors_at_all(self):
        port = FakeDdcPort(monitors=[])
        detection = port.resolve_target()
        self.assertFalse(detection.found)
        self.assertEqual(detection.error, "No display monitors found")

    def test_a_miss_is_logged_at_warning_once_per_reason(self):
        port = FakeDdcPort(monitors=[pd2700u(DISPLAY2, primary=True)])
        with self.assertLogs("moonhalo_bridge.ddc", level="WARNING") as logs:
            port.resolve_target()
            port.resolve_target()
            with self.assertRaises(DdcError):
                port.write_vcp(0xD9, 1)
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(logs.records[0].levelname, "WARNING")
        self.assertEqual(logs.records[0].getMessage(), "monitor not found: " + port.detection.error)
        # A different reason is logged; the same one again is not.
        port.fake_monitors.append(no_edid(DISPLAY3))
        with self.assertLogs("moonhalo_bridge.ddc", level="WARNING") as logs:
            port.resolve_target()
            port.resolve_target()
        self.assertEqual(len(logs.records), 1)
        self.assertIn(f"no EDID ({DISPLAY3})", logs.records[0].getMessage())
        # Found, then lost again: the old reason is news again.
        port.fake_monitors.append(rd280ug(DISPLAY1))
        self.assertTrue(port.resolve_target().found)
        del port.fake_monitors[2]
        with self.assertLogs("moonhalo_bridge.ddc", level="WARNING") as logs:
            port.resolve_target()
        self.assertEqual(len(logs.records), 1)


class TestDetectionRuns(unittest.TestCase):
    """When detection runs: once per display set while found, again when
    the set of attached device names changes, and on every call after a
    miss (no cooldown: a miss costs a registry read per monitor, no
    DDC/CI call)."""

    def test_same_display_set_is_not_detected_again(self):
        port = FakeDdcPort(monitors=[pd2700u(DISPLAY2, primary=True), rd280ug(DISPLAY1)])
        first = port.resolve_target()
        with self.assertNoLogs("moonhalo_bridge.ddc", level="INFO"):
            port.write_vcp(0xD9, 0x0405)
            port.write_vcp(0xD9, 0x0406)
        self.assertIs(port.detection, first)

    def test_a_changed_display_set_is_detected_again(self):
        port = FakeDdcPort(monitors=[pd2700u(DISPLAY2, primary=True), rd280ug(DISPLAY1)])
        port.write_vcp(0xD9, 0x0405)
        # The RD280UG's cable moves to another port.
        del port.fake_monitors[1]
        port.fake_monitors.append(rd280ug(DISPLAY3))
        with self.assertLogs("moonhalo_bridge.ddc", level="INFO"):
            port.write_vcp(0xD9, 0x0406)
        self.assertEqual(port.detection.device_name, DISPLAY3)
        self.assertEqual(port.detection.rule, "edid")
        self.assertEqual(port.monitor(DISPLAY3).writes, [(0xD9, 0x0406)])

    def test_a_monitor_that_goes_away_fails_the_next_call(self):
        port = FakeDdcPort(monitors=[pd2700u(DISPLAY2, primary=True), rd280ug(DISPLAY1)])
        port.write_vcp(0xD9, 0x0405)
        del port.fake_monitors[1]  # standby, off or unplugged
        with self.assertRaises(DdcError) as caught:
            port.write_vcp(0xD9, 0x0406)
        self.assertEqual(str(caught.exception), NOT_ATTACHED + f"BenQ PD2700U BNQ802E ({DISPLAY2})")
        self.assertEqual(port.target_label, "unknown")

    def test_a_miss_is_tried_again_on_the_next_call(self):
        port = FakeDdcPort(monitors=[pd2700u(DISPLAY2, primary=True)])
        with self.assertRaises(DdcError):
            port.write_vcp(0xD9, 0x0405)
        port.fake_monitors.append(rd280ug(DISPLAY1))
        port.write_vcp(0xD9, 0x0406)
        self.assertEqual(port.target_label, f"BenQ RD280UG on {DISPLAY1}")

    def test_a_miss_is_tried_again_even_when_the_display_set_is_unchanged(self):
        # No cooldown (#44): the same device names, but the display's EDID
        # is now readable; the very next call finds it.
        port = FakeDdcPort(monitors=[no_edid(DISPLAY1, primary=True)])
        self.assertFalse(port.resolve_target().found)
        port.fake_monitors[0] = rd280ug(DISPLAY1, primary=True)
        self.assertEqual(port.resolve_target().rule, "edid")
        port.write_vcp(0xD9, 1)
        self.assertEqual(port.monitor(DISPLAY1).writes, [(0xD9, 1)])

    def test_target_label_is_unknown_before_the_first_resolution(self):
        port = FakeDdcPort()
        self.assertIsNone(port.detection)
        self.assertEqual(port.target_label, "unknown")


class TestMonitorLinkErrors(unittest.TestCase):
    """A DDC/CI failure on the identified monitor names it and says the
    monitor was identified by EDID, so a stuck link reads as a stuck link
    and not as an absent monitor (#44, 2026-09-16)."""

    def test_a_failing_write_carries_the_identified_prefix_and_the_hex_code(self):
        monitor = rd280ug(DISPLAY1)
        monitor.write_error = I2C_ERROR
        port = FakeDdcPort(monitors=[pd2700u(DISPLAY2, primary=True), monitor])
        with self.assertRaises(DdcError) as caught:
            port.write_vcp(0xD9, 0x0405)
        self.assertEqual(
            str(caught.exception),
            f"BenQ RD280UG on {DISPLAY1} identified by EDID; DDC/CI not answering: "
            "SetVCPFeature failed for VCP 0xD9 (Win32 error -1071241854 = 0xC0262582)",
        )
        self.assertEqual(caught.exception.win32_error, I2C_ERROR)
        self.assertEqual(monitor.writes, [])
        # The identity is still read from Windows, not from DDC/CI: the
        # next call identifies it again, and the write fails the same way.
        with self.assertRaises(DdcError) as again:
            port.write_vcp(0xD9, 0x0405)
        self.assertEqual(str(again.exception), str(caught.exception))
        self.assertEqual(port.target_label, f"BenQ RD280UG on {DISPLAY1}")

    def test_a_failing_read_carries_the_same_prefix(self):
        monitor = rd280ug(DISPLAY1, primary=True)
        monitor.fail_reads[0xD9] = 99
        port = FakeDdcPort(monitors=[monitor])
        with self.assertRaises(DdcError) as caught:
            port.read_vcp(0xD9)
        self.assertTrue(
            str(caught.exception).startswith(
                f"BenQ RD280UG on {DISPLAY1} identified by EDID; DDC/CI not answering: "
            )
        )

    def test_a_selector_match_is_not_identified_by_edid(self):
        monitor = rd280ug(DISPLAY1, primary=True)
        monitor.write_error = I2C_ERROR
        port = FakeDdcPort(monitors=[monitor], monitor_selector="DISPLAY1")
        with self.assertRaises(DdcError) as caught:
            port.write_vcp(0xD9, 1)
        self.assertEqual(
            str(caught.exception),
            "SetVCPFeature failed for VCP 0xD9 (Win32 error -1071241854 = 0xC0262582)",
        )

    def test_win32_errors_print_the_hex_next_to_the_decimal(self):
        self.assertEqual(str(DdcError("boom", I2C_ERROR)), "boom (Win32 error -1071241854 = 0xC0262582)")
        self.assertEqual(str(DdcError("boom", 1450)), "boom (Win32 error 1450 = 0x000005AA)")
        self.assertEqual(str(DdcError("boom")), "boom")


class TestSelectorOverride(unittest.TestCase):
    """A set monitor_selector skips detection: substring of the device
    name or description, case-insensitive, as in 0.0.7."""

    def test_selector_matches_device_name_whatever_the_identity(self):
        first, second = rd280ug(DISPLAY2, primary=True), pd2700u(DISPLAY1)
        port = FakeDdcPort(monitors=[first, second], monitor_selector="display1")
        detection = port.resolve_target()
        self.assertEqual(detection.device_name, DISPLAY1)
        self.assertEqual(detection.rule, "selector")
        self.assertEqual(detection.label, f"{GENERIC} on {DISPLAY1}")
        self.assertEqual(port.reads, [])

    def test_selector_matches_description(self):
        other = FakeMonitor(MonitorInfo(DISPLAY2, True, "BenQ PD2700U", **PD2700U_IDENTITY))
        port = FakeDdcPort(monitors=[other, rd280ug(DISPLAY1)], monitor_selector="pd2700")
        self.assertEqual(port.resolve_target().device_name, DISPLAY2)

    def test_selector_that_matches_nothing_is_an_error_not_the_first_monitor(self):
        port = FakeDdcPort(monitors=[pd2700u(DISPLAY2, primary=True)], monitor_selector="DISPLAY1")
        detection = port.resolve_target()
        self.assertFalse(detection.found)
        self.assertIn("DISPLAY1", detection.error)
        with self.assertRaises(DdcError):
            port.write_vcp(0xD9, 1)

    def test_selector_is_logged_once_per_display_set(self):
        port = FakeDdcPort(monitors=[rd280ug(DISPLAY1, primary=True)], monitor_selector="DISPLAY1")
        with self.assertLogs("moonhalo_bridge.ddc", level="INFO") as logs:
            port.write_vcp(0xD9, 1)
            port.write_vcp(0xD9, 2)
        self.assertEqual(len(logs.records), 1)
        self.assertIn("by selector", logs.records[0].getMessage())


class TestDetectionValue(unittest.TestCase):
    def test_found_is_whether_a_device_was_chosen(self):
        self.assertTrue(Detection(DISPLAY1, "x", "edid", (DISPLAY1,)).found)
        self.assertFalse(Detection(None, "unknown", "none", (), "why").found)


if __name__ == "__main__":
    unittest.main()
