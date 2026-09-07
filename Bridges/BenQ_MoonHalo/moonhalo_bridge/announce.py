"""Announces the Bridge's LAN address to the Driver through the Hub's Maker
API, so the Hub keeps finding the Bridge after the PC's IP changes.

The Driver exposes a custom command `setBridgeAddress(ip, port)`. Maker API
turns it into a GET on

    http://<hub_ip>/apps/api/<app>/devices/<device>/setBridgeAddress/<ip>,<port>?access_token=<token>

with the two command parameters comma-separated as the secondary value
(Hubitat staff, https://community.hubitat.com/t/25634). `Announcer` sends
that request when `serve` starts, every `announce_seconds`, and within
`check_seconds` of the LAN address changing.

The LAN address is whatever local address the OS would use to reach the
Hub, read from a UDP socket connected to `hub_ip` (nothing is sent), so an
overlay adapter such as Tailscale is never chosen. The HTTP sender is
injectable so tests use a fake; the access token never reaches a log line.
"""
from __future__ import annotations

import logging
import socket
import threading
import time
import urllib.parse
import urllib.request
from typing import Callable, Optional, Protocol

from .config import Config

#: Timeout, in seconds, for one announcement request to the Hub.
ANNOUNCE_TIMEOUT = 5.0

#: How often, in seconds, the announcer re-reads the LAN address between
#: announcements; an address change is announced on the next check.
CHECK_SECONDS = 5.0

#: Port used only to pick a route in `lan_address_for`; never contacted.
_ROUTE_PROBE_PORT = 9

#: A callable returning the local address that routes to the given Hub IP.
AddressSource = Callable[[str], str]

#: `host` values that mean "every interface": the announcer then picks the
#: address that routes to the Hub. Any other host is announced as typed.
WILDCARD_HOSTS = frozenset({"", "0.0.0.0", "::"})

#: `host` values the Hub can never reach; the announcer refuses to run.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def is_wildcard_host(host: Optional[str]) -> bool:
    return (host or "").strip() in WILDCARD_HOSTS


def is_loopback_host(host: Optional[str]) -> bool:
    return (host or "").strip().lower() in LOOPBACK_HOSTS


def lan_address_for(hub_ip: str) -> str:
    """The local IPv4 address the OS would send from to reach `hub_ip`.

    Connecting a UDP socket only selects a route and binds a local address;
    no packet leaves the machine. Raises `OSError` when `hub_ip` is not an
    address or no route exists.
    """
    socket.inet_aton(hub_ip)  # a literal IPv4 only: no name lookup, fails fast
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((hub_ip, _ROUTE_PROBE_PORT))
        return sock.getsockname()[0]


def build_announce_url(hub_ip: str, app_id: str, device_id: str, ip: str, port: int, token: str) -> str:
    """The Maker API URL that calls `setBridgeAddress(ip, port)` on the
    MoonHalo device: both parameters comma-separated in the path."""
    return (
        f"http://{hub_ip}/apps/api/{app_id}/devices/{device_id}/setBridgeAddress/{ip},{port}"
        f"?access_token={urllib.parse.quote(str(token), safe='')}"
    )


def redact(text: str, token: str) -> str:
    """`text` with every occurrence of `token` replaced, for log lines."""
    if not token:
        return text
    return text.replace(token, "[redacted]")


class Sender(Protocol):
    """Performs one announcement GET; raises on any failure."""

    def send(self, url: str) -> None:
        ...


class UrllibSender:
    """`Sender` backed by `urllib.request`, with a short timeout. The Hub's
    reply body is read and discarded: Maker API answers with the device's
    attributes, which the Bridge has no use for."""

    def __init__(self, timeout: float = ANNOUNCE_TIMEOUT):
        self._timeout = timeout

    def send(self, url: str) -> None:
        with urllib.request.urlopen(url, timeout=self._timeout) as response:
            response.read()


class FakeSender:
    """`Sender` for tests: records every URL; raises `OSError(error_text)`
    while `fail` is true."""

    def __init__(self) -> None:
        self.urls: list[str] = []
        self.fail = False
        self.error_text = "simulated failure"

    def send(self, url: str) -> None:
        self.urls.append(url)
        if self.fail:
            raise OSError(self.error_text)


