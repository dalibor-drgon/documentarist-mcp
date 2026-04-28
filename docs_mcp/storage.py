"""On-disk storage for the documentation MCP.

Layout under the configured root directory:

    docs/<ns>/<ns>/<Class>/__index__.yaml          (class info)
    docs/<ns>/<ns>/<Class>/<method>.yaml           (one or more variant docs)
    docs/<ns>/<ns>/<free_func>.yaml                (free function)
    docs/<ns>/<ns>/<VAR>.yaml                      (variable)
    docs/<leaf>.<file>.yaml                        (static / file-local item)
    index/<short_name>.txt                         (flat reverse index)

Function YAML files are *multi-document* YAML streams: each `---` block
holds one variant (overload). Class and variable YAML files are single
documents. The shape of each document mirrors the MCP `register_*` input.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import yaml

from .parser import (
    Param,
    ParsedName,
    parse_fullname,
    signature_of,
    signatures_match,
)


# ---------------------------------------------------------------------------
# Index file representation
# ---------------------------------------------------------------------------


@dataclass
class IndexEntry:
    kind: str  # "class" | "function" | "variable"
    fullname: str  # with templates
    signature: str = ""  # "(int, int)" — only for functions
    path: str = ""  # forward-slash, relative to root
    is_static: bool = False  # registered with `file` argument

    def render(self) -> str:
        prefix = "static " if self.is_static else ""
        if self.kind == "function":
            return f'{prefix}{self.kind} {self.fullname}{self.signature} at "{self.path}"'
        return f'{prefix}{self.kind} {self.fullname} at "{self.path}"'

    def matches(self, other: "IndexEntry") -> bool:
        """Same logical entry — used to find an existing index line."""
        if self.kind != other.kind or self.fullname != other.fullname:
            return False
        if self.kind == "function":
            return self.signature == other.signature
        return True


_INDEX_RE = re.compile(
    r'^\s*(?P<static>static\s+)?(?P<kind>class|function|variable)\s+'
    r'(?P<rest>.+?)\s+at\s+"(?P<path>[^"]+)"\s*$'
)


def parse_index_line(line: str) -> Optional[IndexEntry]:
    m = _INDEX_RE.match(line)
    if not m:
        return None
    rest = m.group("rest").strip()
    kind = m.group("kind")
    sig = ""
    if kind == "function":
        # peel trailing top-level (...) as signature
        from .parser import extract_trailing_args
        head, args = extract_trailing_args(rest)
        if args is not None:
            rest = head
            sig = "(" + args.strip() + ")"
    return IndexEntry(
        kind=kind,
        fullname=rest,
        signature=sig,
        path=m.group("path"),
        is_static=bool(m.group("static")),
    )


# ---------------------------------------------------------------------------
# Path conventions
# ---------------------------------------------------------------------------


_BAD_FS_CHARS = re.compile(r'[\\/:*?"<>|]+')


def _safe_segment(s: str) -> str:
    """Sanitise a string for use as a single path segment."""
    s = s.strip()
    s = _BAD_FS_CHARS.sub("_", s)
    return s


def docs_path_components(parsed: ParsedName, kind: str, file: Optional[str]) -> Tuple[List[str], str]:
    """Return (directory segments under docs/, filename).

    For classes the filename is `__index__.yaml` and the leaf segment is
    a directory. For functions/variables the filename is `<leaf>.yaml`.
    A non-empty `file` argument suffixes the leaf with `.<file>`.
    """
    qualifier_segments = [_safe_segment(name) for name, _tpl in parsed.qualifier_parts]
    leaf_name = _safe_segment(parsed.leaf_name)
    suffix = ""
    if file:
        suffix = "." + _safe_segment(file)

    if kind == "class":
        dir_segs = qualifier_segments + [leaf_name + suffix]
        return dir_segs, "__index__.yaml"
    # function / variable
    return qualifier_segments, leaf_name + suffix + ".yaml"


# ---------------------------------------------------------------------------
# Storage object
# ---------------------------------------------------------------------------


class Storage:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.docs_root = self.root / "docs"
        self.index_root = self.root / "index"
        self.docs_root.mkdir(parents=True, exist_ok=True)
        self.index_root.mkdir(parents=True, exist_ok=True)

    # ---- path helpers ---------------------------------------------------

    def docs_path(self, parsed: ParsedName, kind: str, file: Optional[str]) -> Path:
        dir_segs, filename = docs_path_components(parsed, kind, file)
        return self.docs_root.joinpath(*dir_segs, filename)

    def docs_relpath(self, abs_path: Path) -> str:
        return "docs/" + abs_path.relative_to(self.docs_root).as_posix()

    def index_path(self, short_name: str) -> Path:
        return self.index_root / (_safe_segment(short_name) + ".txt")

    def abs_from_relpath(self, relpath: str) -> Path:
        # `docs/foo/bar.yaml` -> root/docs/foo/bar.yaml
        relpath = relpath.replace("\\", "/")
        if relpath.startswith("docs/"):
            return self.docs_root / relpath[len("docs/") :]
        return self.root / relpath

    # ---- YAML I/O -------------------------------------------------------

    @staticmethod
    def _load_yaml(path: Path, multi: bool) -> List[dict]:
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return []
        if multi:
            return [d for d in yaml.safe_load_all(text) if d is not None]
        data = yaml.safe_load(text)
        return [data] if data is not None else []

    @staticmethod
    def _dump_yaml(path: Path, docs: List[dict], multi: bool) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if multi:
            text = yaml.safe_dump_all(
                docs, sort_keys=False, default_flow_style=False, allow_unicode=True
            )
        else:
            doc = docs[0] if docs else {}
            text = yaml.safe_dump(
                doc, sort_keys=False, default_flow_style=False, allow_unicode=True
            )
        path.write_text(text, encoding="utf-8")

    def read_class_yaml(self, path: Path) -> dict:
        docs = self._load_yaml(path, multi=False)
        return docs[0] if docs else {}

    def write_class_yaml(self, path: Path, doc: dict) -> None:
        self._dump_yaml(path, [doc], multi=False)

    def read_variants(self, path: Path) -> List[dict]:
        return self._load_yaml(path, multi=True)

    def write_variants(self, path: Path, docs: List[dict]) -> None:
        self._dump_yaml(path, docs, multi=True)

    def read_variable_yaml(self, path: Path) -> dict:
        docs = self._load_yaml(path, multi=False)
        return docs[0] if docs else {}

    def write_variable_yaml(self, path: Path, doc: dict) -> None:
        self._dump_yaml(path, [doc], multi=False)

    # ---- index file I/O ------------------------------------------------

    def read_index(self, short_name: str) -> List[IndexEntry]:
        path = self.index_path(short_name)
        if not path.exists():
            return []
        out: List[IndexEntry] = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            e = parse_index_line(raw)
            if e is not None:
                out.append(e)
        return out

    def write_index(self, short_name: str, entries: List[IndexEntry]) -> None:
        path = self.index_path(short_name)
        if not entries:
            if path.exists():
                path.unlink()
            return
        # Stable order for diff-friendliness
        ordered = sorted(entries, key=lambda e: (e.kind, e.fullname, e.signature))
        text = "\n".join(e.render() for e in ordered) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def upsert_index(self, entry: IndexEntry) -> None:
        entries = self.read_index(_short_name_of(entry.fullname))
        replaced = False
        for i, e in enumerate(entries):
            if e.matches(entry):
                entries[i] = entry
                replaced = True
                break
        if not replaced:
            entries.append(entry)
        self.write_index(_short_name_of(entry.fullname), entries)

    def remove_from_index(self, entry: IndexEntry) -> bool:
        entries = self.read_index(_short_name_of(entry.fullname))
        kept = [e for e in entries if not e.matches(entry)]
        if len(kept) == len(entries):
            return False
        self.write_index(_short_name_of(entry.fullname), kept)
        return True

    # ---- iteration helpers --------------------------------------------

    def iter_index_entries(self) -> Iterable[Tuple[str, IndexEntry]]:
        """Yield (short_name, entry) for every line of every index file."""
        if not self.index_root.exists():
            return
        for p in self.index_root.glob("*.txt"):
            short = p.stem
            for raw in p.read_text(encoding="utf-8").splitlines():
                if not raw.strip():
                    continue
                e = parse_index_line(raw)
                if e is not None:
                    yield short, e


def _short_name_of(fullname: str) -> str:
    parsed = parse_fullname(fullname)
    return parsed.leaf_name


# ---------------------------------------------------------------------------
# High-level operations
# ---------------------------------------------------------------------------


REQUIRED_CLASS_FIELDS = ("short_description", "full_description")
REQUIRED_FUNCTION_FIELDS = ("short_description", "full_description")
REQUIRED_VARIABLE_FIELDS = ("short_description", "full_description")


def _normalise_params(params) -> List[Param]:
    out: List[Param] = []
    if params is None:
        return out
    for p in params:
        out.append(Param.from_any(p))
    return out


def _params_to_yaml(params: List[Param]) -> List[dict]:
    return [p.to_dict() for p in params]


def _params_from_yaml(raw) -> List[Param]:
    if not raw:
        return []
    return [Param.from_any(p) for p in raw]


def _normalise_examples(examples) -> List[dict]:
    """Coerce a list of examples into ``[{title?, description?, code}]``.

    Accepts strings (treated as raw code), or dicts with optional
    ``title`` / ``description`` and required ``code``. ``None`` and
    empty list both yield an empty list.
    """
    if not examples:
        return []
    out: List[dict] = []
    for i, ex in enumerate(examples):
        if isinstance(ex, str):
            out.append({"code": ex})
        elif isinstance(ex, dict):
            d: dict = {}
            if ex.get("title"):
                d["title"] = str(ex["title"])
            if ex.get("description"):
                d["description"] = str(ex["description"])
            code = ex.get("code")
            if code is None:
                # Allow {title, description} with no code, but require at
                # least one populated field.
                if not d:
                    raise ValueError(f"example {i} is empty")
                out.append(d)
                continue
            d["code"] = str(code)
            out.append(d)
        else:
            raise TypeError(f"example {i!r} must be str or dict")
    return out


# ---- call-graph reference encoding ----------------------------------------

# A callee/called-by reference is a single string that uniquely names a
# function variant. Format mirrors the index file:
#
#   "ns::cls::fn(t1, t2)"          - regular
#   "static fn(t1, t2) @file"      - static / file-private (bare leaf)
#
# `make_call_ref` produces the canonical form. `parse_call_ref` reverses
# it to (fullname, params, is_static, file).


def make_call_ref(
    fullname: str,
    params: List[Param],
    is_static: bool = False,
    file: Optional[str] = None,
) -> str:
    sig = signature_of(params)
    base = f"{fullname}{sig}"
    if is_static:
        suffix = f" @{file}" if file else ""
        return f"static {base}{suffix}"
    return base


_CALL_REF_RE = re.compile(
    r"^\s*(?P<static>static\s+)?(?P<rest>.+?)\s*(?:@(?P<file>\S+))?\s*$"
)


def parse_call_ref(ref: str) -> Tuple[str, List[Param], bool, Optional[str]]:
    """Inverse of `make_call_ref`. Returns (fullname, params, static, file)."""
    m = _CALL_REF_RE.match(ref)
    if not m:
        return ref, [], False, None
    is_static = bool(m.group("static"))
    rest = m.group("rest").strip()
    file = m.group("file")
    parsed = parse_fullname(rest)
    return parsed.fullname_no_args(), parsed.params, is_static, file


# ---- function variant lookup ---------------------------------------------


@dataclass
class FunctionLocation:
    path: Path
    rel_path: str
    variant_index: int
    variant: dict
    is_static: bool


def _find_function_variant(
    storage: Storage,
    fullname: str,
    parameters=None,
    file: Optional[str] = None,
) -> Tuple[Optional[FunctionLocation], str]:
    """Resolve a function variant by fullname + optional signature/file.

    Returns ``(location, error)``. On success ``location`` is set and
    ``error`` is empty. On failure ``location`` is ``None`` and
    ``error`` describes why (not found / ambiguous).
    """
    parsed = parse_fullname(fullname)
    fullname_clean = parsed.fullname_no_args()
    target_params = _normalise_params(parameters) if parameters is not None else parsed.params
    has_filter = parameters is not None or parsed.is_function_call
    short = parsed.leaf_name

    entries = [
        e for e in storage.read_index(short)
        if e.kind == "function" and e.fullname == fullname_clean
    ]
    if file is not None:
        entries = [
            e for e in entries
            if e.path.endswith("." + file + ".yaml") or "/" + file + ".yaml" in e.path
        ]
    if not entries:
        return None, f"no function {fullname_clean!r} indexed"

    paths = list({e.path for e in entries})
    if len(paths) > 1:
        return None, f"function {fullname_clean!r} ambiguous across {paths}"
    rel_path = paths[0]
    is_static = entries[0].is_static
    abs_path = storage.abs_from_relpath(rel_path)
    variants = storage.read_variants(abs_path)

    candidates = []
    for i, v in enumerate(variants):
        v_params = _params_from_yaml(v.get("parameters"))
        if has_filter:
            if signatures_match(v_params, target_params):
                candidates.append((i, v))
        else:
            candidates.append((i, v))

    if len(candidates) == 0:
        return None, f"no variant of {fullname_clean!r} matched the signature"
    if len(candidates) > 1 and has_filter:
        # exact-signature match should be unique; pick first to avoid hard error
        idx, v = candidates[0]
        return FunctionLocation(abs_path, rel_path, idx, v, is_static), ""
    if len(candidates) > 1 and not has_filter:
        return None, (
            f"function {fullname_clean!r} has {len(candidates)} variants — "
            "pass `parameters` to disambiguate"
        )
    idx, v = candidates[0]
    return FunctionLocation(abs_path, rel_path, idx, v, is_static), ""


@dataclass
class OperationResult:
    ok: bool
    action: str  # "created" | "updated" | "removed" | "noop"
    path: str  # repo-relative path that was touched
    message: str = ""
    extra: dict = field(default_factory=dict)


# ---- class -----------------------------------------------------------------


def register_class(
    storage: Storage,
    fullname: str,
    short_description: str,
    full_description: str,
    dangers: str = "",
    extends: Optional[str] = None,
    pseudocode: Optional[str] = None,
    file: Optional[str] = None,
    examples=None,
) -> OperationResult:
    parsed = parse_fullname(fullname)
    path = storage.docs_path(parsed, "class", file)
    existed = path.exists()
    prev_extends: Optional[str] = None
    keep_extended_by: List[str] = []
    if existed:
        prev = storage.read_class_yaml(path)
        prev_extends = prev.get("extends")
        keep_extended_by = list(prev.get("extended-by") or [])

    doc: dict = {
        "type": "class",
        "fullname": fullname,
    }
    if extends:
        doc["extends"] = extends
    doc["extended-by"] = keep_extended_by
    doc["short-description"] = short_description
    if dangers:
        doc["dangers"] = dangers
    doc["full-description"] = full_description
    if pseudocode:
        doc["pseudocode"] = pseudocode
    ex = _normalise_examples(examples)
    if ex:
        doc["examples"] = ex
    if file:
        doc["file"] = file

    storage.write_class_yaml(path, doc)

    entry = IndexEntry(
        kind="class",
        fullname=fullname,
        path=storage.docs_relpath(path),
        is_static=bool(file),
    )
    storage.upsert_index(entry)

    # Update parent classes' extended-by lists.
    if prev_extends and prev_extends != extends:
        _modify_extended_by(storage, prev_extends, fullname, add=False)
    if extends:
        _modify_extended_by(storage, extends, fullname, add=True)

    # If anyone already declared they extend us, pull their fullnames in.
    rebuilt = _rebuild_extended_by(storage, fullname, path)
    if rebuilt != keep_extended_by:
        doc["extended-by"] = rebuilt
        storage.write_class_yaml(path, doc)

    return OperationResult(
        ok=True,
        action="updated" if existed else "created",
        path=storage.docs_relpath(path),
    )


def remove_class(
    storage: Storage,
    fullname: str,
    file: Optional[str] = None,
) -> OperationResult:
    parsed = parse_fullname(fullname)
    path = storage.docs_path(parsed, "class", file)
    if not path.exists():
        return OperationResult(ok=False, action="noop", path=storage.docs_relpath(path),
                               message="class not found")
    doc = storage.read_class_yaml(path)
    parent = doc.get("extends")
    children = list(doc.get("extended-by") or [])

    # Refuse if there are still child symbol files inside the folder. The
    # caller should remove children first; we don't recursively delete.
    folder = path.parent
    leftover = [p for p in folder.iterdir() if p.name != "__index__.yaml"]
    if leftover:
        return OperationResult(
            ok=False, action="noop", path=storage.docs_relpath(path),
            message=(f"class folder not empty — remove {len(leftover)} child entries first"),
            extra={"children": [p.name for p in leftover]},
        )

    path.unlink()
    try:
        folder.rmdir()
    except OSError:
        pass

    storage.remove_from_index(IndexEntry(
        kind="class", fullname=fullname,
        path=storage.docs_relpath(path), is_static=bool(file),
    ))

    if parent:
        _modify_extended_by(storage, parent, fullname, add=False)

    return OperationResult(
        ok=True, action="removed", path=storage.docs_relpath(path),
        extra={"orphaned_children": children},
    )


def _modify_extended_by(storage: Storage, parent_fullname: str, child_fullname: str, add: bool) -> bool:
    """Add or remove `child_fullname` from `parent_fullname`'s extended-by list."""
    parent_path = _find_class_path(storage, parent_fullname)
    if parent_path is None:
        return False
    doc = storage.read_class_yaml(parent_path)
    lst = list(doc.get("extended-by") or [])
    changed = False
    if add and child_fullname not in lst:
        lst.append(child_fullname)
        changed = True
    elif (not add) and child_fullname in lst:
        lst = [x for x in lst if x != child_fullname]
        changed = True
    if changed:
        doc["extended-by"] = lst
        storage.write_class_yaml(parent_path, doc)
    return changed


