"""Logger construction shared by the HTTP layer and the announcer: one
handler writing to `config.log_file`, or to stderr when it is None."""
from __future__ import annotations

import logging
import sys

from .config import Config


def file_logger(name: str, config: Config, level: int = logging.INFO) -> logging.Logger:
    """A non-propagating logger named `name` whose single handler writes to
    `config.log_file` (stderr when None). Calling it again with the same
    name replaces the handler, so a rebuilt app never logs twice."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers.clear()
    if config.log_file:
        handler: logging.Handler = logging.FileHandler(config.log_file, encoding="utf-8")
    else:
        handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger
