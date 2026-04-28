"""FastMCP server exposing documentation tools.

Run as ``python -m docs_mcp``. Set ``DOCUMENTATOR_ROOT`` to point at the
directory that should hold ``docs/`` and ``index/``; defaults to the
current working directory.

All tools accept and return plain JSON-serialisable dictionaries so they
work uniformly across MCP clients.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List, Optional

from mcp.server.fastmcp import FastMCP

from . import storage as st


def _root() -> Path:
    return Path(os.environ.get("DOCUMENTATOR_ROOT", os.getcwd())).resolve()


def _store() -> st.Storage:
    return st.Storage(_root())


mcp = FastMCP("documentator")


# ---------------------------------------------------------------------------
# Registration tools
# ---------------------------------------------------------------------------


@mcp.tool()
def register_class(
    fullname: str,
    short_description: str,
    full_description: str,
    dangers: str = "",
    extends: Optional[str] = None,
    pseudocode: Optional[str] = None,
    file: Optional[str] = None,
    examples: Optional[List[Any]] = None,
) -> dict:
    """Register or update a class in the documentation store.

    Use this for classes, structs, interfaces, or any aggregate type. The
    `fullname` MUST include all enclosing namespaces / outer classes
    separated by ``::`` and may include template parameters, e.g.
    ``mynamespace::math_n::vector<int X>``.

    `dangers` is critical on a microcontroller codebase: spell out the
    *thread-safety* contract here (ISR-safe? task-only? requires which
    lock?) — silent thread-safety assumptions are the most common
    source of bugs. If a class is touched from both ISR and task
    context, document EXACTLY which lock guards which member, and what
    happens on contention.

    Args:
      fullname: Fully-qualified class name with templates if any.
      short_description: One-sentence summary surfaced in listings.
      full_description: Implementation details, lifecycle, threading
        contract, ownership, expected caller behaviour. Multi-line OK.
      dangers: Footguns, invariants, locking requirements. Quote the
        exact lock name (e.g. "irq_lock", "scheduler_lock"). Empty
        only if there are truly no caveats — that is rare on MCU code.
      extends: Fullname of the parent class. The parent's
        ``extended-by`` list is auto-updated. Pass ``null`` to remove.
      pseudocode: Optional pseudocode for non-obvious algorithms.
      file: For file-private classes (e.g. C `static` types defined in
        a single ``.c`` file). The leaf folder name is suffixed with
        ``.<file>`` to disambiguate.
      examples: List of usage examples. Each item is either a string
        (raw code) or ``{title?, description?, code}``. Supply at least
        one when the API is non-trivial — examples are the cheapest way
        to convey the contract.

    Returns: ``{ok, action, path, ...}``.
    """
    res = st.register_class(
        _store(), fullname, short_description, full_description,
        dangers=dangers, extends=extends, pseudocode=pseudocode, file=file,
        examples=examples,
    )
    return _result_dict(res)


@mcp.tool()
def register_function(
    fullname: str,
    short_description: str,
    full_description: str,
    parameters: Optional[List[Any]] = None,
    returns: Optional[str] = None,
    dangers: str = "",
    overrides: Optional[List[str]] = None,
    pseudocode: Optional[str] = None,
    file: Optional[str] = None,
    examples: Optional[List[Any]] = None,
) -> dict:
    """Register or update a function / method variant.

    Multiple overloads of the same function (same fullname, different
    parameters) all live in one YAML file as separate documents. Calling
    this tool inserts a new variant or replaces the variant whose
    parameter *types* match (parameter names are not part of the key).

    `dangers` MUST document thread-safety on this codebase. State the
    execution context the function is intended for (task / ISR / both)
    and the lock that must be held by the caller (e.g. ``irq_lock``,
    ``scheduler_lock``). The most common bug class in this codebase is
    a routine called from both contexts without a lock, or with the
    wrong lock — your description is what prevents that.

    `callees` and `called-by` are NOT set here — they are managed by
    the dedicated ``add_callee`` / ``remove_callee`` tools and are
    preserved across re-registration.

    Args:
      fullname: ``ns::cls<T>::name`` — without trailing ``(...)``.
        (You may include the ``(...)`` for convenience; the parser will
        peel it off and use it as parameters if `parameters` is null.)
      short_description: One-sentence summary.
      full_description: Side effects, error modes, callbacks, ownership
        transfers. Repeat the key thread-safety claim here too.
      parameters: List of ``{type, name?, default?}`` objects, in order.
        Empty list = takes no parameters. ``null`` only when you also
        embedded the parameter list in `fullname`.
      returns: Return type (string). Optional.
      dangers: Caller-must-know warnings — thread-safety FIRST. Name
        the lock by its actual symbol.
      overrides: List of base-class fullnames+signatures this variant
        overrides, e.g. ``["matrix::sum(vector, vector)"]``.
      pseudocode: Optional.
      file: For static / file-private functions.
      examples: Usage examples. Each item is a string (raw code) or
        ``{title?, description?, code}``. Strongly encouraged when the
        function's contract or threading rules are non-trivial.

    Returns: ``{ok, action, path}``.
    """
    res = st.register_function(
        _store(), fullname, short_description, full_description,
        parameters=parameters, returns=returns, dangers=dangers,
        overrides=overrides, pseudocode=pseudocode, file=file,
        examples=examples,
    )
    return _result_dict(res)


@mcp.tool()
def register_variable(
    fullname: str,
    short_description: str,
    full_description: str,
    var_type: Optional[str] = None,
    dangers: str = "",
    pseudocode: Optional[str] = None,
    file: Optional[str] = None,
    examples: Optional[List[Any]] = None,
) -> dict:
    """Register or update a variable, constant, or class field.

    For shared mutable state, `dangers` MUST name the lock that
    protects it and the contexts (task / ISR) that read or write it.
    Unprotected globals touched from both contexts are the canonical
    Heisenbug on this codebase.

    Args:
      fullname: ``ns::cls::NAME``. For class fields, use the enclosing
        class as a qualifier.
      short_description: One-sentence summary.
      full_description: Lifetime, initialisation order, who writes it,
        access rules. State the read/write contexts explicitly.
      var_type: The declared type (string), e.g. ``const uint32_t`` or
        ``volatile struct foo *``.
      dangers: Threading / locking / aliasing warnings.
      pseudocode: Optional.
      file: For static / file-private variables.
      examples: Optional usage examples (strings or ``{title?, description?, code}``).
    """
    res = st.register_variable(
        _store(), fullname, short_description, full_description,
        var_type=var_type, dangers=dangers, pseudocode=pseudocode, file=file,
        examples=examples,
    )
    return _result_dict(res)


# ---------------------------------------------------------------------------
# Removal tools
# ---------------------------------------------------------------------------


@mcp.tool()
def remove_class(fullname: str, file: Optional[str] = None) -> dict:
    """Remove a class entry.

    Fails if the class folder still contains documented members
    (methods, fields, nested classes). Remove those first.
    """
    return _result_dict(st.remove_class(_store(), fullname, file=file))


@mcp.tool()
def remove_function(
    fullname: str,
    parameters: Optional[List[Any]] = None,
    file: Optional[str] = None,
) -> dict:
    """Remove a function. With `parameters` given, removes that variant
    only; without, removes every variant (whole file)."""
    return _result_dict(st.remove_function(
        _store(), fullname, parameters=parameters, file=file,
    ))


@mcp.tool()
def remove_variable(fullname: str, file: Optional[str] = None) -> dict:
    """Remove a variable entry."""
    return _result_dict(st.remove_variable(_store(), fullname, file=file))


# ---------------------------------------------------------------------------
# Call-graph tools — used to backtrack thread-safety issues across
# functions reachable in either direction (callee tree, caller tree).
# ---------------------------------------------------------------------------


@mcp.tool()
def add_callee(
    caller: str,
    callee: str,
    caller_parameters: Optional[List[Any]] = None,
    callee_parameters: Optional[List[Any]] = None,
    caller_file: Optional[str] = None,
    callee_file: Optional[str] = None,
) -> dict:
    """Record that `caller` calls `callee`. Updates BOTH sides:

      * adds `callee` to `caller`'s `callees` list
      * adds `caller` to `callee`'s `called-by` list

    If the callee is not yet documented, only the caller side is
    written; the back-edge is filled in later when the callee is
    registered (the index is scanned at register time).

    Disambiguating overloads: if either side has multiple variants
    with the same fullname, pass the corresponding `*_parameters` to
    pick the right one. Without parameters and with multiple variants
    the call returns ``ok=false``.

    This is the primary tool an agent uses to build the call graph for
    *thread-safety auditing*: by walking ``callees`` downward and
    ``called-by`` upward, you can prove which contexts (task / ISR)
    can ever reach a given function.

    Args:
      caller: Fullname of the calling function (``ns::cls::fn``).
      callee: Fullname of the called function.
      caller_parameters: Param list to disambiguate caller overloads.
      callee_parameters: Param list to disambiguate callee overloads.
      caller_file / callee_file: Hints for static / file-private functions.
    """
    res = st.add_callee(
        _store(), caller, callee,
        caller_parameters=caller_parameters,
        callee_parameters=callee_parameters,
        caller_file=caller_file, callee_file=callee_file,
    )
    return _result_dict(res)


@mcp.tool()
def remove_callee(
    caller: str,
    callee: str,
    caller_parameters: Optional[List[Any]] = None,
    callee_parameters: Optional[List[Any]] = None,
    caller_file: Optional[str] = None,
    callee_file: Optional[str] = None,
) -> dict:
    """Inverse of `add_callee`. Removes the edge from both sides."""
    res = st.remove_callee(
        _store(), caller, callee,
        caller_parameters=caller_parameters,
        callee_parameters=callee_parameters,
        caller_file=caller_file, callee_file=callee_file,
    )
    return _result_dict(res)


# ---------------------------------------------------------------------------
# Retrieval tools
# ---------------------------------------------------------------------------


@mcp.tool()
def retrieve(
    name: str,
    parameters: Optional[List[Any]] = None,
    file: Optional[str] = None,
    include_full_description: bool = False,
    include_examples: bool = False,
    include_callees: bool = False,
    include_called_by: bool = False,
    include_pseudocode: bool = False,
) -> dict:
    """Look up documentation by name.

    Resolution order:
      1. Treat `name` as a fully-qualified name. If found in the index
         exactly, return that one document (or the matching variant for
         a function whose `parameters` you supplied).
      2. If not found and `name` is a *short* name (no ``::``), return
         every index entry for that short name, with their YAML bodies.
      3. Otherwise return ``found=false``.

    By default the response is *lightweight*: it contains
    ``short-description``, ``dangers``, ``parameters``, ``returns``,
    ``extends`` / ``extended-by`` / ``overrides``, plus a
    ``_omitted`` map that lists which heavy fields were stripped.
    Heavy fields are not loaded unless you opt in:

      * ``include_full_description`` — the prose contract.
      * ``include_examples``         — usage code blocks.
      * ``include_callees``          — outgoing call edges.
      * ``include_called_by``        — incoming call edges.
      * ``include_pseudocode``       — pseudocode block.

    Toggle ONLY what you need; this keeps your context window small
    when you are walking a call graph or scanning many symbols.

    Args:
      name: Fully-qualified or short symbol name. Trailing ``(...)`` is
        accepted and used as a parameter filter when `parameters` is
        null.
      parameters: Optional list of params (same shape as register).
        Disambiguates function overloads.
      file: Hint for static items — ``"vector.c"`` matches entries
        whose path includes ``.vector.c.yaml``.

    Returns: ``{found, mode, short_name, matches}``. `mode` is one of
    "exact", "short", or "miss". Each match is ``{entry, doc}``.
    """
    res = st.retrieve(
        _store(), name, parameters=parameters, file=file,
        include_full_description=include_full_description,
        include_examples=include_examples,
        include_callees=include_callees,
        include_called_by=include_called_by,
        include_pseudocode=include_pseudocode,
    )
    return {
        "found": res.found,
        "mode": res.mode,
        "short_name": res.short_name,
        "matches": res.matches,
    }


@mcp.tool()
def search(short_name: str) -> dict:
    """Read the raw `index/<short_name>.txt` entries (no YAML bodies).

    Useful as a cheap existence check or to enumerate overloads /
    homonyms before calling `retrieve`.
    """
    return {"short_name": short_name, "entries": st.search(_store(), short_name)}


@mcp.tool()
def list_namespace(namespace: str = "") -> dict:
    """List every documented symbol under `namespace`.

    Pass ``""`` for the global / root namespace listing. Returns one
    entry per index line (so each function variant appears once).
    """
    return {"namespace": namespace,
            "entries": st.list_namespace(_store(), namespace)}


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


@mcp.tool()
def stats() -> dict:
    """Report the storage root in use and how many entries are indexed."""
    s = _store()
    by_kind = {"class": 0, "function": 0, "variable": 0}
    for _short, e in s.iter_index_entries():
        by_kind[e.kind] = by_kind.get(e.kind, 0) + 1
    return {
        "root": str(s.root),
        "docs_root": str(s.docs_root),
        "index_root": str(s.index_root),
        "by_kind": by_kind,
        "total": sum(by_kind.values()),
    }


def _result_dict(res: st.OperationResult) -> dict:
    d = {
        "ok": res.ok,
        "action": res.action,
        "path": res.path,
    }
    if res.message:
        d["message"] = res.message
    if res.extra:
        d["extra"] = res.extra
    return d


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
