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
    "log_file": None,
    "default_brightness_step": 5,
    "default_colortemp_step": 4,
    "kelvin_min": 2700,
    "kelvin_max": 6500,
    "invert_colortemp": False,
    # Placeholders for the access-control ticket; not enforced yet.
    "allowed_macs": [],
    "allowed_ips": [],
    "allow_loopback": True,
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


def _resolve_path(value: Optional[str], base_dir: Path) -> Optional[Path]:
    """Resolve `value` against `base_dir` unless it is already absolute."""
    if value is None:
        return None
    path = Path(value)
    return path if path.is_absolute() else base_dir / path


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
    )
