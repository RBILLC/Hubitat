"""Command-line mode for the MoonHalo Bridge: list monitors, read or write a
VCP register, or serve the HTTP bridge, against the real monitor or an
in-memory fake with `--dry-run`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence, TextIO

from .capabilities import VcpEntry, parse_vcp_codes
from .ddc import DdcError, DdcPort, FakeDdcPort, MonitorInfo, WindowsDdcPort

#: Hardware facts verified on the RD280UG on 2026-09-03, used to pre-load the
#: `--dry-run` fake port.
DRY_RUN_MONITORS = [
    MonitorInfo(device_name="DRYRUN1", primary=True, description="Generic PnP Monitor"),
]
DRY_RUN_REGISTERS = {0xD9: (0x0105, 0x070A), 0xD7: (0x0230, 0x0231)}

#: The RD280UG's own DDC/CI capabilities string, read verbatim on
#: 2026-09-03 (issue #28) and recorded in
#: docs/research/rd280ug-capabilities.md. Pre-loads the --dry-run fake so
#: `capabilities` has a real string to parse with no hardware attached.
DRY_RUN_CAPABILITIES = (
    "(prot(monitor)type(LCD)model(RD280UG)cmds(01 02 03 07 0C E3 F3)vcp(02 04 08 10 12 13 "
    "(00 01) 14 (04 05 08 0B) 16 18 19 1A 52 60 (0F 11 13) 62 68 (00 02 04 06 08 0A 0C 0E) "
    "69 (00 01) 6A (00 01) 6F (00 01) 71 (00 01) 72 (50 64 78 8C A0) 7D (00 01 02 07 08) "
    "7E(0F 11 13) 7F (01) 80 (00 01 02) 80 (00 01 02 03) 81 (00 01 02) 86 (02 05) 87 8A "
    "8D (01 02) 94 (01 02 03) AA (01 02 03) C1 C2 C9 CA(01 02 05 06 09 0A 11 12 21 22) "
    "CC(01 02 03 04 05 06 07 09 0A 0B 0D 0E 0F 10 12 14 17 1A 1E 1F 24 ) "
    "D0(01 02 03 04 05 06 07 08 09 0A) D1(00 01 02) D2 D6 (50 60 90 A0) D7 D9 "
    "DC (0A 0F 12 1F 23 30 31 32 3A) DF E1 E3 (00 01) E4 (02 03 04) E5 E6 (00 01) "
    "E7 (00 01 0A 14 1E 3C 50 A0) E8 (01 02) E9 (01 02 03) EB (00 01 02 03) EE (00 01 02) "
    "EF (00 01) F0 (00 01 02) F1 (00 1E 20 3C) F3 (00 01) F4 (00 01) F6 (00 01) "
    "F8 (00 0A 14 1E) FD (00 03 04) mswhql(1)asset_eep(40)mccs_ver(2.2))"
)


def make_dry_run_port() -> FakeDdcPort:
    """A FakeDdcPort pre-loaded with the RD280UG's verified hardware facts."""
    return FakeDdcPort(
        monitors=list(DRY_RUN_MONITORS),
        registers=dict(DRY_RUN_REGISTERS),
        capabilities=DRY_RUN_CAPABILITIES,
    )


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

    sub.add_parser(
        "capabilities", help="read and parse the monitor's DDC/CI capabilities string"
    )

    read_parser = sub.add_parser("read", help="read a VCP register")
    read_parser.add_argument("code", type=parse_vcp_code, help="VCP code, hex (e.g. D9 or 0xD9)")

    write_parser = sub.add_parser("write", help="write a VCP register")
    write_parser.add_argument("code", type=parse_vcp_code, help="VCP code, hex (e.g. D7 or 0xD7)")
    write_parser.add_argument("value", type=parse_value, help="value, decimal or 0x-hex")

    serve_parser = sub.add_parser("serve", help="run the HTTP bridge")
    serve_parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="path to config.json (default: config.json next to the package folder)",
    )

    return parser


def _format_monitor(monitor: MonitorInfo) -> str:
    return f"device={monitor.device_name} primary={monitor.primary} description={monitor.description!r}"


