"""Smoke test — exercises the storage layer without the MCP runtime.

Run from the repo root:

    python -m tests.test_smoke
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

# Allow `python tests/test_smoke.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docs_mcp import storage as st
from docs_mcp.parser import parse_fullname


def banner(s):
    print("\n=== " + s + " ===")


def listdir(p: Path):
    return sorted([str(x.relative_to(p)).replace("\\", "/") for x in p.rglob("*") if x.is_file()])


def main():
    root = Path(tempfile.mkdtemp(prefix="docmcp_smoke_"))
    print("root:", root)
    s = st.Storage(root)

    # -- parser sanity --
    banner("parser")
    p = parse_fullname("mynamespace::math_n::vector<int X>::sum(Vector<X> a, Vector<X> b)")
    print("parts:", p.parts, "params:", [(x.type, x.name) for x in p.params])
    assert p.leaf_name == "sum"
    assert p.parts[1] == ("math_n", "")
    assert p.parts[2] == ("vector", "<int X>")
    assert len(p.params) == 2

    # -- register parent class --
    banner("register matrix")
    r = st.register_class(
        s, "mynamespace::math_n::matrix",
        short_description="2-D matrix",
        full_description="owns rows*cols buffer",
        dangers="not thread-safe",
    )
    print(r)
    assert r.ok and r.action == "created"

    # -- register child class --
    banner("register vector<int X> extends matrix")
    r = st.register_class(
        s, "mynamespace::math_n::vector<int X>",
        short_description="vector",
        full_description="row-vector specialisation",
        dangers="needs irq lock",
        extends="mynamespace::math_n::matrix",
    )
    print(r)

    # extended-by must be auto-populated on matrix
    matrix_doc = s.read_class_yaml(
        s.docs_root / "mynamespace" / "math_n" / "matrix" / "__index__.yaml"
    )
    print("matrix.extended-by:", matrix_doc.get("extended-by"))
    assert matrix_doc["extended-by"] == ["mynamespace::math_n::vector<int X>"]

    # -- register two function variants --
    banner("register vector::sum overloads")
    r = st.register_function(
        s, "mynamespace::math_n::vector<int X>::sum",
        short_description="elem-wise sum",
        full_description="...",
        parameters=[{"type": "Vector<X>", "name": "first"},
                    {"type": "Vector<X>", "name": "second"}],
        returns="Vector<X>",
        overrides=["matrix::sum(vector, vector)"],
    )
    print(r)
    r = st.register_function(
        s, "mynamespace::math_n::vector<int X>::sum",
        short_description="scalar add",
        full_description="...",
        parameters=[{"type": "Vector<X>", "name": "first"},
                    {"type": "scalar", "name": "scalar"}],
        returns="Vector<X>",
    )
    print(r)

    sum_path = s.docs_root / "mynamespace" / "math_n" / "vector" / "sum.yaml"
    docs = s.read_variants(sum_path)
    assert len(docs) == 2
    print("variants:", [d["parameters"] for d in docs])

    # -- register a static / file-private fn with same short name --
    banner("register static sum in vector.c")
    r = st.register_function(
        s, "sum",
        short_description="static helper",
        full_description="...",
        parameters=[{"type": "int", "name": "a"},
                    {"type": "int", "name": "b"}],
        returns="int",
        file="vector.c",
    )
    print(r)
    assert (s.docs_root / "sum.vector.c.yaml").exists()

    # -- register a variable --
    banner("register PI")
    st.register_variable(
        s, "mynamespace::math_n::PI",
        short_description="pi",
        full_description="constant",
        var_type="const double",
    )

    # -- inspect index files --
    banner("index files")
    for txt in sorted(s.index_root.glob("*.txt")):
        print("\n--", txt.name, "--")
        print(txt.read_text(encoding="utf-8"))

    # -- retrieve exact (with overload disambiguation) --
    banner("retrieve exact w/ params")
    res = st.retrieve(
        s, "mynamespace::math_n::vector<int X>::sum",
        parameters=[{"type": "Vector<X>"}, {"type": "Vector<X>"}],
    )
    print("found:", res.found, "mode:", res.mode, "n:", len(res.matches))
    assert res.found and res.mode == "exact" and len(res.matches) == 1

    # -- retrieve by short name → returns ALL homonyms --
    banner("retrieve short 'sum'")
    res = st.retrieve(s, "sum")
    print("mode:", res.mode, "n:", len(res.matches))
    for m in res.matches:
        print(" -", m["entry"])
    assert res.mode == "short" and len(res.matches) >= 3

    # -- search --
    banner("search 'sum'")
    print(st.search(s, "sum"))

    # -- list_namespace --
    banner("list_namespace 'mynamespace::math_n'")
    for e in st.list_namespace(s, "mynamespace::math_n"):
        print(" -", e)

    # -- update vector's parent (extends -> nothing) and verify cleanup --
    banner("update vector to remove extends")
    st.register_class(
        s, "mynamespace::math_n::vector<int X>",
        short_description="vector",
        full_description="row-vector specialisation",
        dangers="needs irq lock",
        extends=None,
    )
    matrix_doc = s.read_class_yaml(
        s.docs_root / "mynamespace" / "math_n" / "matrix" / "__index__.yaml"
    )
    print("matrix.extended-by after:", matrix_doc.get("extended-by"))
    assert matrix_doc.get("extended-by") == []

    # -- remove_function single variant --
    banner("remove scalar overload")
    r = st.remove_function(
        s, "mynamespace::math_n::vector<int X>::sum",
        parameters=[{"type": "Vector<X>"}, {"type": "scalar"}],
    )
    print(r)
    docs = s.read_variants(sum_path)
    assert len(docs) == 1

    # -- remove_class refuses if children remain --
    banner("remove vector class while sum.yaml still exists")
    r = st.remove_class(s, "mynamespace::math_n::vector<int X>")
    print(r)
    assert not r.ok

    # -- remove all variants of sum, then class --
    banner("remove sum entirely, then vector class")
    print(st.remove_function(s, "mynamespace::math_n::vector<int X>::sum"))
    print(st.remove_class(s, "mynamespace::math_n::vector<int X>"))

    banner("docs tree after cleanup")
    for f in listdir(s.docs_root):
        print(" -", f)
    banner("index after cleanup")
    for f in sorted(s.index_root.glob("*.txt")):
        print("\n--", f.name, "--")
        print(f.read_text(encoding="utf-8"))

    # ============================================================
    # Phase 2 smoke: examples + callees/called-by + retrieve flags
    # ============================================================
    banner("phase2: fresh root")
    root2 = Path(tempfile.mkdtemp(prefix="docmcp_smoke2_"))
    s = st.Storage(root2)

    # Set up: 3 functions on an MCU theme.
    #   isr_handler() -> shared_buf_push() -> ring_advance()
    #   task_drain()  -> shared_buf_push()
    st.register_function(
        s, "isr_handler",
        short_description="GPIO IRQ handler",
        full_description="runs in IRQ context",
        parameters=[], returns="void",
        dangers="ISR-only; never call from task context",
        examples=["void isr_handler(void) { shared_buf_push(byte); }"],
    )
    st.register_function(
        s, "task_drain",
        short_description="Background drain task",
        full_description="task context, holds irq_lock when touching shared_buf",
        parameters=[], returns="void",
        dangers="task-only; takes irq_lock before any shared_buf access",
    )
    st.register_function(
        s, "shared_buf_push",
        short_description="Push a byte into the shared ring buffer",
        full_description="caller MUST hold irq_lock OR be in IRQ context",
        parameters=[{"type": "uint8_t", "name": "byte"}], returns="bool",
        dangers="not thread-safe — caller holds irq_lock",
        examples=[{"title": "from ISR", "code": "shared_buf_push(b);"},
                  {"title": "from task", "code": "irq_lock(); shared_buf_push(b); irq_unlock();"}],
    )
    st.register_function(
        s, "ring_advance",
        short_description="Advance ring head index",
        full_description="non-atomic; caller holds irq_lock",
        parameters=[], returns="void",
        dangers="caller MUST hold irq_lock",
    )

    banner("add_callee edges")
    print(st.add_callee(s, "isr_handler", "shared_buf_push"))
    print(st.add_callee(s, "task_drain",  "shared_buf_push"))
    print(st.add_callee(s, "shared_buf_push", "ring_advance"))

    # Confirm bidirectional update.
    push_loc, _ = st._find_function_variant(s, "shared_buf_push")
    print("shared_buf_push.called-by:", push_loc.variant.get("called-by"))
    print("shared_buf_push.callees:  ", push_loc.variant.get("callees"))
    assert push_loc.variant.get("callees") == ["ring_advance()"]
    assert set(push_loc.variant.get("called-by")) == {"isr_handler()", "task_drain()"}

    ring_loc, _ = st._find_function_variant(s, "ring_advance")
    assert ring_loc.variant.get("called-by") == ["shared_buf_push(uint8_t)"]

    banner("retrieve default — heavy fields stripped")
    res = st.retrieve(s, "shared_buf_push")
    doc = res.matches[0]["doc"]
    print("keys:", sorted(doc.keys()))
    print("_omitted:", doc.get("_omitted"))
    assert "full-description" not in doc
    assert "examples"          not in doc
    assert "callees"           not in doc
    assert "called-by"         not in doc
    assert "short-description" in doc and "dangers" in doc
    assert "_omitted" in doc and "callees" in doc["_omitted"]

    banner("retrieve with include_callees + include_called_by")
    res = st.retrieve(s, "shared_buf_push", include_callees=True, include_called_by=True)
    doc = res.matches[0]["doc"]
    print("callees:  ", doc.get("callees"))
    print("called-by:", doc.get("called-by"))
    assert doc.get("callees") == ["ring_advance()"]
    assert "full-description" not in doc  # still stripped

    banner("retrieve with include_full_description + include_examples")
    res = st.retrieve(s, "shared_buf_push",
                      include_full_description=True, include_examples=True)
    doc = res.matches[0]["doc"]
    assert "full-description" in doc and "examples" in doc
    assert len(doc["examples"]) == 2

    banner("examples on a class")
    st.register_class(
        s, "ring_buffer",
        short_description="lock-free SPSC ring (single producer, single consumer)",
        full_description="producer side IRQ-only, consumer side task-only",
        dangers="producer must be IRQ-only; consumer task-only — violating crashes",
        examples=[{"title": "init", "code": "ring_buffer_t rb; ring_buffer_init(&rb);"}],
    )
    res = st.retrieve(s, "ring_buffer", include_examples=True)
    print("class examples:", res.matches[0]["doc"].get("examples"))
    assert res.matches[0]["doc"]["examples"]

    banner("re-register preserves callees/called-by")
    st.register_function(
        s, "shared_buf_push",
        short_description="Push a byte into the shared ring buffer (revised)",
        full_description="updated full description",
        parameters=[{"type": "uint8_t", "name": "byte"}], returns="bool",
        dangers="caller holds irq_lock",
    )
    push_loc, _ = st._find_function_variant(s, "shared_buf_push")
    print("after re-reg, callees:  ", push_loc.variant.get("callees"))
    print("after re-reg, called-by:", push_loc.variant.get("called-by"))
    assert push_loc.variant.get("callees") == ["ring_advance()"]
    assert set(push_loc.variant.get("called-by")) == {"isr_handler()", "task_drain()"}

    banner("remove_callee")
    print(st.remove_callee(s, "task_drain", "shared_buf_push"))
    push_loc, _ = st._find_function_variant(s, "shared_buf_push")
    assert "task_drain()" not in (push_loc.variant.get("called-by") or [])

    banner("forward edge to undocumented callee then register it")
    print(st.add_callee(s, "task_drain", "led_off"))
    drain_loc, _ = st._find_function_variant(s, "task_drain")
    assert "led_off()" in (drain_loc.variant.get("callees") or [])
    # now register led_off — should pick up task_drain as a caller
    st.register_function(
        s, "led_off",
        short_description="Turn the status LED off",
        full_description="GPIO write",
        parameters=[], returns="void",
        dangers="none",
    )
    led_loc, _ = st._find_function_variant(s, "led_off")
    print("led_off.called-by:", led_loc.variant.get("called-by"))
    assert "task_drain()" in (led_loc.variant.get("called-by") or [])

    print("\nPHASE2 OK")
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(root2, ignore_errors=True)


if __name__ == "__main__":
    main()
