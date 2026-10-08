"""Tests for moonhalo_bridge.edid: the EDID identity parser and the
interface-path to registry-key mapping (issue #44).

The two EDID blocks are the registry cache of this PC, captured on
2026-10-08 with PowerShell:
`(Get-ItemProperty "HKLM:\\SYSTEM\\CurrentControlSet\\Enum\\DISPLAY\\<id>\\<instance>\\Device Parameters").EDID`.
"""
import unittest

from moonhalo_bridge.edid import EdidIdentity, device_parameters_key, instance_id, parse_edid

#: The RD280UG, `DISPLAY\BNQ80BB\5&3a1fce67&0&UID4352`: three 128-byte blocks.
RD280UG_EDID = bytes.fromhex(
    "00ffffffffffff0009d1bb80010101011a240103803c28782a51d0ad5246a3230d5054a56b8081c081008180"
    "a9c0b3008140d1009500e0d40040f1003da060403a00548d2100001a000000ff00454d533654303032353830"
    "3837000000fd0830780f4781000a202020202020000000fc0042656e5120524432383055470a014702036af0"
    "e278025c010203111213042021221f10403f5d5e5f606176060715161405282e23090707830100006d030c00"
    "100038442000600102036dd85dc4017880630230788344156d1a000002013078ed0000000000e200eae305c0"
    "00e50f00000e00e6060501626225565e00a0a0a0295030203500548d2100001a000000ee7012670600030164"
    "c6f60088ff0e9f002f801f00ff094800020009004f9f0108ff0e770007801f00ff097b006d00070001f70108"
    "ff0e770007801f00ff09950087000700e1680008ff099f002f801f003f062d00020005006ec20008ff099f00"
    "2f801f009f05540002000400a800000000000000000000000000000000000090"
)
#: The PD2700U, `DISPLAY\BNQ802E\5&3a1fce67&0&UID4353`: two blocks.
PD2700U_EDID = bytes.fromhex(
    "00ffffffffffff0009d12e8001010101331e0104b53c22783f2895a7554ea3260f5054a56b80d1c081c08100"
    "8180a9c0b300a94001014dd000a0f0703e803020350055502100001a000000ff00455453434c303734303253"
    "4c30000000fd00283c8c8c3c010a202020202020000000fc0042656e5120504432373030550a01a702032ef1"
    "5661605d5e5f100504030207060f1f20212214131216012309070783010000e305c000e60605015a5344023a"
    "801871382d40582c450055502100001e565e00a0a0a029503020350055502100001a8c640050f0701f800820"
    "180455502100001a000000000000000000000000000000000000000000000000000000ea"
)
RD280UG_INTERFACE = "\\\\?\\DISPLAY#BNQ80BB#5&3a1fce67&0&UID4352#{e6f07b5f-ee97-4a90-b076-33f57bf4eaa7}"


def without_name_descriptor(edid: bytes) -> bytes:
    """Block 0 of `edid` with its name descriptor (tag 0xFC) replaced by a
    dummy descriptor (tag 0x10)."""
    block = bytearray(edid[:128])
    for offset in (54, 72, 90, 108):
        if block[offset : offset + 4] == bytes([0, 0, 0, 0xFC]):
            block[offset : offset + 18] = bytes([0, 0, 0, 0x10, 0]) + bytes(13)
            return bytes(block)
    raise AssertionError("no name descriptor to remove")


class TestParseEdid(unittest.TestCase):
    def test_rd280ug_registry_bytes(self):
        identity = parse_edid(RD280UG_EDID)
        self.assertEqual(identity.manufacturer, "BNQ")
        self.assertEqual(identity.product_code, "80BB")
        self.assertEqual(identity.product, "BNQ80BB")
        self.assertEqual(identity.name, "BenQ RD280UG")
        self.assertEqual(identity.serial, "EMS6T00258087")

    def test_pd2700u_registry_bytes(self):
        identity = parse_edid(PD2700U_EDID)
        self.assertEqual(identity.product, "BNQ802E")
        self.assertEqual(identity.name, "BenQ PD2700U")
        self.assertEqual(identity.serial, "ETSCL07402SL0")

    def test_block_zero_alone_is_enough(self):
        self.assertEqual(parse_edid(RD280UG_EDID[:128]), parse_edid(RD280UG_EDID))

    def test_block_with_no_name_descriptor(self):
        identity = parse_edid(without_name_descriptor(RD280UG_EDID))
        self.assertEqual(identity.product, "BNQ80BB")
        self.assertIsNone(identity.name)
        self.assertEqual(identity.serial, "EMS6T00258087")

    def test_block_with_no_descriptor_strings_at_all(self):
        block = bytearray(RD280UG_EDID[:128])
        for offset in (54, 72, 90, 108):
            block[offset : offset + 18] = bytes([0, 0, 0, 0x10, 0]) + bytes(13)
        identity = parse_edid(bytes(block))
        self.assertEqual(identity, EdidIdentity("BNQ", "80BB", None, None))

    def test_product_code_is_little_endian_upper_case_hex(self):
        block = bytearray(RD280UG_EDID[:128])
        block[10:12] = bytes([0x0A, 0x01])
        self.assertEqual(parse_edid(bytes(block)).product_code, "010A")

    def test_too_short_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_edid(RD280UG_EDID[:127])
        with self.assertRaises(ValueError):
            parse_edid(b"")

    def test_bad_header_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_edid(b"\x00" * 128)


class TestInterfacePath(unittest.TestCase):
    def test_instance_id_is_the_middle_of_the_interface_path(self):
        self.assertEqual(instance_id(RD280UG_INTERFACE), "DISPLAY\\BNQ80BB\\5&3a1fce67&0&UID4352")

    def test_registry_key_is_the_instance_under_enum_with_device_parameters(self):
        self.assertEqual(
            device_parameters_key(RD280UG_INTERFACE),
            "SYSTEM\\CurrentControlSet\\Enum\\DISPLAY\\BNQ80BB\\5&3a1fce67&0&UID4352\\Device Parameters",
        )

    def test_a_path_without_the_prefix_or_guid_still_maps(self):
        self.assertEqual(instance_id("DISPLAY#BNQ802E#5&3a1fce67&0&UID4353"), "DISPLAY\\BNQ802E\\5&3a1fce67&0&UID4353")

    def test_empty_path_is_rejected(self):
        with self.assertRaises(ValueError):
            instance_id("")


if __name__ == "__main__":
    unittest.main()
