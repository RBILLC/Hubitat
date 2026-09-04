"""Flask HTTP layer for the MoonHalo Bridge: maps GET endpoints onto the
MoonHalo model.

`create_app(model, config, arp)` builds the Flask app. A `before_request`
hook enforces the access-control allowlists (`allowed_macs`, `allowed_ips`,
`allow_loopback`) from `config` on every path except `/health`.
"""
from __future__ import annotations

import logging
import sys
from typing import Optional

from flask import Flask, jsonify, request

from .access import AccessPolicy, ArpTable, WindowsArpTable
from . import __version__
from .config import Config
from .ddc import DdcError
from .model import MoonHaloModel, kelvin_to_colortemp_step

#: Writes a call to /moonhalo/status (or /health) always produces: none.
NO_WRITES: list[tuple[int, int]] = []

#: Module logger (propagates to root) for the once-at-startup open-policy
#: warning, kept separate from the per-app request logger below, whose
#: handlers are reset on every `create_app` call.
_logger = logging.getLogger(__name__)


def _configure_logger(config: Config) -> logging.Logger:
    """One logger per app, writing to `config.log_file` or stderr when
    `log_file` is None, per request line: endpoint, VCP writes, outcome."""
    logger = logging.getLogger(f"moonhalo_bridge.http.{id(config)}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    if config.log_file:
        handler: logging.Handler = logging.FileHandler(config.log_file, encoding="utf-8")
    else:
        handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def _log_request(logger: logging.Logger, endpoint: str, writes: list[tuple[int, int]], outcome: str) -> None:
    logger.info("endpoint=%s writes=%s outcome=%s", endpoint, writes, outcome)


def _parse_level(raw: Optional[str]) -> Optional[int]:
    """Validate the optional `level` query: an integer 1-100, or None when
    absent. Raises ValueError, with a message fit for a 400 body, otherwise.
    """
    if raw is None:
        return None
    try:
        level = int(raw)
    except ValueError:
        raise ValueError(f"level must be an integer 1-100, got {raw!r}") from None
    if not 1 <= level <= 100:
        raise ValueError(f"level must be 1-100, got {level}")
    return level


def _parse_brightness(raw: str) -> int:
    """Validate the `/moonhalo/brightness/<value>` path segment: an integer
    0-100. `<value>` is captured as a plain string (not Flask's `<int:...>`
    converter) so a non-numeric value gets a 400, not a 404. Raises
    ValueError, with a message fit for a 400 body, otherwise.
    """
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"brightness must be an integer 0-100, got {raw!r}") from None
    if not 0 <= value <= 100:
        raise ValueError(f"brightness must be 0-100, got {value}")
    return value


def _parse_colortemp(raw: str, kelvin_min: int, kelvin_max: int, invert: bool) -> int:
    """Validate the `/moonhalo/colortemp/<value>` path segment: an integer
    1-7 is taken as the hardware step directly; an integer >= 1000 is
    Kelvin, converted to a step with `kelvin_to_colortemp_step`; anything
    else (0, 8-999, negative) is invalid. `<value>` is captured as a plain
    string (not Flask's `<int:...>` converter) so a non-numeric value gets
    a 400, not a 404. Raises ValueError, with a message fit for a 400
    body, otherwise.
    """
    try:
        parsed = int(raw)
    except ValueError:
        raise ValueError(
            f"colortemp must be an integer 1-7 (step) or >= 1000 (Kelvin), got {raw!r}"
        ) from None
    if 1 <= parsed <= 7:
        return parsed
    if parsed >= 1000:
        return kelvin_to_colortemp_step(parsed, kelvin_min, kelvin_max, invert)
    raise ValueError(f"colortemp must be 1-7 (step) or >= 1000 (Kelvin), got {parsed}")