def _rebuild_extended_by(storage: Storage, parent_fullname: str, parent_path: Path) -> List[str]:
    """Walk the index, collect every class whose `extends` matches `parent_fullname`."""
    found: List[str] = []
    seen = set()
    for _short, entry in storage.iter_index_entries():
        if entry.kind != "class":
            continue
        if entry.fullname == parent_fullname:
            continue
        abs_path = storage.abs_from_relpath(entry.path)
        if abs_path == parent_path:
            continue
        try:
            d = storage.read_class_yaml(abs_path)
        except Exception:
            continue
        if d.get("extends") == parent_fullname and entry.fullname not in seen:
            found.append(entry.fullname)
            seen.add(entry.fullname)
    found.sort()
    return found


def _find_class_path(storage: Storage, fullname: str) -> Optional[Path]:
    short = _short_name_of(fullname)
    for e in storage.read_index(short):
        if e.kind == "class" and e.fullname == fullname:
            return storage.abs_from_relpath(e.path)
    return None


# ---- function -------------------------------------------------------------


def register_function(
    storage: Storage,
    fullname: str,
    short_description: str,
    full_description: str,
    parameters=None,
    returns: Optional[str] = None,
    dangers: str = "",
    overrides: Optional[List[str]] = None,
    pseudocode: Optional[str] = None,
    file: Optional[str] = None,
    examples=None,
) -> OperationResult:
    parsed = parse_fullname(fullname)
    params = _normalise_params(parameters)
    if not params and parsed.params:
        params = parsed.params
    fullname_clean = parsed.fullname_no_args()

    path = storage.docs_path(parsed, "function", file)
    variants = storage.read_variants(path) if path.exists() else []

    # Find existing variant with same signature (if any) so we can
    # preserve auto-managed call-graph fields across an update.
    existing_callees: List[str] = []
    existing_called_by: List[str] = []
    replaced_idx = -1
    for i, v in enumerate(variants):
        existing_params = _params_from_yaml(v.get("parameters"))
        if v.get("fullname") == fullname_clean and signatures_match(existing_params, params):
            existing_callees = list(v.get("callees") or [])
            existing_called_by = list(v.get("called-by") or [])
            replaced_idx = i
            break

    new_variant: dict = {
        "type": "function",
        "fullname": fullname_clean,
        "parameters": _params_to_yaml(params),
    }
    if returns:
        new_variant["returns"] = returns
    if overrides:
        new_variant["overrides"] = list(overrides)
    new_variant["short-description"] = short_description
    if dangers:
        new_variant["dangers"] = dangers
    new_variant["full-description"] = full_description
    if pseudocode:
        new_variant["pseudocode"] = pseudocode
    ex = _normalise_examples(examples)
    if ex:
        new_variant["examples"] = ex
    # Preserve call-graph edges across re-registration. They are managed
    # by add_callee / remove_callee, not by register_function.
    if existing_callees:
        new_variant["callees"] = existing_callees
    if existing_called_by:
        new_variant["called-by"] = existing_called_by
    if file:
        new_variant["file"] = file

    if replaced_idx >= 0:
        variants[replaced_idx] = new_variant
        replaced = True
    else:
        variants.append(new_variant)
        replaced = False

    storage.write_variants(path, variants)

    entry = IndexEntry(
        kind="function",
        fullname=fullname_clean,
        signature=signature_of(params),
        path=storage.docs_relpath(path),
        is_static=bool(file),
    )
    storage.upsert_index(entry)

    # If anyone else already declared they call us, surface those edges
    # in our `called-by` field. (The reverse direction is filled in at
    # add_callee time; this catches callers registered earlier whose
    # add_callee target didn't yet exist.)
    if not replaced:
        own_ref = make_call_ref(fullname_clean, params, bool(file), file)
        incoming = _collect_incoming_callers(storage, own_ref, exclude_path=storage.docs_relpath(path))
        if incoming:
            merged = list(new_variant.get("called-by") or [])
            for ref in incoming:
                if ref not in merged:
                    merged.append(ref)
            new_variant["called-by"] = merged
            storage.write_variants(path, variants)

    return OperationResult(
        ok=True,
        action="updated" if replaced else "created",
        path=storage.docs_relpath(path),
    )


