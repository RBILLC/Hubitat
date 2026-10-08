"""Command-line mode for the MoonHalo Bridge: list monitors, read or write a
VCP register, or serve the HTTP bridge, against the real monitor or an
in-memory fake with `--dry-run`.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence, TextIO

from .ddc import (
    DEFAULT_FAKE_MONITOR,
    DEFAULT_MONITOR_PRODUCT,
    DdcError,
    DdcPort,
    FakeDdcPort,
    MonitorInfo,
    WindowsDdcPort,
)

#: Hardware facts verified on the RD280UG on 2026-09-03, used to pre-load the
#: `--dry-run` fake port; the monitor carries the RD280UG's EDID identity,
#: so `--dry-run` detects by `edid` like the real monitor.
DRY_RUN_MONITORS = [DEFAULT_FAKE_MONITOR]
DRY_RUN_REGISTERS = {0xD9: (0x0105, 0x070A), 0xD7: (0x0230, 0x0231)}


def make_dry_run_port(
    monitor_selector: Optional[str] = None,
    monitor_product: str = DEFAULT_MONITOR_PRODUCT,
    logger: Optional[logging.Logger] = None,
) -> FakeDdcPort:
    """A FakeDdcPort pre-loaded with the RD280UG's verified hardware facts."""
    return FakeDdcPort(
        monitors=list(DRY_RUN_MONITORS),
        registers=dict(DRY_RUN_REGISTERS),
        monitor_selector=monitor_selector,
        monitor_product=monitor_product,
        logger=logger,
    )


def cli_logger() -> logging.Logger:
    """Where the port's detection lines go for `monitors`, `read` and
    `write`: warnings to stderr, so an ambiguous or unanswering monitor is
    seen at the prompt. `serve` uses the Bridge's file logger instead."""
    logger = logging.getLogger("moonhalo_bridge.cli")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
        logger.propagate = False
    return logger


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
    parser.add_argument(
        "--monitor",
        default=None,
        metavar="SELECTOR",
        help=(
            "substring of a monitor's device name or description to act on, "
            "instead of detecting the MoonHalo monitor by its EDID identity "
            "(product %s; monitors, read, write; serve takes "
            "config.json's monitor_selector)"
        )
        % DEFAULT_MONITOR_PRODUCT,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "monitors", help="list attached monitors with their EDID identity and which one is the MoonHalo"
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
    """One `monitors` line: device, primary, the EDID identity (`none`
    for each field Windows has no value for), description."""
    product = monitor.product if monitor.product is not None else "none"
    name = repr(monitor.name) if monitor.name is not None else "none"
    serial = repr(monitor.serial) if monitor.serial is not None else "none"
    return (
        f"device={monitor.device_name} primary={monitor.primary} product={product} "
        f"name={name} serial={serial} description={monitor.description!r}"
    )


def _format_vcp(code: int, current: int, maximum: int) -> str:
    return (
        f"VCP 0x{code:02X}: current={current} (0x{current:04X}) "
        f"maximum={maximum} (0x{maximum:04X})"
    )


def _run_monitors(port: DdcPort, out: TextIO) -> int:
    """List every attached monitor with its EDID identity, then which one
    the port would act on and by which rule (issues #40, #44). No DDC/CI
    call is made: the identity comes from Windows."""
    monitors = port.list_monitors()
    if not monitors:
        print("No monitors found.", file=out)
        return 0
    for monitor in monitors:
        print(_format_monitor(monitor), file=out)
    detection = port.resolve_target()
    if detection.found:
        print(f"selected: {detection.label} (by {detection.rule})", file=out)
    else:
        print(f"selected: none ({detection.error})", file=out)
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
    ddc_logger = file_logger("moonhalo_bridge.ddc", config)
    if dry_run:
        port: DdcPort = make_dry_run_port(config.monitor_selector, config.monitor_product, ddc_logger)
    else:
        port = WindowsDdcPort(
            monitor_selector=config.monitor_selector,
            monitor_product=config.monitor_product,
            logger=ddc_logger,
        )
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

    logger = cli_logger()
    if args.dry_run:
        port: DdcPort = make_dry_run_port(monitor_selector=args.monitor, logger=logger)
    else:
        port = WindowsDdcPort(monitor_selector=args.monitor, logger=logger)

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
