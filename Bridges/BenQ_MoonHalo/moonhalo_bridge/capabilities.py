"""Parse a monitor's DDC/CI capabilities string.

Pure parsing, kept separate from `cli.py` and `ddc.py` so it is testable
without a port or the command-line entry point. The grammar followed here
is ddcutil's `src/vcp/parse_capabilities.c`, as quoted and applied to the
BenQ RD280UG's own string in `docs/research/rd280ug-capabilities.md`
(research for issue #28): the string is a parenthesised expression made of
named segments (`prot(...)`, `type(...)`, `model(...)`, `vcp(...)`, ...);
inside `vcp(...)`, each entry names a VCP register as two hex digits,
optionally followed by a parenthesised, space-separated list of the hex
values the register supports (a Non-Continuous feature). Whitespace before
that parenthesis is inconsistent in real strings (`"7E(0F 11 13)"` has
none, `"7F (01)"` has one) and a register may legitimately appear twice
with different lists (the RD280UG's own string lists `80` twice) -- both
are tolerated here, not treated as errors.

The RD280UG's own string also never closes `vcp(...)` with its own `)`
before appending `mswhql(1)asset_eep(40)mccs_ver(2.2))` -- confirmed
byte-for-byte against the research file, not a transcription slip: the
whole capabilities string is one `(` short of balanced. ddcutil is known
to tolerate malformed capabilities strings from real monitors, so rather
than requiring a matching close paren for `vcp(...)` itself, parsing here
simply stops at the next unmistakable top-level segment name (letters
immediately followed by `(`, e.g. `mswhql(`) if one turns up where a VCP
register was expected.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class VcpEntry:
    """One VCP register advertised in a capabilities string's `vcp(...)`
    segment, in the order the monitor listed it.

    `values` is the register's advertised list of legal hex values (a
    Non-Continuous feature), or None when the string gives no list --
    either because the register is Continuous (its real range comes from
    `GetVCPFeatureAndVCPFeatureReply`, not this string) or because the
    firmware simply did not enumerate one.
    """

    code: int
    values: Optional[tuple[int, ...]]


_CODE_RE = re.compile(r"[0-9A-Fa-f]{2}")
#: A top-level segment name immediately followed by its opening paren,
#: e.g. `mswhql(` or `mccs_ver(`. Used only to recognise where a
#: never-closed `vcp(...)` segment ends (see the module docstring).
_SEGMENT_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\(")


def _find_matching_paren(text: str, open_index: int) -> int:
    """Return the index of the `)` matching the `(` at `open_index`,
    accounting for parentheses nested inside (a `vcp(...)` segment nests
    one level for each entry's value list)."""
    depth = 0
    for i in range(open_index, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    raise ValueError(f"unbalanced parentheses in capabilities string: {text[open_index:]!r}")


def parse_segment(raw: str, name: str) -> Optional[str]:
    """Return the parenthesised value of a top-level segment such as
    `model` or `mccs_ver`, or None if the segment is absent. Top-level
    segments never nest, so a single balanced-paren scan is enough."""
    match = re.search(re.escape(name) + r"\(", raw)
    if match is None:
        return None
    open_index = match.end() - 1
    close_index = _find_matching_paren(raw, open_index)
    return raw[match.end() : close_index]


def parse_vcp_codes(raw: str) -> list[VcpEntry]:
    """Parse the `vcp(...)` segment of a capabilities string into an
    ordered list of `VcpEntry`. Raises ValueError, quoting the offending
    text, if there is no `vcp(` segment or an entry cannot be parsed.
    """
    match = re.search(r"vcp\(", raw)
    if match is None:
        raise ValueError(f"no vcp() segment found in capabilities string: {raw!r}")
    return _parse_vcp_entries(raw, match.end())


def _parse_vcp_entries(raw: str, pos: int) -> list[VcpEntry]:
    entries: list[VcpEntry] = []
    length = len(raw)
    while pos < length:
        while pos < length and raw[pos].isspace():
            pos += 1
        if pos >= length or raw[pos] == ")":
            break

        code_match = _CODE_RE.match(raw, pos)
        if not code_match:
            # A well-formed string ends the vcp() list with `)`, handled
            # above. A malformed-but-tolerable one (see the module
            # docstring) instead runs straight into the next segment
            # name -- treat that as the end of the list too.
            if _SEGMENT_NAME_RE.match(raw, pos):
                break
            raise ValueError(
                f"expected a 2-hex-digit VCP register at {raw[pos:pos + 12]!r} "
                f"in vcp() segment starting {raw[pos - 20 if pos >= 20 else 0:pos]!r}..."
            )
        code = int(code_match.group(), 16)
        pos = code_match.end()

        # A value list's opening paren may or may not be preceded by a
        # space (both appear in the RD280UG's own string).
        peek = pos
        while peek < length and raw[peek].isspace():
            peek += 1

        values: Optional[tuple[int, ...]] = None
        if peek < length and raw[peek] == "(":
            close = _find_matching_paren(raw, peek)
            list_text = raw[peek + 1 : close]
            try:
                values = tuple(int(token, 16) for token in list_text.split())
            except ValueError as error:
                raise ValueError(
                    f"expected a space-separated hex value list in {raw[peek:close + 1]!r}"
                ) from error
            pos = close + 1

        entries.append(VcpEntry(code=code, values=values))
    return entries