def _collect_incoming_callers(storage: Storage, own_ref: str, exclude_path: str) -> List[str]:
    """Walk every function variant and collect the refs of those whose
    ``callees`` mention `own_ref`."""
    out: List[str] = []
    seen = set()
    for _short, e in storage.iter_index_entries():
        if e.kind != "function":
            continue
        if e.path == exclude_path:
            continue
        if e.path in seen:
            continue
        seen.add(e.path)
        abs_path = storage.abs_from_relpath(e.path)
        if not abs_path.exists():
            continue
        for v in storage.read_variants(abs_path):
            callees = v.get("callees") or []
            if own_ref in callees:
                v_params = _params_from_yaml(v.get("parameters"))
                ref = make_call_ref(
                    str(v.get("fullname", e.fullname)),
                    v_params,
                    e.is_static,
                    v.get("file") if e.is_static else None,
                )
                if ref not in out:
                    out.append(ref)
    return out


def remove_function(
    storage: Storage,
    fullname: str,
    parameters=None,
    file: Optional[str] = None,
) -> OperationResult:
    parsed = parse_fullname(fullname)
    fullname_clean = parsed.fullname_no_args()
    path = storage.docs_path(parsed, "function", file)
    if not path.exists():
        return OperationResult(ok=False, action="noop",
                               path=storage.docs_relpath(path),
                               message="function file not found")
    variants = storage.read_variants(path)

    target_params: List[Param]
    if parameters is not None:
        target_params = _normalise_params(parameters)
    elif parsed.is_function_call:
        target_params = parsed.params
    else:
        target_params = []  # match-all

    if parameters is None and not parsed.is_function_call:
        # remove the whole file (all variants)
        kept: List[dict] = []
        removed_sigs = [signature_of(_params_from_yaml(v.get("parameters"))) for v in variants]
    else:
        kept = []
        removed_sigs = []
        for v in variants:
            existing = _params_from_yaml(v.get("parameters"))
            if v.get("fullname") == fullname_clean and signatures_match(existing, target_params):
                removed_sigs.append(signature_of(existing))
                continue
            kept.append(v)

    if not removed_sigs:
        return OperationResult(ok=False, action="noop",
                               path=storage.docs_relpath(path),
                               message="no matching variant")

    if kept:
        storage.write_variants(path, kept)
    else:
        path.unlink()
        # Drop any now-empty parent folder up to docs_root
        try:
            path.parent.rmdir()
        except OSError:
            pass

    # Index: remove one entry per removed signature; if any variants of
    # the same fullname remain, keep one entry per remaining signature.
    for sig in removed_sigs:
        storage.remove_from_index(IndexEntry(
            kind="function", fullname=fullname_clean, signature=sig,
            path=storage.docs_relpath(path), is_static=bool(file),
        ))
    for v in kept:
        existing = _params_from_yaml(v.get("parameters"))
        storage.upsert_index(IndexEntry(
            kind="function", fullname=fullname_clean,
            signature=signature_of(existing),
            path=storage.docs_relpath(path),
            is_static=bool(file),
        ))

    return OperationResult(ok=True, action="removed",
                           path=storage.docs_relpath(path),
                           extra={"removed_variants": removed_sigs})


