"""Command-line mode for the MoonHalo Bridge: list monitors, read or write a
VCP register, against the real monitor or an in-memory fake with `--dry-run`.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence, TextIO

from .ddc import DdcError, DdcPort, FakeDdcPort, MonitorInfo, WindowsDdcPort

#: Hardware facts verified on the RD280UG on 2026-09-03, used to pre-load the
#: `--dry-run` fake port.
DRY_RUN_MONITORS = [
    MonitorInfo(device_name="DRYRUN1", primary=True, description="Generic PnP Monitor"),
]
DRY_RUN_REGISTERS = {0xD9: (0x0105, 0x070A), 0xD7: (0x0230, 0x0231)}


def make_dry_run_port() -> FakeDdcPort:
    """A FakeDdcPort pre-loaded with the RD280UG's verified hardware facts."""
    return FakeDdcPort(monitors=list(DRY_RUN_MONITORS), registers=dict(DRY_RUN_REGISTERS))


def parse_vcp_code(text: str) -> int:
    """Parse a VCP code given as hex, with or without a 0x prefix (D9 or 0xD9)."""
    try:
        return int(text, 16)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"invalid VCP code {text!r}: expected hex like D9 or 0xD9"
        ) from error


def parse_value(text: str) -> int:
    """Parse a VCP value as decimal or 0x-prefixed hex."""
    try:
        return int(text, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"invalid value {text!r}: expected decimal or 0x-hex"
        ) from error


def build_parser() -> argparse.ArgumentParser:
    """Build the `moonhalo_bridge` argparse parser."""
    parser = argparse.ArgumentParser(
        prog="moonhalo_bridge", description="MoonHalo Bridge DDC command line"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="use an in-memory fake monitor; perform no Windows API calls",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("monitors", help="list attached monitors")

    read_parser = sub.add_parser("read", help="read a VCP register")
    read_parser.add_argument("code", type=parse_vcp_code, help="VCP code, hex (e.g. D9 or 0xD9)")

    write_parser = sub.add_parser("write", help="write a VCP register")
    write_parser.add_argument("code", type=parse_vcp_code, help="VCP code, hex (e.g. D7 or 0xD7)")
    write_parser.add_argument("value", type=parse_value, help="value, decimal or 0x-hex")

    return parser


def _format_monitor(monitor: MonitorInfo) -> str:
    return f"device={monitor.device_name} primary={monitor.primary} description={monitor.description!r}"


def _format_vcp(code: int, current: int, maximum: int) -> str:
    return (
        f"VCP 0x{code:02X}: current={current} (0x{current:04X}) "
        f"maximum={maximum} (0x{maximum:04X})"
    )


def _run_monitors(port: DdcPort, out: TextIO) -> int:
    monitors = port.list_monitors()
    if not monitors:
        print("No monitors found.", file=out)
        return 0
    for monitor in monitors:
        print(_format_monitor(monitor), file=out)
    return 0


def _run_read(port: DdcPort, code: int, out: TextIO) -> int:
    current, maximum = port.read_vcp(code)
    print(_format_vcp(code, current, maximum), file=out)
    return 0


def _run_write(port: DdcPort, code: int, value: int, dry_run: bool, out: TextIO) -> int:
    if dry_run:
        print(f"[dry-run] would write VCP 0x{code:02X} <- {value} (0x{value:04X})", file=out)
    port.write_vcp(code, value)
    current, maximum = port.read_vcp(code)
    print(
        f"wrote VCP 0x{code:02X} <- {value} (0x{value:04X}); "
        f"read-back: {_format_vcp(code, current, maximum)}",
        file=out,
    )
    return 0


def main(argv: Optional[Sequence[str]] = None, out: Optional[TextIO] = None) -> int:
    """Entry point for `py -m moonhalo_bridge`. Returns a process exit code."""
    out = out if out is not None else sys.stdout
    parser = build_parser()
    args = parser.parse_args(argv)

    port: DdcPort = make_dry_run_port() if args.dry_run else WindowsDdcPort()

    try:
        if args.command == "monitors":
            return _run_monitors(port, out)
        if args.command == "read":
            return _run_read(port, args.code, out)
        if args.command == "write":
            return _run_write(port, args.code, args.value, args.dry_run, out)
    except DdcError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    parser.error(f"unknown command {args.command!r}")
    return 2  # pragma: no cover - parser.error above always exits


if __name__ == "__main__":
    sys.exit(main())
