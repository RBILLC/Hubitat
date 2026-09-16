"""Tests for monitor detection (issue #40): the Bridge picks the MoonHalo
monitor by what it is -- the `model(...)` in its DDC/CI capabilities, with
the D9 probe as fallback and tie-breaker -- and says so when it is absent.
Every rule runs through FakeDdcPort's per-monitor capabilities and
registers; no real monitor is involved.
"""
import unittest

from moonhalo_bridge.ddc import (
    DEFAULT_MONITOR_MODEL,
    MISS_RETRY_SECONDS,
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
RD280UG_CAPS = "(prot(monitor)type(LCD)model(RD280UG)vcp(D7 D9))"
PD2700U_CAPS = "(prot(monitor)type(LCD)model(PD2700U)vcp(10 12))"
#: The RD280UG's D9 as read on 2026-09-16 (the ticket's evidence).
RD280UG_D9 = (0x0101, 0x070A)
#: The PD2700U's D9 as read the same day: it answers, with zeros.
PD2700U_D9 = (0x0000, 0x0000)


def rd280ug(device_name: str, primary: bool = False, d9=RD280UG_D9) -> FakeMonitor:
    return FakeMonitor(
        MonitorInfo(device_name=device_name, primary=primary, description=GENERIC),
        registers={0xD9: d9, 0xD7: (0x0230, 0x0231)},
        capabilities=RD280UG_CAPS,
    )


def pd2700u(device_name: str, primary: bool = False) -> FakeMonitor:
    return FakeMonitor(
        MonitorInfo(device_name=device_name, primary=primary, description=GENERIC),
        registers={0xD9: PD2700U_D9},
        capabilities=PD2700U_CAPS,
    )


class TestFakeDdcPortPerMonitor(unittest.TestCase):
    """FakeDdcPort holds one FakeMonitor per attached monitor; the old
    single-monitor attributes stand for the first one."""

    def test_monitor_info_entries_get_the_shared_registers_and_capabilities(self):
        infos = [
            MonitorInfo(device_name=DISPLAY1, primary=True, description=GENERIC),
            MonitorInfo(device_name=DISPLAY2, primary=False, description=GENERIC),
        ]
        port = FakeDdcPort(monitors=infos, registers={0xD9: RD280UG_D9}, capabilities=RD280UG_CAPS)
        self.assertEqual(port.list_monitors(), infos)
        for device in (DISPLAY1, DISPLAY2):
            self.assertEqual(port.monitor(device).registers, {0xD9: RD280UG_D9})
            self.assertEqual(port.monitor(device).capabilities, RD280UG_CAPS)
        # each monitor owns its own dict
        port.monitor(DISPLAY1).registers[0xD7] = (1, 1)
        self.assertNotIn(0xD7, port.monitor(DISPLAY2).registers)

    def test_single_monitor_attributes_are_the_first_monitors(self):
        port = FakeDdcPort(monitors=[pd2700u(DISPLAY2, primary=True), rd280ug(DISPLAY1)])
        self.assertIs(port.registers, port.monitor(DISPLAY2).registers)
        self.assertIs(port.fail_reads, port.monitor(DISPLAY2).fail_reads)
        self.assertEqual(port.capabilities, PD2700U_CAPS)
        port.capabilities = RD280UG_CAPS
        port.fail_capabilities = 2
        self.assertEqual(port.monitor(DISPLAY2).capabilities, RD280UG_CAPS)
        self.assertEqual(port.monitor(DISPLAY2).fail_capabilities, 2)

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


class TestDetectionByModel(unittest.TestCase):
    """Detection order per the ticket: model from capabilities first."""

    def test_second_monitor_of_the_same_description_is_the_rd280ug(self):
        # The 2026-09-16 case: the PD2700U is primary, both say "Generic PnP Monitor".
        port = FakeDdcPort(monitors=[pd2700u(DISPLAY2, primary=True), rd280ug(DISPLAY1)])
        detection = port.resolve_target()
        self.assertEqual(detection.device_name, DISPLAY1)
        self.assertEqual(detection.rule, "model")
        self.assertEqual(detection.label, f"RD280UG on {DISPLAY1}")
        self.assertIsNone(detection.error)
        port.write_vcp(0xD9, 0x0405)
        self.assertEqual(port.monitor(DISPLAY1).writes, [(0xD9, 0x0405)])
        self.assertEqual(port.monitor(DISPLAY2).writes, [])

    def test_model_match_is_a_case_insensitive_substring(self):
        port = FakeDdcPort(monitors=[rd280ug(DISPLAY1, primary=True)], monitor_model="rd280")
        self.assertEqual(port.resolve_target().device_name, DISPLAY1)

    def test_default_model_is_the_rd280ug(self):
        self.assertEqual(DEFAULT_MONITOR_MODEL, "RD280UG")
        self.assertEqual(FakeDdcPort().monitor_model, "RD280UG")

    def test_logs_one_line_naming_the_choice_rule_and_candidates(self):
        port = FakeDdcPort(monitors=[pd2700u(DISPLAY2, primary=True), rd280ug(DISPLAY1)])
        with self.assertLogs("moonhalo_bridge.ddc", level="INFO") as logs:
            port.resolve_target()
        self.assertEqual(len(logs.records), 1)
        line = logs.records[0].getMessage()
        self.assertEqual(logs.records[0].levelname, "INFO")
        self.assertIn(f"RD280UG on {DISPLAY1}", line)
        self.assertIn("by model", line)
        self.assertIn(f"PD2700U ({DISPLAY2})", line)
        self.assertIn(f"RD280UG ({DISPLAY1})", line)

    def test_model_match_with_zero_d9_maximum_stands_but_warns(self):
        port = FakeDdcPort(monitors=[rd280ug(DISPLAY1, primary=True, d9=(0, 0))])
        with self.assertLogs("moonhalo_bridge.ddc", level="WARNING") as logs:
            detection = port.resolve_target()
        self.assertEqual(detection.device_name, DISPLAY1)
        self.assertEqual(detection.rule, "model")
        self.assertIn("D9", logs.records[0].getMessage())
        self.assertIn(DISPLAY1, logs.records[0].getMessage())

    def test_model_match_whose_d9_read_fails_stands_but_warns(self):
        monitor = rd280ug(DISPLAY1, primary=True)
        del monitor.registers[0xD9]
        port = FakeDdcPort(monitors=[monitor])
        with self.assertLogs("moonhalo_bridge.ddc", level="WARNING") as logs:
            detection = port.resolve_target()
        self.assertEqual(detection.device_name, DISPLAY1)
        self.assertIn("D9", logs.records[0].getMessage())

    def test_capabilities_failing_on_one_monitor_does_not_stop_the_match_on_another(self):
        broken = pd2700u(DISPLAY2, primary=True)
        broken.fail_capabilities = 99
        port = FakeDdcPort(monitors=[broken, rd280ug(DISPLAY1)])
        detection = port.resolve_target()
        self.assertEqual(detection.device_name, DISPLAY1)
        self.assertEqual(detection.rule, "model")

    def test_capabilities_read_uses_three_attempts(self):
        monitor = rd280ug(DISPLAY1, primary=True)
        monitor.fail_capabilities = 2  # the third attempt answers
        port = FakeDdcPort(monitors=[monitor])
        self.assertEqual(port.resolve_target().rule, "model")
        self.assertEqual(monitor.fail_capabilities, 0)


class TestDetectionByD9Probe(unittest.TestCase):
    """Capabilities failing on every monitor: the D9 probe decides; two
    model matches: the D9 probe breaks the tie."""

    def test_probe_picks_the_monitor_whose_d9_maximum_is_non_zero(self):
        first, second = pd2700u(DISPLAY2, primary=True), rd280ug(DISPLAY1)
        first.fail_capabilities = second.fail_capabilities = 99
        port = FakeDdcPort(monitors=[first, second])
        detection = port.resolve_target()
        self.assertEqual(detection.device_name, DISPLAY1)
        self.assertEqual(detection.rule, "d9-probe")
        self.assertEqual(detection.label, f"RD280UG on {DISPLAY1}")

    def test_probe_treats_a_failed_d9_read_as_no(self):
        first, second = rd280ug(DISPLAY2, primary=True), rd280ug(DISPLAY1)
        first.fail_capabilities = second.fail_capabilities = 99
        del first.registers[0xD9]
        port = FakeDdcPort(monitors=[first, second])
        self.assertEqual(port.resolve_target().device_name, DISPLAY1)

    def test_probe_with_several_answers_takes_the_first_and_warns(self):
        first, second = rd280ug(DISPLAY2, primary=True), rd280ug(DISPLAY1)
        first.fail_capabilities = second.fail_capabilities = 99
        port = FakeDdcPort(monitors=[first, second])
        with self.assertLogs("moonhalo_bridge.ddc", level="WARNING") as logs:
            detection = port.resolve_target()
        self.assertEqual(detection.device_name, DISPLAY2)
        self.assertEqual(detection.rule, "first-of-ambiguous")
        warnings = [r for r in logs.records if r.levelname == "WARNING"]
        self.assertEqual(len(warnings), 1)
        self.assertIn(DISPLAY1, warnings[0].getMessage())
        self.assertIn(DISPLAY2, warnings[0].getMessage())
        self.assertIn("answer the D9 probe", warnings[0].getMessage())

    def test_two_model_matches_are_broken_by_the_d9_probe(self):
        port = FakeDdcPort(
            monitors=[rd280ug(DISPLAY2, primary=True, d9=(0, 0)), rd280ug(DISPLAY1)]
        )
        detection = port.resolve_target()
        self.assertEqual(detection.device_name, DISPLAY1)
        self.assertEqual(detection.rule, "tie-break")

    def test_two_model_matches_both_answering_take_the_first_and_warn(self):
        port = FakeDdcPort(monitors=[rd280ug(DISPLAY2, primary=True), rd280ug(DISPLAY1)])
        with self.assertLogs("moonhalo_bridge.ddc", level="WARNING") as logs:
            detection = port.resolve_target()
        self.assertEqual(detection.device_name, DISPLAY2)
        self.assertEqual(detection.rule, "first-of-ambiguous")
        warnings = [r for r in logs.records if r.levelname == "WARNING"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("match model RD280UG and answer the D9 probe", warnings[0].getMessage())


class TestDetectionNotFound(unittest.TestCase):
    def test_no_matching_model_means_no_write_and_an_error_naming_the_models_seen(self):
        port = FakeDdcPort(monitors=[pd2700u(DISPLAY2, primary=True)])
        detection = port.resolve_target()
        self.assertFalse(detection.found)
        self.assertIsNone(detection.device_name)
        self.assertEqual(detection.label, "unknown")
        self.assertEqual(detection.rule, "none")
        self.assertEqual(detection.error, f"no monitor with model RD280UG among: PD2700U ({DISPLAY2})")
        with self.assertRaises(DdcError) as caught:
            port.write_vcp(0xD9, 0x0405)
        self.assertEqual(str(caught.exception), detection.error)
        self.assertEqual(port.writes, [])
        self.assertEqual(port.monitor(DISPLAY2).writes, [])

    def test_reads_fail_the_same_way(self):
        port = FakeDdcPort(monitors=[pd2700u(DISPLAY2, primary=True)])
        with self.assertRaises(DdcError):
            port.read_vcp(0xD9)
        with self.assertRaises(DdcError):
            port.read_capabilities()

    def test_error_names_unreadable_and_modelless_monitors(self):
        unreadable = pd2700u(DISPLAY3)
        unreadable.fail_capabilities = 99
        modelless = pd2700u(DISPLAY2, primary=True)
        modelless.capabilities = "(prot(monitor)type(LCD)vcp(10))"
        port = FakeDdcPort(monitors=[modelless, unreadable])
        error = port.resolve_target().error
        self.assertIn(f"no model ({DISPLAY2})", error)
        self.assertIn(f"unreadable ({DISPLAY3})", error)

    def test_capabilities_and_probe_both_failing_says_so(self):
        first, second = pd2700u(DISPLAY2, primary=True), pd2700u(DISPLAY1)
        first.fail_capabilities = second.fail_capabilities = 99
        port = FakeDdcPort(monitors=[first, second])
        detection = port.resolve_target()
        self.assertFalse(detection.found)
        self.assertIn("RD280UG", detection.error)
        self.assertIn("D9", detection.error)
        self.assertIn(DISPLAY1, detection.error)
        self.assertIn(DISPLAY2, detection.error)

    def test_no_monitors_at_all(self):
        port = FakeDdcPort(monitors=[])
        detection = port.resolve_target()
        self.assertFalse(detection.found)
        self.assertEqual(detection.error, "No display monitors found")

    def test_failure_is_logged_at_warning_with_the_reason(self):
        port = FakeDdcPort(monitors=[pd2700u(DISPLAY2, primary=True)])
        with self.assertLogs("moonhalo_bridge.ddc", level="WARNING") as logs:
            port.resolve_target()
        self.assertEqual(logs.records[0].levelname, "WARNING")
        self.assertIn("no monitor with model RD280UG", logs.records[0].getMessage())


class TestDetectionRuns(unittest.TestCase):
    """When detection runs: once per display set, again when the set of
    attached device names changes, and again after a miss."""

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
        port.fake_monitors.append(rd280ug(DISPLAY3))  # a cable swap: two RD280UGs now
        port.monitor(DISPLAY1).registers[0xD9] = (0, 0)  # and the old one stops answering D9
        with self.assertLogs("moonhalo_bridge.ddc", level="INFO"):
            port.write_vcp(0xD9, 0x0406)
        self.assertEqual(port.detection.device_name, DISPLAY3)
        self.assertEqual(port.detection.rule, "tie-break")
        self.assertEqual(port.monitor(DISPLAY3).writes, [(0xD9, 0x0406)])

    def test_a_monitor_that_goes_away_fails_the_next_call(self):
        port = FakeDdcPort(monitors=[pd2700u(DISPLAY2, primary=True), rd280ug(DISPLAY1)])
        port.write_vcp(0xD9, 0x0405)
        del port.fake_monitors[1]  # the RD280UG's cable is pulled
        with self.assertRaises(DdcError) as caught:
            port.write_vcp(0xD9, 0x0406)
        self.assertIn("no monitor with model RD280UG", str(caught.exception))
        self.assertEqual(port.target_label, "unknown")

    def test_a_miss_is_tried_again_on_the_next_call(self):
        port = FakeDdcPort(monitors=[pd2700u(DISPLAY2, primary=True)])
        with self.assertRaises(DdcError):
            port.write_vcp(0xD9, 0x0405)
        port.fake_monitors.append(rd280ug(DISPLAY1))
        port.write_vcp(0xD9, 0x0406)
        self.assertEqual(port.target_label, f"RD280UG on {DISPLAY1}")

    def test_a_miss_stands_for_the_cooldown_then_is_tried_again(self):
        # A miss costs a capabilities read per monitor (2.8 s on the
        # PD2700U), so an unchanged display set is not detected again on
        # every call: commands fail fast until the cooldown passes.
        monitor = rd280ug(DISPLAY1, primary=True)
        monitor.fail_capabilities = 3  # start-up: every attempt fails, the D9 probe is then the rule
        del monitor.registers[0xD9]  # ...and D9 fails too, so nothing is found
        port = FakeDdcPort(monitors=[monitor])
        now = [1000.0]
        port._clock = lambda: now[0]
        first = port.resolve_target()
        self.assertFalse(first.found)
        monitor.registers[0xD9] = RD280UG_D9  # the monitor would now be found
        now[0] += MISS_RETRY_SECONDS - 1
        with self.assertNoLogs("moonhalo_bridge.ddc", level="INFO"):
            self.assertIs(port.resolve_target(), first)
        with self.assertRaises(DdcError):
            port.write_vcp(0xD9, 1)
        self.assertEqual(monitor.writes, [])
        now[0] += 1
        self.assertEqual(port.resolve_target().rule, "model")

    def test_a_display_set_change_ends_the_cooldown_at_once(self):
        port = FakeDdcPort(monitors=[pd2700u(DISPLAY2, primary=True)])
        now = [1000.0]
        port._clock = lambda: now[0]
        self.assertFalse(port.resolve_target().found)
        port.fake_monitors.append(rd280ug(DISPLAY1))  # cable plugged in, same instant
        self.assertEqual(port.resolve_target().label, f"RD280UG on {DISPLAY1}")

    def test_target_label_is_unknown_before_the_first_resolution(self):
        port = FakeDdcPort()
        self.assertIsNone(port.detection)
        self.assertEqual(port.target_label, "unknown")


class TestSelectorOverride(unittest.TestCase):
    """A set monitor_selector skips detection: substring of the device
    name or description, case-insensitive, as in 0.0.7."""

    def test_selector_matches_device_name_without_reading_capabilities(self):
        first, second = pd2700u(DISPLAY2, primary=True), rd280ug(DISPLAY1)
        first.fail_capabilities = second.fail_capabilities = 99
        port = FakeDdcPort(monitors=[first, second], monitor_selector="display1")
        detection = port.resolve_target()
        self.assertEqual(detection.device_name, DISPLAY1)
        self.assertEqual(detection.rule, "selector")
        self.assertEqual(detection.label, f"{GENERIC} on {DISPLAY1}")
        self.assertEqual(first.fail_capabilities, 99)
        self.assertEqual(second.fail_capabilities, 99)

    def test_selector_matches_description(self):
        other = FakeMonitor(
            MonitorInfo(device_name=DISPLAY2, primary=True, description="BenQ PD2700U"),
            capabilities=PD2700U_CAPS,
        )
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
        self.assertTrue(Detection(DISPLAY1, "x", "model", (DISPLAY1,)).found)
        self.assertFalse(Detection(None, "unknown", "none", (), "why").found)


if __name__ == "__main__":
    unittest.main()