# ---- variable -------------------------------------------------------------


def register_variable(
    storage: Storage,
    fullname: str,
    short_description: str,
    full_description: str,
    var_type: Optional[str] = None,
    dangers: str = "",
    pseudocode: Optional[str] = None,
    file: Optional[str] = None,
    examples=None,
) -> OperationResult:
    parsed = parse_fullname(fullname)
    path = storage.docs_path(parsed, "variable", file)
    existed = path.exists()

    doc: dict = {
        "type": "variable",
        "fullname": fullname,
    }
    if var_type:
        doc["var-type"] = var_type
    doc["short-description"] = short_description
    if dangers:
        doc["dangers"] = dangers
    doc["full-description"] = full_description
    if pseudocode:
        doc["pseudocode"] = pseudocode
    ex = _normalise_examples(examples)
    if ex:
        doc["examples"] = ex
    if file:
        doc["file"] = file

    storage.write_variable_yaml(path, doc)

    storage.upsert_index(IndexEntry(
        kind="variable", fullname=fullname,
        path=storage.docs_relpath(path), is_static=bool(file),
    ))

    return OperationResult(
        ok=True,
        action="updated" if existed else "created",
        path=storage.docs_relpath(path),
    )


def remove_variable(
    storage: Storage,
    fullname: str,
    file: Optional[str] = None,
) -> OperationResult:
    parsed = parse_fullname(fullname)
    path = storage.docs_path(parsed, "variable", file)
    if not path.exists():
        return OperationResult(ok=False, action="noop",
                               path=storage.docs_relpath(path),
                               message="variable not found")
    path.unlink()
    try:
        path.parent.rmdir()
    except OSError:
        pass
    storage.remove_from_index(IndexEntry(
        kind="variable", fullname=fullname,
        path=storage.docs_relpath(path), is_static=bool(file),
    ))
    return OperationResult(ok=True, action="removed", path=storage.docs_relpath(path))


