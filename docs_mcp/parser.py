"""Parsing utilities for qualified symbol names.

A *fullname* may contain:

* `::` separated qualifier parts (namespaces and enclosing classes)
* template parameters in `<...>` on any part
* a trailing argument list `(...)` for functions

Examples this module must handle:

    PI
    mynamespace::PI
    mynamespace::math_n::sum(int a, int b)
    mynamespace::math_n::vector<int X>
    mynamespace::math_n::vector<int X>::sum(Vector<X> a, Vector<X> b)

The parser is intentionally permissive: it does not validate identifiers
or types, only structure. Whitespace inside templates / argument lists is
preserved when re-emitted but normalised when comparing signatures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Low-level tokenising helpers
# ---------------------------------------------------------------------------


_OPEN = "<([{"
_CLOSE = ">)]}"


def _depth_iter(s: str):
    """Yield (index, char, depth_before) ignoring quotes (none expected here)."""
    depth = 0
    for i, c in enumerate(s):
        yield i, c, depth
        if c in _OPEN:
            depth += 1
        elif c in _CLOSE:
            depth -= 1


def split_top_level(s: str, sep: str = "::") -> List[str]:
    """Split *s* on *sep*, but only at bracket depth 0."""
    parts: List[str] = []
    last = 0
    i = 0
    n = len(s)
    sep_len = len(sep)
    depth = 0
    while i < n:
        c = s[i]
        if c in _OPEN:
            depth += 1
            i += 1
        elif c in _CLOSE:
            depth -= 1
            i += 1
        elif depth == 0 and s[i : i + sep_len] == sep:
            parts.append(s[last:i])
            i += sep_len
            last = i
        else:
            i += 1
    parts.append(s[last:])
    return parts


def split_args(args_str: str) -> List[str]:
    """Split a function-argument string by top-level commas."""
    if args_str.strip() == "":
        return []
    out: List[str] = []
    last = 0
    depth = 0
    for i, c in enumerate(args_str):
        if c in _OPEN:
            depth += 1
        elif c in _CLOSE:
            depth -= 1
        elif c == "," and depth == 0:
            out.append(args_str[last:i].strip())
            last = i + 1
    tail = args_str[last:].strip()
    if tail:
        out.append(tail)
    return out


def extract_trailing_args(s: str) -> Tuple[str, Optional[str]]:
    """If *s* ends with a top-level (...) group, return (head, inner).

    Otherwise returns (s, None). Only the *outermost* trailing group at
    depth 0 is recognised — nested calls inside templates are left alone.
    """
    s = s.rstrip()
    if not s.endswith(")"):
        return s, None
    # Walk backwards to find the matching opening paren at depth 0
    depth = 0
    for i in range(len(s) - 1, -1, -1):
        c = s[i]
        if c == ")":
            depth += 1
        elif c == "(":
            depth -= 1
            if depth == 0:
                head = s[:i].rstrip()
                inner = s[i + 1 : -1]
                return head, inner
    return s, None  # unbalanced — treat as opaque


def split_name_template(part: str) -> Tuple[str, str]:
    """Split a single qualifier part `name<T>` into (`name`, `<T>`)."""
    part = part.strip()
    if not part or "<" not in part:
        return part, ""
    # First top-level '<'
    depth = 0
    for i, c in enumerate(part):
        if c == "<" and depth == 0:
            return part[:i].strip(), part[i:].strip()
        if c in _OPEN:
            depth += 1
        elif c in _CLOSE:
            depth -= 1
    return part, ""


# ---------------------------------------------------------------------------
# Structured representation
# ---------------------------------------------------------------------------


@dataclass
class Param:
    type: str
    name: str = ""
    default: Optional[str] = None

    def to_dict(self) -> dict:
        d: dict = {"type": self.type}
        if self.name:
            d["name"] = self.name
        if self.default is not None:
            d["default"] = self.default
        return d

    @classmethod
    def from_any(cls, v) -> "Param":
        if isinstance(v, Param):
            return v
        if isinstance(v, str):
            return parse_param(v)
        if isinstance(v, dict):
            return cls(
                type=str(v.get("type", "")).strip(),
                name=str(v.get("name", "")).strip(),
                default=v.get("default"),
            )
        raise TypeError(f"unsupported parameter spec: {v!r}")


def parse_param(spec: str) -> Param:
    """Parse a single parameter spec like `Vector<X> first = {}`.

    The last identifier (no template, no brackets) is taken as the name;
    everything before it is the type. If `=` is present, the right hand
    side is the default. If no obvious name is present, only the type
    field is populated.
    """
    spec = spec.strip()
    default: Optional[str] = None
    eq_at = -1
    depth = 0
    for i, c in enumerate(spec):
        if c in _OPEN:
            depth += 1
        elif c in _CLOSE:
            depth -= 1
        elif c == "=" and depth == 0:
            eq_at = i
            break
    if eq_at >= 0:
        default = spec[eq_at + 1 :].strip()
        spec = spec[:eq_at].rstrip()

    # Walk from the end to find an identifier-looking name token.
    j = len(spec)
    # skip trailing spaces/brackets etc — names are simple identifiers
    while j > 0 and spec[j - 1].isspace():
        j -= 1
    end = j
    while j > 0 and (spec[j - 1].isalnum() or spec[j - 1] == "_"):
        j -= 1
    name = spec[j:end]
    # Reject if name is the entire string (then we have no type) or starts
    # with a digit, or is empty — fall back to no name.
    if not name or name[:1].isdigit() or j == 0:
        return Param(type=spec, name="", default=default)
    typ = spec[:j].rstrip()
    if not typ:
        return Param(type=spec, name="", default=default)
    return Param(type=typ, name=name, default=default)


@dataclass
class ParsedName:
    """Result of parsing a fullname."""

    # Each (name_without_template, template_suffix). For
    # `mynamespace::vector<X>::sum`, parts is
    #   [("mynamespace", ""), ("vector", "<X>"), ("sum", "")]
    parts: List[Tuple[str, str]] = field(default_factory=list)
    args_str: Optional[str] = None  # None = no parens given (not a call)
    params: List[Param] = field(default_factory=list)

    @property
    def is_function_call(self) -> bool:
        return self.args_str is not None

    @property
    def leaf_name(self) -> str:
        return self.parts[-1][0] if self.parts else ""

    @property
    def leaf_template(self) -> str:
        return self.parts[-1][1] if self.parts else ""

    @property
    def qualifier_parts(self) -> List[Tuple[str, str]]:
        """All but the leaf — namespaces + enclosing classes."""
        return self.parts[:-1]

    def fullname_no_args(self) -> str:
        return "::".join(name + tpl for name, tpl in self.parts)

    def signature(self) -> str:
        """Canonical signature for matching: `(t1, t2, ...)` of types only."""
        return "(" + ", ".join(_normalise_type(p.type) for p in self.params) + ")"


def parse_fullname(fullname: str) -> ParsedName:
    fullname = fullname.strip()
    head, args = extract_trailing_args(fullname)
    parts_raw = split_top_level(head, "::")
    parts = [split_name_template(p) for p in parts_raw if p.strip() != ""]
    params: List[Param] = []
    if args is not None:
        for a in split_args(args):
            params.append(parse_param(a))
    return ParsedName(parts=parts, args_str=args, params=params)


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------


def _normalise_type(t: str) -> str:
    """Whitespace-collapse a type string for signature comparison."""
    return " ".join(t.split())


def signature_of(params: List[Param]) -> str:
    return "(" + ", ".join(_normalise_type(p.type) for p in params) + ")"


def signatures_match(a: List[Param], b: List[Param]) -> bool:
    if len(a) != len(b):
        return False
    return all(_normalise_type(x.type) == _normalise_type(y.type) for x, y in zip(a, b))