def create_app(model: MoonHaloModel, config: Config, arp: Optional[ArpTable] = None) -> Flask:
    """Build the Flask app wiring GET endpoints to `model`, enforcing the
    access policy built from `config` on every path except `/health`.
    `arp` defaults to `WindowsArpTable()`.
    """
    app = Flask(__name__)
    logger = _configure_logger(config)
    arp_table = arp if arp is not None else WindowsArpTable()
    policy = AccessPolicy(config.allowed_macs, config.allowed_ips, config.allow_loopback)

    if policy.is_open:
        _logger.warning(
            "access policy is open (allowed_macs and allowed_ips are both empty): "
            "the Bridge accepts requests from any caller"
        )

    @app.before_request
    def enforce_access_policy():
        if request.path == "/health":
            return None
        remote_ip = request.remote_addr
        decision = policy.check(remote_ip, arp_table)
        if not decision.allowed:
            mac_text = decision.mac if decision.mac is not None else "unresolved"
            logger.info("access denied ip=%s mac=%s path=%s", remote_ip, mac_text, request.path)
            return jsonify({"ok": False, "error": "forbidden"}), 403
        return None

    @app.get("/health")
    def health():
        _log_request(logger, "/health", NO_WRITES, "ok")
        return jsonify({"ok": True, "version": __version__}), 200

    @app.get("/moonhalo/on")
    def moonhalo_on():
        endpoint = "/moonhalo/on"
        try:
            level = _parse_level(request.args.get("level"))
        except ValueError as error:
            _log_request(logger, endpoint, NO_WRITES, f"error:{error}")
            return jsonify({"ok": False, "error": str(error)}), 400

        try:
            state = model.turn_on(level)
        except DdcError as error:
            _log_request(logger, endpoint, model.last_writes, f"error:{error}")
            return jsonify({"ok": False, "error": str(error)}), 500

        _log_request(logger, endpoint, model.last_writes, "ok")
        return jsonify({"ok": True, "state": state}), 200

    @app.get("/moonhalo/off")
    def moonhalo_off():
        endpoint = "/moonhalo/off"
        try:
            state = model.turn_off()
        except DdcError as error:
            _log_request(logger, endpoint, model.last_writes, f"error:{error}")
            return jsonify({"ok": False, "error": str(error)}), 500

        _log_request(logger, endpoint, model.last_writes, "ok")
        return jsonify({"ok": True, "state": state}), 200

    @app.get("/moonhalo/brightness/<value>")
    def moonhalo_brightness(value: str):
        endpoint = "/moonhalo/brightness"
        try:
            level = _parse_brightness(value)
        except ValueError as error:
            _log_request(logger, endpoint, NO_WRITES, f"error:{error}")
            return jsonify({"ok": False, "error": str(error)}), 400

        try:
            state = model.set_level(level)
        except DdcError as error:
            _log_request(logger, endpoint, model.last_writes, f"error:{error}")
            return jsonify({"ok": False, "error": str(error)}), 500

        _log_request(logger, endpoint, model.last_writes, "ok")
        return jsonify({"ok": True, "state": state}), 200

    @app.get("/moonhalo/colortemp/<value>")
    def moonhalo_colortemp(value: str):
        endpoint = "/moonhalo/colortemp"
        try:
            step = _parse_colortemp(value, config.kelvin_min, config.kelvin_max, config.invert_colortemp)
        except ValueError as error:
            _log_request(logger, endpoint, NO_WRITES, f"error:{error}")
            return jsonify({"ok": False, "error": str(error)}), 400

        stage = request.args.get("stage") == "1"
        try:
            state = model.set_colortemp(step, stage=stage)
        except DdcError as error:
            _log_request(logger, endpoint, model.last_writes, f"error:{error}")
            return jsonify({"ok": False, "error": str(error)}), 500

        _log_request(logger, endpoint, model.last_writes, "ok")
        return jsonify({"ok": True, "state": state}), 200

    @app.get("/moonhalo/status")
    def moonhalo_status():
        state = model.status()
        _log_request(logger, "/moonhalo/status", NO_WRITES, "ok")
        return jsonify({"ok": True, "state": state}), 200

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify({"ok": False, "error": "not found"}), 404

    return app