# ---- call-graph ----------------------------------------------------------


def _write_variant(storage: Storage, loc: FunctionLocation, new_variant: dict) -> None:
    """Persist a single variant change."""
    variants = storage.read_variants(loc.path)
    variants[loc.variant_index] = new_variant
    storage.write_variants(loc.path, variants)


def add_callee(
    storage: Storage,
    caller: str,
    callee: str,
    caller_parameters=None,
    callee_parameters=None,
    caller_file: Optional[str] = None,
    callee_file: Optional[str] = None,
) -> OperationResult:
    """Record that `caller` calls `callee`.

    Both sides are updated:
      * `caller`'s variant gets `callee_ref` appended to ``callees``.
      * `callee`'s variant gets `caller_ref` appended to ``called-by``.

    If `callee` is not yet documented, the edge is still recorded on
    `caller`'s side. When `callee` is later registered, the missing
    ``called-by`` entry is auto-filled by `register_function` from the
    forward-edge scan.

    Disambiguation: if a name has multiple variants and you don't pass
    `*_parameters`, the call returns ``ok=false`` with a message — pass
    parameters to pick a variant.
    """
    caller_loc, caller_err = _find_function_variant(
        storage, caller, caller_parameters, caller_file,
    )
    if caller_loc is None:
        return OperationResult(ok=False, action="noop", path="",
                               message=f"caller: {caller_err}")
    caller_ref = make_call_ref(
        str(caller_loc.variant.get("fullname", caller)),
        _params_from_yaml(caller_loc.variant.get("parameters")),
        caller_loc.is_static,
        caller_loc.variant.get("file"),
    )

    # Try to resolve callee. If not found, record on caller only.
    callee_loc, callee_err = _find_function_variant(
        storage, callee, callee_parameters, callee_file,
    )

    if callee_loc is not None:
        callee_ref = make_call_ref(
            str(callee_loc.variant.get("fullname", callee)),
            _params_from_yaml(callee_loc.variant.get("parameters")),
            callee_loc.is_static,
            callee_loc.variant.get("file"),
        )
    else:
        # Build a forward-only ref from the user-supplied name+params.
        parsed_callee = parse_fullname(callee)
        params = _normalise_params(callee_parameters)
        if not params and parsed_callee.params:
            params = parsed_callee.params
        callee_ref = make_call_ref(
            parsed_callee.fullname_no_args(), params,
            bool(callee_file), callee_file,
        )

    # Update caller side.
    cv = dict(caller_loc.variant)
    callees = list(cv.get("callees") or [])
    added_callee = callee_ref not in callees
    if added_callee:
        callees.append(callee_ref)
    cv["callees"] = callees
    _write_variant(storage, caller_loc, cv)

    # Update callee side, if it exists.
    added_called_by = False
    if callee_loc is not None:
        kv = dict(callee_loc.variant)
        cb = list(kv.get("called-by") or [])
        if caller_ref not in cb:
            cb.append(caller_ref)
            added_called_by = True
        kv["called-by"] = cb
        _write_variant(storage, callee_loc, kv)

    msg = ""
    if callee_loc is None:
        msg = f"callee not yet documented: {callee_err}; recorded on caller only"

    return OperationResult(
        ok=True,
        action="updated",
        path=caller_loc.rel_path,
        message=msg,
        extra={
            "caller_ref": caller_ref,
            "callee_ref": callee_ref,
            "caller_path": caller_loc.rel_path,
            "callee_path": callee_loc.rel_path if callee_loc else None,
            "added_callee": added_callee,
            "added_called_by": added_called_by,
        },
    )


