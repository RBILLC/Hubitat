"""Tests for moonhalo_bridge.capabilities: parsing a DDC/CI capabilities
string, exercised against the RD280UG's real string recorded on the
research branch (docs/research/rd280ug-capabilities.md, issue #28).
"""
import unittest

from moonhalo_bridge.capabilities import VcpEntry, parse_segment, parse_vcp_codes
from moonhalo_bridge.cli import DRY_RUN_CAPABILITIES


class TestParseVcpCodesRd280ug(unittest.TestCase):
    """One assertion per notable shape in the research file's section 4
    parsed list, plus a full-list check for the order and the duplicate
    0x80 entry."""

    def setUp(self):
        self.entries = parse_vcp_codes(DRY_RUN_CAPABILITIES)

    def test_first_and_last_entries(self):
        self.assertEqual(self.entries[0], VcpEntry(code=0x02, values=None))
        self.assertEqual(self.entries[-1], VcpEntry(code=0xFD, values=(0x00, 0x03, 0x04)))

    def test_bare_codes_have_no_values(self):
        by_code = {entry.code: entry for entry in self.entries if entry.code in (0xD7, 0xD9)}
        self.assertIsNone(by_code[0xD7].values)
        self.assertIsNone(by_code[0xD9].values)

    def test_code_with_no_space_before_paren(self):
        matches = [entry for entry in self.entries if entry.code == 0x7E]
        self.assertEqual(matches, [VcpEntry(code=0x7E, values=(0x0F, 0x11, 0x13))])

    def test_code_with_trailing_space_in_list(self):
        matches = [entry for entry in self.entries if entry.code == 0xCC]
        self.assertEqual(len(matches), 1)
        self.assertEqual(
            matches[0].values,
            (0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x09, 0x0A, 0x0B, 0x0D, 0x0E, 0x0F, 0x10,
             0x12, 0x14, 0x17, 0x1A, 0x1E, 0x1F, 0x24),
        )
        self.assertEqual(len(matches[0].values), 21)

    def test_code_listed_twice_keeps_both_in_order(self):
        matches = [entry for entry in self.entries if entry.code == 0x80]
        self.assertEqual(
            matches,
            [
                VcpEntry(code=0x80, values=(0x00, 0x01, 0x02)),
                VcpEntry(code=0x80, values=(0x00, 0x01, 0x02, 0x03)),
            ],
        )

    def test_total_entry_count(self):
        # The research file's section 4 table lists 63 lines (62 distinct
        # codes, 0x80 twice) -- its own prose miscounts this as "61 lines,
        # 60 distinct codes", but the table itself is what section 4 says
        # to match, and this is a straight count of its rows.
        self.assertEqual(len(self.entries), 63)


class TestParseVcpCodesErrors(unittest.TestCase):
    def test_no_vcp_segment_raises(self):
        with self.assertRaises(ValueError):
            parse_vcp_codes("(prot(monitor)type(LCD)model(RD280UG))")

    def test_malformed_entry_raises(self):
        with self.assertRaises(ValueError):
            parse_vcp_codes("(vcp(D7 XY D9))")

    def test_error_message_quotes_offending_text(self):
        try:
            parse_vcp_codes("(vcp(D7 XY D9))")
        except ValueError as error:
            self.assertIn("XY", str(error))
        else:
            self.fail("expected ValueError")


class TestParseSegment(unittest.TestCase):
    def test_model(self):
        self.assertEqual(parse_segment(DRY_RUN_CAPABILITIES, "model"), "RD280UG")

    def test_mccs_ver(self):
        self.assertEqual(parse_segment(DRY_RUN_CAPABILITIES, "mccs_ver"), "2.2")

    def test_missing_segment_returns_none(self):
        self.assertIsNone(parse_segment(DRY_RUN_CAPABILITIES, "nope"))


if __name__ == "__main__":
    unittest.main()