def _format_vcp(code: int, current: int, maximum: int) -> str:
    return (
        f"VCP 0x{code:02X}: current={current} (0x{current:04X}) "
        f"maximum={maximum} (0x{maximum:04X})"
    )


def _format_vcp_entry(entry: VcpEntry) -> str:
    if entry.values is None:
        return f"  {entry.code:02X}"
    values = " ".join(f"{value:02X}" for value in entry.values)
    return f"  {entry.code:02X}  ({values})"


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


def _run_capabilities(port: DdcPort, out: TextIO) -> int:
    """Print the monitor's raw capabilities string, then its parsed VCP
    list, one entry per line in the monitor's own order.

    A DdcError from `read_capabilities` (retries exhausted) propagates to
    `main`'s existing DdcError handler, same as `read`/`write`. A
    ValueError from the parser is handled here instead, because the raw
    string -- already printed by that point -- is what the user needs even
    when parsing fails.
    """
    raw = port.read_capabilities()
    print(raw, file=out)
    try:
        entries = parse_vcp_codes(raw)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(file=out)
    for entry in entries:
        print(_format_vcp_entry(entry), file=out)
    return 0


def _run_serve(dry_run: bool, config_path: Optional[Path], out: TextIO) -> int:
    """Build the model and Flask app from config and serve them. Imported
    lazily so `monitors`/`read`/`write` never need Flask installed."""
    from .access import WindowsArpTable
    from .config import load_config
    from .http import create_app
    from .logs import file_logger
    from .model import MoonHaloModel

    from werkzeug.serving import make_server

    config = load_config(config_path)
    port: DdcPort = make_dry_run_port() if dry_run else WindowsDdcPort(monitor_selector=config.monitor_selector)
    model = MoonHaloModel(port, config, logger=file_logger("moonhalo_bridge.model", config))
    app = create_app(model, config, arp=WindowsArpTable())
    # Bind before announcing, so a Bridge that cannot take its port never
    # tells the Hub it is up.
    server = make_server(config.host, config.port, app, threaded=True)
    announcer = start_announcer(config, out)
    print(f"MoonHalo Bridge serving on {config.host}:{config.port} (dry_run={dry_run})", file=out)
    try:
        server.serve_forever()
    finally:
        if announcer is not None:
            announcer.stop()
    return 0


def start_announcer(config, out: TextIO):
    """Start the Maker API announcer on its daemon thread when config
    enables it; return it, or None. A config that asks for announcements
    but lacks a Maker API value, or listens on loopback only, gets one
    warning and no announcer."""
    from .announce import Announcer, is_loopback_host
    from .logs import file_logger

    if not config.announce_enabled:
        return None
    logger = file_logger("moonhalo_bridge.announce", config)
    message = None
    if not config.maker_configured:
        message = (
            "announce_enabled is true but hub_ip, maker_api_app_id, maker_api_device_id "
            "and maker_api_token are not all set: the Bridge address will not be announced"
        )
    elif is_loopback_host(config.host):
        message = (
            f"host is {config.host}, which the Hub cannot reach: the Bridge address "
            "will not be announced"
        )
    if message is not None:
        logger.warning(message)
        print(f"warning: {message}", file=out)
        return None
    announcer = Announcer(config, logger=logger)
    announcer.start()
    print(
        f"Announcing the Bridge address to hub {config.hub_ip} every {config.announce_seconds}s",
        file=out,
    )
    return announcer


def main(argv: Optional[Sequence[str]] = None, out: Optional[TextIO] = None) -> int:
    """Entry point for `py -m moonhalo_bridge`. Returns a process exit code."""
    out = out if out is not None else sys.stdout
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        try:
            return _run_serve(args.dry_run, args.config, out)
        except DdcError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1

    port: DdcPort = make_dry_run_port() if args.dry_run else WindowsDdcPort()

    try:
        if args.command == "monitors":
            return _run_monitors(port, out)
        if args.command == "read":
            return _run_read(port, args.code, out)
        if args.command == "write":
            return _run_write(port, args.code, args.value, args.dry_run, out)
        if args.command == "capabilities":
            return _run_capabilities(port, out)
    except DdcError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    parser.error(f"unknown command {args.command!r}")
    return 2  # pragma: no cover - parser.error above always exits


if __name__ == "__main__":
    sys.exit(main())
