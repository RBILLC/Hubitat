"""Tests for moonhalo_bridge.access: MAC normalisation, the ARP lookup
interface, and the AccessPolicy decision rules.
"""
from __future__ import annotations

import subprocess
import unittest

from moonhalo_bridge.access import (
    AccessPolicy,
    Decision,
    FakeArpTable,
    WindowsArpTable,
    normalize_mac,
    parse_arp_output,
)


class TestNormalizeMac(unittest.TestCase):
    def test_dash_separated_upper_case(self):
        self.assertEqual(normalize_mac("EC-B5-FA-82-2D-1D"), "ec:b5:fa:82:2d:1d")

    def test_colon_separated_lower_case(self):
        self.assertEqual(normalize_mac("ec:b5:fa:82:2d:1d"), "ec:b5:fa:82:2d:1d")

    def test_dot_grouped(self):
        self.assertEqual(normalize_mac("ecb5.fa82.2d1d"), "ec:b5:fa:82:2d:1d")

    def test_mixed_case(self):
        self.assertEqual(normalize_mac("Ec:B5:fA:82:2d:1D"), "ec:b5:fa:82:2d:1d")

    def test_surrounding_whitespace(self):
        self.assertEqual(normalize_mac("  ec:b5:fa:82:2d:1d  "), "ec:b5:fa:82:2d:1d")

    def test_no_separators(self):
        self.assertEqual(normalize_mac("ecb5fa822d1d"), "ec:b5:fa:82:2d:1d")

    def test_too_short_raises(self):
        with self.assertRaises(ValueError):
            normalize_mac("ec:b5:fa:82:2d")

    def test_too_long_raises(self):
        with self.assertRaises(ValueError):
            normalize_mac("ec:b5:fa:82:2d:1d:ff")

    def test_non_hex_raises(self):
        with self.assertRaises(ValueError):
            normalize_mac("zz:b5:fa:82:2d:1d")

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            normalize_mac("")


class TestFakeArpTable(unittest.TestCase):
    def test_lookup_normalises_stored_mac(self):
        table = FakeArpTable({"192.168.86.27": "EC-B5-FA-82-2D-1D"})
        self.assertEqual(table.lookup("192.168.86.27"), "ec:b5:fa:82:2d:1d")

    def test_lookup_missing_ip_returns_none(self):
        table = FakeArpTable({})
        self.assertIsNone(table.lookup("192.168.86.99"))


class TestParseArpOutput(unittest.TestCase):
    def test_found_line(self):
        output = (
            "\nInterface: 192.168.86.93 --- 0x8\n"
            "  Internet Address      Physical Address      Type\n"
            "  192.168.86.27         ec-b5-fa-82-2d-1d     dynamic\n"
        )
        self.assertEqual(parse_arp_output(output, "192.168.86.27"), "ec:b5:fa:82:2d:1d")

    def test_no_arp_entries_found(self):
        output = "No ARP Entries Found\n"
        self.assertIsNone(parse_arp_output(output, "192.168.86.27"))

    def test_ip_not_present(self):
        output = (
            "  Internet Address      Physical Address      Type\n"
            "  192.168.86.1          aa-bb-cc-dd-ee-ff     dynamic\n"
        )
        self.assertIsNone(parse_arp_output(output, "192.168.86.27"))

    def test_malformed_mac_column_returns_none(self):
        output = "  192.168.86.27         not-a-mac             dynamic\n"
        self.assertIsNone(parse_arp_output(output, "192.168.86.27"))

    def test_empty_output(self):
        self.assertIsNone(parse_arp_output("", "192.168.86.27"))


class TestWindowsArpTable(unittest.TestCase):
    """WindowsArpTable is exercised with an injected runner function so no
    subprocess is actually started."""

    def _make_runner(self, stdout: str, returncode: int = 0):
        def runner(*args, **kwargs):
            return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr="")

        return runner

    def test_lookup_parses_found_line(self):
        stdout = "  192.168.86.27         ec-b5-fa-82-2d-1d     dynamic\n"
        table = WindowsArpTable(runner=self._make_runner(stdout))
        self.assertEqual(table.lookup("192.168.86.27"), "ec:b5:fa:82:2d:1d")

    def test_lookup_no_arp_entries_found_returns_none(self):
        table = WindowsArpTable(runner=self._make_runner("No ARP Entries Found\n"))
        self.assertIsNone(table.lookup("192.168.86.27"))

    def test_lookup_nonzero_returncode_returns_none(self):
        table = WindowsArpTable(runner=self._make_runner("", returncode=1))
        self.assertIsNone(table.lookup("192.168.86.27"))

    def test_lookup_runner_exception_returns_none(self):
        def raising_runner(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="arp", timeout=2.0)

        table = WindowsArpTable(runner=raising_runner)
        self.assertIsNone(table.lookup("192.168.86.27"))

    def test_lookup_passes_ip_and_no_shell(self):
        seen = {}

        def runner(cmd, **kwargs):
            seen["cmd"] = cmd
            seen["kwargs"] = kwargs
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="No ARP Entries Found\n", stderr="")

        table = WindowsArpTable(runner=runner)
        table.lookup("192.168.86.27")
        self.assertEqual(seen["cmd"], ["arp", "-a", "192.168.86.27"])
        self.assertNotIn("shell", seen["kwargs"])


