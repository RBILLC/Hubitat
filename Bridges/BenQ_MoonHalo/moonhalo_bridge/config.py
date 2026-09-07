"""Bridge configuration: load a JSON config file with documented defaults.

The config file lives next to the package folder (``Bridges/BenQ_MoonHalo/``)
by default. Relative `state_file` and `log_file` paths in the config are
resolved against that same directory (or the directory of whatever config
file was actually loaded), so a config file can live anywhere and still use
short relative paths for its sibling files.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

#: Directory the package folder lives in, i.e. `Bridges/BenQ_MoonHalo/`.
PACKAGE_ROOT = Path(__file__).resolve().parent.parent

#: Default path to the config file, next to the package folder.
DEFAULT_CONFIG_PATH = PACKAGE_ROOT / "config.json"

#: Documented default for every config key.
DEFAULTS: dict[str, Any] = {
    "host": "0.0.0.0",
    "port": 5000,
    "default_on_level": 50,
    "monitor_selector": None,
    "state_file": "state.json",
    "log_file": "bridge.log",
    "default_brightness_step": 5,
    "default_colortemp_step": 4,
    "kelvin_min": 2700,
    "kelvin_max": 6500,
    "invert_colortemp": False,
    # Access control: enforced by moonhalo_bridge.access.AccessPolicy.
    "allowed_macs": [],
    "allowed_ips": [],
    "allow_loopback": True,
    # Maker API announcement (moonhalo_bridge.announce.Announcer): the Hub's
    # address, the Maker API app id, the MoonHalo device id, and the app's
    # access token. `announce_enabled` null means "on when all four are set".
    "hub_ip": None,
    "maker_api_app_id": None,
    "maker_api_device_id": None,
    "maker_api_token": None,
    "announce_seconds": 60,
    "announce_enabled": None,
}


@dataclass(frozen=True)
class Config:
    """Fully-resolved Bridge configuration. `state_file` and `log_file` are
    absolute paths (`log_file` may be `None`, meaning log to stderr)."""

    host: str
    port: int
    default_on_level: int
    monitor_selector: Optional[str]
    state_file: Path
    log_file: Optional[Path]
    default_brightness_step: int
    default_colortemp_step: int
    kelvin_min: int
    kelvin_max: int
    invert_colortemp: bool
    allowed_macs: list[str]
    allowed_ips: list[str]
    allow_loopback: bool
    hub_ip: Optional[str] = None
    maker_api_app_id: Optional[str] = None
    maker_api_device_id: Optional[str] = None
    maker_api_token: Optional[str] = None
    announce_seconds: int = 60
    announce_enabled: bool = False

    @property
    def maker_configured(self) -> bool:
        """True when every value the announcer needs is present."""
        return all(
            (self.hub_ip, self.maker_api_app_id, self.maker_api_device_id, self.maker_api_token)
        )


def _resolve_path(value: Optional[str], base_dir: Path) -> Optional[Path]:
    """Resolve `value` against `base_dir` unless it is already absolute."""
    if value is None:
        return None
    path = Path(value)
    return path if path.is_absolute() else base_dir / path


def _optional_str(value: Any) -> Optional[str]:
    """A non-empty string for `value` (ids may arrive as JSON numbers), or
    None when the key is null or blank."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_config(path: Optional[Path] = None) -> Config:
    """Load config from `path` (default `DEFAULT_CONFIG_PATH`), filling in
    the documented default for any key missing from the file. A missing
    file is not an error: every key simply takes its default.
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    data: dict[str, Any] = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)

    merged = dict(DEFAULTS)
    merged.update(data)
    base_dir = config_path.resolve().parent

    hub_ip = _optional_str(merged["hub_ip"])
    app_id = _optional_str(merged["maker_api_app_id"])
    device_id = _optional_str(merged["maker_api_device_id"])
    token = _optional_str(merged["maker_api_token"])
    maker_configured = all((hub_ip, app_id, device_id, token))
    announce_enabled = merged["announce_enabled"]
    if announce_enabled is None:
        announce_enabled = maker_configured
    announce_seconds = int(merged["announce_seconds"])
    if announce_seconds < 1:
        raise ValueError(f"announce_seconds must be at least 1, got {announce_seconds}")

    return Config(
        host=merged["host"],
        port=int(merged["port"]),
        default_on_level=int(merged["default_on_level"]),
        monitor_selector=merged["monitor_selector"],
        state_file=_resolve_path(merged["state_file"], base_dir),
        log_file=_resolve_path(merged["log_file"], base_dir),
        default_brightness_step=int(merged["default_brightness_step"]),
        default_colortemp_step=int(merged["default_colortemp_step"]),
        kelvin_min=int(merged["kelvin_min"]),
        kelvin_max=int(merged["kelvin_max"]),
        invert_colortemp=bool(merged["invert_colortemp"]),
        allowed_macs=list(merged["allowed_macs"]),
        allowed_ips=list(merged["allowed_ips"]),
        allow_loopback=bool(merged["allow_loopback"]),
        hub_ip=hub_ip,
        maker_api_app_id=app_id,
        maker_api_device_id=device_id,
        maker_api_token=token,
        announce_seconds=announce_seconds,
        announce_enabled=bool(announce_enabled),
    )
