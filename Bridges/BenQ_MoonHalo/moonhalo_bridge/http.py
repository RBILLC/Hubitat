"""Flask HTTP layer for the MoonHalo Bridge: maps GET endpoints onto the
MoonHalo model.

`create_app(model, config)` builds the Flask app. The access-control
allowlists (`allowed_macs`, `allowed_ips`, `allow_loopback`) are read from
`config` but not enforced here; that is a later ticket.
"""
from __future__ import annotations

import logging
import sys
from typing import Optional

from flask import Flask, jsonify, request

from .config import Config
from .ddc import DdcError
from .model import POWER_OFF_VALUE, POWER_ON_VALUE, VCP_POWER, MoonHaloModel

#: Writes a call to /moonhalo/status (or /health) always produces: none.
NO_WRITES: list[tuple[int, int]] = []


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


def create_app(model: MoonHaloModel, config: Config) -> Flask:
    """Build the Flask app wiring GET endpoints to `model`."""
    app = Flask(__name__)
    logger = _configure_logger(config)

    @app.get("/health")
    def health():
        _log_request(logger, "/health", NO_WRITES, "ok")
        return jsonify({"ok": True}), 200

    @app.get("/moonhalo/on")
    def moonhalo_on():
        endpoint = "/moonhalo/on"
        try:
            level = _parse_level(request.args.get("level"))
        except ValueError as error:
            _log_request(logger, endpoint, NO_WRITES, f"error:{error}")
            return jsonify({"ok": False, "error": str(error)}), 400

        writes = [(VCP_POWER, POWER_ON_VALUE)]
        try:
            state = model.turn_on(level)
        except DdcError as error:
            _log_request(logger, endpoint, writes, f"error:{error}")
            return jsonify({"ok": False, "error": str(error)}), 500

        _log_request(logger, endpoint, writes, "ok")
        return jsonify({"ok": True, "state": state}), 200

    @app.get("/moonhalo/off")
    def moonhalo_off():
        endpoint = "/moonhalo/off"
        writes = [(VCP_POWER, POWER_OFF_VALUE)]
        try:
            state = model.turn_off()
        except DdcError as error:
            _log_request(logger, endpoint, writes, f"error:{error}")
            return jsonify({"ok": False, "error": str(error)}), 500

        _log_request(logger, endpoint, writes, "ok")
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
