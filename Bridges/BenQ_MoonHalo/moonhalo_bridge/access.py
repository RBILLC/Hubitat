"""Access control for the Bridge: only the Hub (identified by MAC address,
with an optional IP allowlist) may drive the MoonHalo.

`AccessPolicy` is built from the config's `allowed_macs`, `allowed_ips`, and
`allow_loopback`. Given a caller's IP and an `ArpTable`, it decides whether
the request is allowed. The ARP lookup is its own small interface so tests
substitute a `FakeArpTable`; the real one, `WindowsArpTable`, shells out to
`arp -a` and caches nothing across requests.
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

#: IPs treated as loopback for the `allow_loopback` rule.
LOOPBACK_IPS = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1"})

#: Matches exactly 12 hex digits once every separator is stripped.
_HEX12_RE = re.compile(r"^[0-9a-f]{12}$")

#: Default timeout, in seconds, for the `arp -a` subprocess call.
ARP_TIMEOUT = 2.0


def normalize_mac(text: str) -> str:
    """Normalise a MAC address to lower-case, colon-separated form.

    Accepts colons, dashes, or dot-grouped forms (`EC-B5-FA-82-2D-1D`,
    `ec:b5:fa:82:2d:1d`, `ecb5.fa82.2d1d`), with or without surrounding
    whitespace. Raises `ValueError` for anything that is not, once
    separators are stripped, exactly 12 hex digits.
    """
    stripped = text.strip().lower()
    hex_only = stripped.replace(":", "").replace("-", "").replace(".", "")
    if not _HEX12_RE.match(hex_only):
        raise ValueError(f"not a MAC address: {text!r}")
    pairs = [hex_only[i : i + 2] for i in range(0, 12, 2)]
    return ":".join(pairs)


class ArpTable(Protocol):
    """Resolves an IP to a normalised MAC address, or None if unknown."""

    def lookup(self, ip: str) -> Optional[str]:
        ...


class FakeArpTable(dict):
    """An `ArpTable` backed by a plain dict, for tests. Keys are IPs, values
    are MAC strings in any format accepted by `normalize_mac`."""

    def lookup(self, ip: str) -> Optional[str]:
        raw = self.get(ip)
        if raw is None:
            return None
        try:
            return normalize_mac(raw)
        except ValueError:
            return None


#: A runner matching `subprocess.run`'s relevant surface, injected so
#: `WindowsArpTable` can be tested without shelling out.
ArpRunner = Callable[..., "subprocess.CompletedProcess[str]"]


class WindowsArpTable:
    """`ArpTable` backed by the Windows `arp -a <ip>` command.

    Never raises to the caller: a missing entry, "No ARP Entries Found",
    or any parse failure all resolve to None. No caching across requests
    (or across `lookup` calls) since the caller has just sent a packet, so
    the OS's own ARP cache is expected to be fresh.
    """

    def __init__(self, runner: Optional[ArpRunner] = None, timeout: float = ARP_TIMEOUT):
        self._runner = runner if runner is not None else subprocess.run
        self._timeout = timeout

    def lookup(self, ip: str) -> Optional[str]:
        try:
            kwargs = {}
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            result = self._runner(
                ["arp", "-a", ip],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                **kwargs,
            )
        except Exception:
            return None
        if result.returncode != 0:
            return None
        return parse_arp_output(result.stdout, ip)


def parse_arp_output(output: str, ip: str) -> Optional[str]:
    """Parse `arp -a <ip>` output, returning the normalised MAC for the
    line whose first column equals `ip`, or None (including for
    "No ARP Entries Found" or any parse failure)."""
    for line in output.splitlines():
        columns = line.split()
        if len(columns) < 2:
            continue
        if columns[0] != ip:
            continue
        try:
            return normalize_mac(columns[1])
        except ValueError:
            return None
    return None


@dataclass(frozen=True)
class Decision:
    """The result of `AccessPolicy.check`: whether the caller is allowed,
    a human-readable reason, and the resolved MAC (None if never
    resolved, e.g. loopback or an IP-allowlist match)."""

    allowed: bool
    reason: str
    mac: Optional[str]


class AccessPolicy:
    """Decides whether a caller may reach the Bridge, from the config's
    `allowed_macs`, `allowed_ips`, and `allow_loopback`.

    Rules, in order:
    1. Loopback (127.0.0.1, ::1, ::ffff:127.0.0.1) is allowed when
       `allow_loopback` is true.
    2. Both lists empty means open: everyone is allowed.
    3. The caller's IP in `allowed_ips` is allowed.
    4. Otherwise resolve the caller's MAC via `arp` and allow it when it
       is in `allowed_macs` (compared normalised).
    5. Otherwise denied.
    """

    def __init__(self, allowed_macs: list[str], allowed_ips: list[str], allow_loopback: bool):
        self._allowed_macs = {normalize_mac(mac) for mac in allowed_macs}
        self._allowed_ips = set(allowed_ips)
        self._allow_loopback = allow_loopback

    @property
    def is_open(self) -> bool:
        """True when both allowlists are empty, i.e. any caller is
        admitted (other than the loopback rule, which still applies)."""
        return not self._allowed_macs and not self._allowed_ips

    def check(self, remote_ip: str, arp: ArpTable) -> Decision:
        if remote_ip in LOOPBACK_IPS and self._allow_loopback:
            return Decision(allowed=True, reason="loopback", mac=None)

        if self.is_open:
            return Decision(allowed=True, reason="open policy", mac=None)

        if remote_ip in self._allowed_ips:
            return Decision(allowed=True, reason="allowed IP", mac=None)

        mac = arp.lookup(remote_ip)
        if mac is not None and mac in self._allowed_macs:
            return Decision(allowed=True, reason="allowed MAC", mac=mac)

        return Decision(allowed=False, reason="not in allowlist", mac=mac)