class TestAccessPolicy(unittest.TestCase):
    def test_open_when_both_lists_empty(self):
        policy = AccessPolicy(allowed_macs=[], allowed_ips=[], allow_loopback=True)
        self.assertTrue(policy.is_open)
        decision = policy.check("10.0.0.99", FakeArpTable({}))
        self.assertTrue(decision.allowed)

    def test_not_open_when_macs_configured(self):
        policy = AccessPolicy(allowed_macs=["ec:b5:fa:82:2d:1d"], allowed_ips=[], allow_loopback=True)
        self.assertFalse(policy.is_open)

    def test_not_open_when_ips_configured(self):
        policy = AccessPolicy(allowed_macs=[], allowed_ips=["192.168.86.27"], allow_loopback=True)
        self.assertFalse(policy.is_open)

    def test_allowed_mac_admits(self):
        policy = AccessPolicy(allowed_macs=["ec:b5:fa:82:2d:1d"], allowed_ips=[], allow_loopback=True)
        arp = FakeArpTable({"192.168.86.27": "ec:b5:fa:82:2d:1d"})
        decision = policy.check("192.168.86.27", arp)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.mac, "ec:b5:fa:82:2d:1d")

    def test_different_mac_denied(self):
        policy = AccessPolicy(allowed_macs=["ec:b5:fa:82:2d:1d"], allowed_ips=[], allow_loopback=True)
        arp = FakeArpTable({"192.168.86.50": "aa:bb:cc:dd:ee:ff"})
        decision = policy.check("192.168.86.50", arp)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.mac, "aa:bb:cc:dd:ee:ff")

    def test_ip_absent_from_arp_denied(self):
        policy = AccessPolicy(allowed_macs=["ec:b5:fa:82:2d:1d"], allowed_ips=[], allow_loopback=True)
        decision = policy.check("192.168.86.50", FakeArpTable({}))
        self.assertFalse(decision.allowed)
        self.assertIsNone(decision.mac)

    def test_mac_formats_compare_equal(self):
        policy = AccessPolicy(allowed_macs=["EC-B5-FA-82-2D-1D"], allowed_ips=[], allow_loopback=True)
        arp = FakeArpTable({"192.168.86.27": "ecb5.fa82.2d1d"})
        decision = policy.check("192.168.86.27", arp)
        self.assertTrue(decision.allowed)

    def test_ip_allowlist_admits_without_arp_entry(self):
        policy = AccessPolicy(allowed_macs=[], allowed_ips=["192.168.86.27"], allow_loopback=True)
        decision = policy.check("192.168.86.27", FakeArpTable({}))
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "allowed IP")

    def test_loopback_admitted_when_allowed_with_nonempty_lists(self):
        policy = AccessPolicy(allowed_macs=["ec:b5:fa:82:2d:1d"], allowed_ips=[], allow_loopback=True)
        decision = policy.check("127.0.0.1", FakeArpTable({}))
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "loopback")

    def test_loopback_rejected_when_not_allowed_with_nonempty_lists(self):
        policy = AccessPolicy(allowed_macs=["ec:b5:fa:82:2d:1d"], allowed_ips=[], allow_loopback=False)
        decision = policy.check("127.0.0.1", FakeArpTable({}))
        self.assertFalse(decision.allowed)

    def test_ipv6_loopback_forms_admitted(self):
        policy = AccessPolicy(allowed_macs=["ec:b5:fa:82:2d:1d"], allowed_ips=[], allow_loopback=True)
        for ip in ("::1", "::ffff:127.0.0.1"):
            with self.subTest(ip=ip):
                decision = policy.check(ip, FakeArpTable({}))
                self.assertTrue(decision.allowed)


if __name__ == "__main__":
    unittest.main()
