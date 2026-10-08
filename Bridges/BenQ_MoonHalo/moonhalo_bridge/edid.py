"""EDID identity: parse a monitor's EDID bytes into manufacturer letters,
product code, name and serial, and map a `GUID_DEVINTERFACE_MONITOR`
interface path onto the registry key that caches those bytes (issue #44;
research in docs/research/windows-monitor-identity-without-ddc.md).

Pure Python, no Windows calls: `WindowsDdcPort` does the registry read.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: Every EDID block 0 starts with this fixed header.
EDID_HEADER = b"\x00\xff\xff\xff\xff\xff\xff\x00"
#: Where block 0's four 18-byte descriptors start.
DESCRIPTOR_OFFSETS = (54, 72, 90, 108)
#: Display descriptor tags: monitor name and monitor serial number.
TAG_NAME = 0xFC
TAG_SERIAL = 0xFF
#: The `DISPLAY\<product>\<instance>` key's parent in `HKLM`.
ENUM_KEY = "SYSTEM\\CurrentControlSet\\Enum"


@dataclass(frozen=True)
class EdidIdentity:
    """What a monitor's EDID says it is.

    manufacturer: the three PnP letters (`BNQ`).
    product_code: the 16-bit product code as four upper-case hex digits (`80BB`).
    name: the monitor name descriptor (`BenQ RD280UG`); None when absent.
    serial: the serial number descriptor (`EMS6T00258087`); None when absent.
    """

    manufacturer: str
    product_code: str
    name: Optional[str] = None
    serial: Optional[str] = None

    @property
    def product(self) -> str:
        """Manufacturer letters plus product code: `BNQ80BB`, what
        `monitor_product` is compared with."""
        return self.manufacturer + self.product_code


def parse_edid(data: bytes) -> EdidIdentity:
    """The identity in block 0 of `data` (any extension blocks are ignored).
    Raises ValueError when there is no complete block 0 or its header is
    not an EDID's."""
    if len(data) < 128:
        raise ValueError(f"EDID is {len(data)} bytes, shorter than one 128-byte block")
    if data[:8] != EDID_HEADER:
        raise ValueError("not an EDID block: bad header")
    packed = (data[8] << 8) | data[9]
    manufacturer = "".join(
        chr(ord("A") + ((packed >> shift) & 0x1F) - 1) for shift in (10, 5, 0)
    )
    product_code = f"{data[10] | (data[11] << 8):04X}"
    name = _descriptor_text(data, TAG_NAME)
    serial = _descriptor_text(data, TAG_SERIAL)
    return EdidIdentity(manufacturer, product_code, name, serial)


def _descriptor_text(data: bytes, tag: int) -> Optional[str]:
    """The text of the first display descriptor carrying `tag`: 13 bytes
    ending at the first newline, trailing spaces dropped. None when no
    descriptor has that tag."""
    for offset in DESCRIPTOR_OFFSETS:
        block = data[offset : offset + 18]
        if block[:3] != b"\x00\x00\x00" or block[3] != tag:
            continue
        text = block[5:18].decode("latin-1").split("\n", 1)[0].rstrip()
        return text or None
    return None


def instance_id(interface_path: str) -> str:
    """The PnP device instance ID inside a monitor's device interface
    path: `\\\\?\\DISPLAY#BNQ80BB#5&3a1fce67&0&UID4352#{guid}` gives
    `DISPLAY\\BNQ80BB\\5&3a1fce67&0&UID4352`."""
    path = interface_path
    if path.startswith("\\\\?\\"):
        path = path[4:]
    parts = [part for part in path.split("#") if part]
    if parts and parts[-1].startswith("{"):
        parts.pop()
    if not parts:
        raise ValueError(f"no device instance in interface path {interface_path!r}")
    return "\\".join(parts)


def device_parameters_key(interface_path: str) -> str:
    """The `HKLM` subkey whose `EDID` value caches that monitor's EDID."""
    return f"{ENUM_KEY}\\{instance_id(interface_path)}\\Device Parameters"