def remove_callee(
    storage: Storage,
    caller: str,
    callee: str,
    caller_parameters=None,
    callee_parameters=None,
    caller_file: Optional[str] = None,
    callee_file: Optional[str] = None,
) -> OperationResult:
    """Drop the edge created by `add_callee`. Symmetric — clears both
    sides if both exist."""
    caller_loc, caller_err = _find_function_variant(
        storage, caller, caller_parameters, caller_file,
    )
    if caller_loc is None:
        return OperationResult(ok=False, action="noop", path="",
                               message=f"caller: {caller_err}")
    caller_ref = make_call_ref(
        str(caller_loc.variant.get("fullname", caller)),
        _params_from_yaml(caller_loc.variant.get("parameters")),
        caller_loc.is_static,
        caller_loc.variant.get("file"),
    )

    callee_loc, _err = _find_function_variant(
        storage, callee, callee_parameters, callee_file,
    )

    # Drop from caller's callees: any ref that resolves to the same
    # canonical (fullname, signature) wins.
    cv = dict(caller_loc.variant)
    callees = list(cv.get("callees") or [])
    parsed_callee = parse_fullname(callee)
    fullname_clean = parsed_callee.fullname_no_args()
    target_params = _normalise_params(callee_parameters) if callee_parameters is not None else parsed_callee.params

    def _ref_matches(ref: str) -> bool:
        fname, params, _is_st, _f = parse_call_ref(ref)
        if fname != fullname_clean:
            return False
        if not target_params:
            return True
        return signatures_match(params, target_params)

    new_callees = [r for r in callees if not _ref_matches(r)]
    removed_callee = len(new_callees) != len(callees)
    cv["callees"] = new_callees
    _write_variant(storage, caller_loc, cv)

    removed_called_by = False
    if callee_loc is not None:
        kv = dict(callee_loc.variant)
        cb = list(kv.get("called-by") or [])
        new_cb = [r for r in cb if r != caller_ref]
        if len(new_cb) != len(cb):
            removed_called_by = True
        kv["called-by"] = new_cb
        _write_variant(storage, callee_loc, kv)

    if not removed_callee and not removed_called_by:
        return OperationResult(ok=False, action="noop", path=caller_loc.rel_path,
                               message="no matching edge found")

    return OperationResult(
        ok=True,
        action="removed",
        path=caller_loc.rel_path,
        extra={
            "removed_callee": removed_callee,
            "removed_called_by": removed_called_by,
        },
    )


