"""Tests for moonhalo_bridge.cli: argument parsing and --dry-run behaviour.

All --dry-run cases run through main(argv) with captured stdout, per the
ticket's testing decisions, so no Windows API call happens in these tests.
"""
import argparse
import io
import unittest
from pathlib import Path

from moonhalo_bridge.cli import (
    build_parser,
    main,
    parse_value,
    parse_vcp_code,
)


class TestParseVcpCode(unittest.TestCase):
    def test_bare_hex(self):
        self.assertEqual(parse_vcp_code("D9"), 0xD9)

    def test_lowercase_hex(self):
        self.assertEqual(parse_vcp_code("d9"), 0xD9)

    def test_0x_prefixed_hex(self):
        self.assertEqual(parse_vcp_code("0xD7"), 0xD7)

    def test_invalid_raises(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_vcp_code("not-hex")


class TestParseValue(unittest.TestCase):
    def test_decimal(self):
        self.assertEqual(parse_value("544"), 544)

    def test_0x_hex(self):
        self.assertEqual(parse_value("0x220"), 0x220)
        self.assertEqual(parse_value("0x220"), 544)

    def test_invalid_raises(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_value("not-a-number")


class TestBuildParser(unittest.TestCase):
    def test_requires_a_command(self):
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([])

    def test_parses_read(self):
        parser = build_parser()
        args = parser.parse_args(["--dry-run", "read", "D9"])
        self.assertTrue(args.dry_run)
        self.assertEqual(args.command, "read")
        self.assertEqual(args.code, 0xD9)

    def test_parses_write(self):
        parser = build_parser()
        args = parser.parse_args(["write", "D7", "544"])
        self.assertFalse(args.dry_run)
        self.assertEqual(args.command, "write")
        self.assertEqual(args.code, 0xD7)
        self.assertEqual(args.value, 544)

    def test_parses_serve_with_no_config(self):
        # Argument parsing only: main() would block on app.run(), so it is
        # not exercised here. The HTTP behaviour itself is covered by
        # test_http.py through create_app() directly.
        parser = build_parser()
        args = parser.parse_args(["--dry-run", "serve"])
        self.assertTrue(args.dry_run)
        self.assertEqual(args.command, "serve")
        self.assertIsNone(args.config)

    def test_parses_serve_with_config_path(self):
        parser = build_parser()
        args = parser.parse_args(["serve", "--config", "custom-config.json"])
        self.assertEqual(args.command, "serve")
        self.assertEqual(args.config, Path("custom-config.json"))


class TestDryRunMonitors(unittest.TestCase):
    def test_lists_the_preloaded_monitor(self):
        out = io.StringIO()
        exit_code = main(["--dry-run", "monitors"], out=out)
        self.assertEqual(exit_code, 0)
        output = out.getvalue()
        self.assertIn("Generic PnP Monitor", output)
        self.assertIn("primary=True", output)


class TestDryRunRead(unittest.TestCase):
    def test_reads_d9_hardware_facts(self):
        out = io.StringIO()
        exit_code = main(["--dry-run", "read", "D9"], out=out)
        self.assertEqual(exit_code, 0)
        output = out.getvalue()
        self.assertIn("current=261 (0x0105)", output)
        self.assertIn("maximum=1802 (0x070A)", output)

    def test_reads_d7_hardware_facts(self):
        out = io.StringIO()
        exit_code = main(["--dry-run", "read", "0xD7"], out=out)
        self.assertEqual(exit_code, 0)
        output = out.getvalue()
        self.assertIn("current=560 (0x0230)", output)
        self.assertIn("maximum=561 (0x0231)", output)

    def test_unknown_code_errors_cleanly_with_nonzero_exit(self):
        out = io.StringIO()
        exit_code = main(["--dry-run", "read", "AB"], out=out)
        self.assertNotEqual(exit_code, 0)


class TestDryRunWrite(unittest.TestCase):
    def test_write_reports_what_would_be_written_and_reads_back(self):
        out = io.StringIO()
        exit_code = main(["--dry-run", "write", "D7", "544"], out=out)
        self.assertEqual(exit_code, 0)
        output = out.getvalue()
        self.assertIn("[dry-run] would write VCP 0xD7 <- 544 (0x0220)", output)
        self.assertIn("wrote VCP 0xD7 <- 544 (0x0220)", output)
        # the fake preserves D7's existing maximum (0x0231) across the write
        self.assertIn("read-back: VCP 0xD7: current=544 (0x0220) maximum=561 (0x0231)", output)

    def test_write_performs_no_real_hardware_call(self):
        # If this touched WindowsDdcPort it would either raise (no monitor)
        # or hang; --dry-run must complete quickly and successfully.
        out = io.StringIO()
        exit_code = main(["--dry-run", "write", "D9", "0x0402"], out=out)
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