class Announcer:
    """Sends `setBridgeAddress` announcements on a schedule.

    `tick(now)` is the whole decision: read the LAN address, send when it
    differs from the last attempt or when `announce_seconds` have passed
    since the last attempt, and log the outcome. `run` / `start` drive
    `tick` from a daemon thread every `check_seconds`.

    The address announced is the one the Bridge listens on: `config.host`
    when it names an interface, otherwise (wildcard) the local address that
    routes to the Hub.

    Logging: the first successful announcement and every address change
    log at info; unchanged repeats at debug; a failed lookup or a failed
    send warns once on the transition to failing and logs at debug while
    it keeps failing; recovery logs at info. Failures never raise.
    """

    def __init__(
        self,
        config: Config,
        sender: Optional[Sender] = None,
        address_source: AddressSource = lan_address_for,
        logger: Optional[logging.Logger] = None,
        clock: Callable[[], float] = time.monotonic,
        check_seconds: float = CHECK_SECONDS,
    ):
        self._config = config
        self._sender = sender if sender is not None else UrllibSender()
        self._address_source = address_source
        self._logger = logger if logger is not None else logging.getLogger(__name__)
        self._clock = clock
        self._check_seconds = check_seconds
        self._stop = threading.Event()
        #: Address and time of the last attempt, sent or not.
        self._attempted: Optional[str] = None
        self._attempted_at: Optional[float] = None
        #: Address the Hub last acknowledged.
        self._announced: Optional[str] = None
        self._failing = False

    @property
    def enabled(self) -> bool:
        """True when announcements are switched on and every Maker API value
        is present."""
        return bool(self._config.announce_enabled and self._config.maker_configured)

    def tick(self, now: Optional[float] = None) -> bool:
        """Announce if due. Returns True when a request was sent and the Hub
        accepted it."""
        if not self.enabled:
            return False
        moment = self._clock() if now is None else now
        try:
            ip = self._listen_address()
        except OSError as error:
            self._note_failure(f"LAN address lookup for hub {self._config.hub_ip} failed: {error}")
            return False

        address = f"{ip}:{self._config.port}"
        changed = address != self._attempted
        due = (
            self._attempted_at is None
            or moment - self._attempted_at >= self._config.announce_seconds
        )
        if not (changed or due):
            return False

        self._attempted = address
        self._attempted_at = moment
        return self._send(ip, address)

    def _send(self, ip: str, address: str) -> bool:
        config = self._config
        token = config.maker_api_token or ""
        url = build_announce_url(
            config.hub_ip, config.maker_api_app_id, config.maker_api_device_id, ip, config.port, token
        )
        try:
            self._sender.send(url)
        except Exception as error:  # noqa: BLE001 - any failure is logged, never raised
            reason = redact(f"{type(error).__name__}: {error}", token)
            self._note_failure(f"announcement of {address} to hub {config.hub_ip} failed: {reason}")
            return False

        if self._failing or address != self._announced:
            self._logger.info("announced Bridge address %s to hub %s", address, config.hub_ip)
        else:
            self._logger.debug("announced Bridge address %s to hub %s (unchanged)", address, config.hub_ip)
        self._failing = False
        self._announced = address
        return True

    def _listen_address(self) -> str:
        """The address the Bridge is reachable on: a specific `host` as
        typed, or the route-selected LAN address for a wildcard host."""
        host = (self._config.host or "").strip()
        if is_wildcard_host(host):
            return self._address_source(self._config.hub_ip)
        return host

    def _note_failure(self, message: str) -> None:
        """Warn on the transition into failing; debug while it lasts."""
        if self._failing:
            self._logger.debug("%s (still failing)", message)
        else:
            self._failing = True
            self._logger.warning(message)

    def run(self) -> None:
        """Tick now, then every `check_seconds` until `stop()`."""
        self.tick()
        while not self._stop.wait(self._check_seconds):
            self.tick()

    def start(self) -> threading.Thread:
        """Run the announcer on a daemon thread and return it."""
        self._stop.clear()
        thread = threading.Thread(target=self.run, name="moonhalo-announcer", daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        self._stop.set()