# ---- retrieval -----------------------------------------------------------


@dataclass
class RetrieveResult:
    found: bool
    mode: str  # "exact" | "short" | "miss"
    short_name: str = ""
    matches: List[dict] = field(default_factory=list)


# Heavy fields are stripped from retrieved docs unless explicitly
# requested. The default `retrieve` view returns only the contract
# (short-description, dangers, parameters, returns, extends, overrides
# etc.) so the caller's context window is not blown by long
# descriptions or large call graphs.
_HEAVY_FIELDS = {
    "full_description": "full-description",
    "examples":         "examples",
    "callees":          "callees",
    "called_by":        "called-by",
    "pseudocode":       "pseudocode",
}


def _filter_doc(doc: dict, includes: dict) -> dict:
    """Return a copy of *doc* with omitted heavy fields stripped, and a
    summary marker for each so the caller knows the field exists."""
    out = dict(doc)
    for flag, key in _HEAVY_FIELDS.items():
        if includes.get(flag):
            continue
        if key in out:
            val = out.pop(key)
            # Replace the stripped field with a count/length hint so the
            # consumer can decide whether to ask for it.
            if isinstance(val, list):
                out.setdefault("_omitted", {})[key] = {"items": len(val)}
            elif isinstance(val, str):
                out.setdefault("_omitted", {})[key] = {"chars": len(val)}
            else:
                out.setdefault("_omitted", {})[key] = True
    return out


def retrieve(
    storage: Storage,
    name: str,
    parameters=None,
    file: Optional[str] = None,
    include_full_description: bool = False,
    include_examples: bool = False,
    include_callees: bool = False,
    include_called_by: bool = False,
    include_pseudocode: bool = False,
) -> RetrieveResult:
    """Look up by fullname; fall back to short-name listing.

    Resolution rules:
      * If `name` is fully qualified (contains ``::``) and matches an
        index entry exactly, return that single doc — narrowed by
        `parameters` if supplied. mode=``exact``.
      * If `name` is fully qualified but no exact match, fall back to
        returning every entry in `index/<short>.txt`. mode=``short``.
      * If `name` is a short name (no ``::``), always return every
        entry in `index/<short>.txt` (filtered by `parameters` if
        supplied). mode=``short``.
      * If `index/<short>.txt` does not exist at all, mode=``miss``.

    Heavy fields (``full-description``, ``examples``, ``callees``,
    ``called-by``, ``pseudocode``) are stripped by default. Each
    ``include_*`` toggle re-enables one. Stripped fields leave a hint
    under the ``_omitted`` map so callers can see they exist without
    paying for them.

    `file` filters static/file-private entries: ``"vector.c"`` matches
    paths ending in ``.vector.c.yaml``.
    """
    includes = {
        "full_description": include_full_description,
        "examples":         include_examples,
        "callees":          include_callees,
        "called_by":        include_called_by,
        "pseudocode":       include_pseudocode,
    }
    parsed = parse_fullname(name)
    short = parsed.leaf_name
    if not short:
        return RetrieveResult(found=False, mode="miss")
    entries = storage.read_index(short)
    if not entries:
        return RetrieveResult(found=False, mode="miss", short_name=short)

    target_params = _normalise_params(parameters) if parameters is not None else parsed.params
    has_param_filter = parameters is not None or parsed.is_function_call

    fullname_clean = parsed.fullname_no_args()
    qualified = "::" in fullname_clean

    def _matches_file(e: IndexEntry) -> bool:
        if file is None:
            return True
        return e.path.endswith("." + file + ".yaml") or (
            "/" + file + ".yaml" in e.path
        )

    # Pick candidate entries.
    mode = "short"
    if qualified:
        exact = [e for e in entries if e.fullname == fullname_clean and _matches_file(e)]
        if exact:
            candidates = exact
            mode = "exact"
        else:
            candidates = [e for e in entries if _matches_file(e)]
    else:
        candidates = [e for e in entries if _matches_file(e)]

    if not candidates:
        return RetrieveResult(found=False, mode="miss", short_name=short)

    # Read each candidate file (dedup by path) and apply the param
    # filter for functions.
    results: List[dict] = []
    seen_paths: set = set()
    for e in candidates:
        if e.path in seen_paths:
            continue
        seen_paths.add(e.path)
        abs_path = storage.abs_from_relpath(e.path)
        if not abs_path.exists():
            continue
        if e.kind == "function":
            for v in storage.read_variants(abs_path):
                existing = _params_from_yaml(v.get("parameters"))
                if has_param_filter and not signatures_match(existing, target_params):
                    continue
                ve = IndexEntry(
                    kind="function",
                    fullname=str(v.get("fullname", e.fullname)),
                    signature=signature_of(existing),
                    path=e.path,
                    is_static=e.is_static,
                )
                results.append({"entry": _entry_to_dict(ve),
                                "doc": _filter_doc(v, includes)})
        elif e.kind == "class":
            results.append({"entry": _entry_to_dict(e),
                            "doc": _filter_doc(storage.read_class_yaml(abs_path), includes)})
        elif e.kind == "variable":
            results.append({"entry": _entry_to_dict(e),
                            "doc": _filter_doc(storage.read_variable_yaml(abs_path), includes)})

    if not results:
        return RetrieveResult(found=False, mode="miss", short_name=short)
    return RetrieveResult(found=True, mode=mode, short_name=short, matches=results)


def _entry_to_dict(e: IndexEntry) -> dict:
    d: dict = {"kind": e.kind, "fullname": e.fullname, "path": e.path}
    if e.signature:
        d["signature"] = e.signature
    if e.is_static:
        d["static"] = True
    return d


# ---- search ---------------------------------------------------------------


def search(storage: Storage, short_name: str) -> List[dict]:
    """Return raw index entries for *short_name* (no doc bodies)."""
    return [_entry_to_dict(e) for e in storage.read_index(short_name)]


def list_namespace(storage: Storage, namespace: str) -> List[dict]:
    """List every index entry whose fullname starts with `namespace::`."""
    prefix = namespace.rstrip(":")
    out: List[dict] = []
    for _short, e in storage.iter_index_entries():
        if not prefix:
            out.append(_entry_to_dict(e))
            continue
        if e.fullname.startswith(prefix + "::") or e.fullname == prefix:
            out.append(_entry_to_dict(e))
    return out
