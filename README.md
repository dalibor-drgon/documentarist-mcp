# Documentator MCP

An MCP server that lets an LLM **write** and **read** per-symbol code
documentation. Every documented class, function, or variable lives in
its own YAML file under `docs/`, and a flat `index/` directory makes
short-name lookup cheap.

The server is intentionally domain-agnostic: it doesn't care whether
your codebase is C, C++, Rust, Python, or something else. It only deals
in *fully-qualified names* (`ns::ns::Class<T>::method`) and YAML.

## Storage layout

```
<root>/
├── docs/
│   ├── mynamespace/
│   │   └── math_n/
│   │       ├── vector/                  ← class folder
│   │       │   ├── __index__.yaml       ← class doc
│   │       │   ├── sum.yaml             ← method (one or more variants)
│   │       │   └── data.yaml            ← field
│   │       └── PI.yaml                  ← namespace-level constant
│   └── sum.vector.c.yaml                ← static (file-private) function
└── index/
    ├── sum.txt                          ← every symbol named `sum`
    ├── vector.txt
    └── PI.txt
```

Function YAML files are *multi-document* streams — one `---` block per
overload. Class and variable files are single documents.

### Index file format

Each line of `index/<short>.txt`:

```
class       mynamespace::math_n::vector<int X>                       at "docs/mynamespace/math_n/vector/__index__.yaml"
function    mynamespace::math_n::vector<int X>::sum(Vector<X>, Vector<X>)  at "docs/mynamespace/math_n/vector/sum.yaml"
variable    mynamespace::math_n::PI                                   at "docs/mynamespace/math_n/PI.yaml"
static function sum(int, int)                                         at "docs/sum.vector.c.yaml"
```

The index is regenerated on every register/remove call — there is no
separate rebuild step.

## YAML schemas

### Class — `docs/.../<Class>/__index__.yaml`

```yaml
type: class
fullname: mynamespace::math_n::vector<int X>
extends: mynamespace::math_n::matrix
extended-by:
  - mynamespace::math_n::sparse_vector<int X>
short-description: Data structure holding a vector allocated as pointer + dimensions.
dangers: not thread-safe; protect with the irq lock when accessed from ISRs
full-description: |
  Implementation details, ownership, lifecycle, threading contract,
  expected caller behaviour. Multi-line OK.
pseudocode: |
  optional
examples:
  - title: init
    code: |
      vector<int> v = vector_make<int>(8);
```

### Function — one document per variant

```yaml
---
type: function
fullname: mynamespace::math_n::vector<int X>::sum
parameters:
  - {type: "Vector<X>", name: first}
  - {type: "Vector<X>", name: second}
returns: Vector<X>
overrides:
  - matrix::sum(vector, vector)
short-description: Element-wise sum of two vectors.
dangers: caller MUST hold irq_lock; not safe to call from ISR.
full-description: |
  ...
examples:
  - title: from task with lock
    code: |
      irq_lock(); auto z = sum(a, b); irq_unlock();
callees:                       # AUTO — managed by add_callee / remove_callee
  - "ring_advance()"
called-by:                     # AUTO
  - "task_drain()"
---
type: function
fullname: mynamespace::math_n::vector<int X>::sum
parameters:
  - {type: "Vector<X>", name: first}
  - {type: scalar,        name: scalar}
returns: Vector<X>
short-description: Add a scalar to every element.
dangers: pure / stack-only — no threading hazard
full-description: |
  ...
```

`callees` / `called-by` are *not* set via `register_function`. They
are managed by the dedicated `add_callee` / `remove_callee` tools and
preserved across re-registration. Each ref is a string of the form
`"ns::cls::fn(t1, t2)"`, with `"static fn(t1) @file"` for
file-private functions.

### Variable

```yaml
type: variable
fullname: mynamespace::math_n::PI
var-type: const double
short-description: Mathematical constant π.
dangers: read-only / any-context — no hazard.
full-description: |
  ...
examples:
  - "static_assert(PI > 3.14, \"oops\");"
```

## Running the server

```bash
pip install -e .
DOCUMENTATOR_ROOT=/path/to/your/codebase-docs documentator-mcp
```

In an MCP client (Claude Desktop, Claude Code, etc.) add it to your
config:

```json
{
  "mcpServers": {
    "documentator": {
      "command": "python",
      "args": ["-m", "docs_mcp"],
      "env": { "DOCUMENTATOR_ROOT": "/abs/path/to/codebase-docs" }
    }
  }
}
```

## MCP tools

| Tool                | Purpose                                                                    |
|---------------------|----------------------------------------------------------------------------|
| `register_class`    | Create or update a class doc; auto-syncs `extended-by`. Accepts `examples`. |
| `register_function` | Insert/update one variant (overload-aware). Accepts `examples`. Preserves call-graph fields. |
| `register_variable` | Create or update a variable / field / constant. Accepts `examples`.         |
| `remove_class`      | Delete a class (refuses if folder still has children).                      |
| `remove_function`   | Delete one variant or every variant.                                        |
| `remove_variable`   | Delete a variable.                                                          |
| `add_callee`        | Record `caller -> callee`. Updates BOTH sides of the edge.                  |
| `remove_callee`     | Drop the edge (both sides).                                                 |
| `retrieve`          | Fullname → exact doc, or short name → all matches. **Heavy fields stripped by default**; toggle `include_full_description` / `include_examples` / `include_callees` / `include_called_by` / `include_pseudocode`. |
| `search`            | Read the raw `index/<short>.txt` lines.                                     |
| `list_namespace`    | All entries under `ns::ns::...`.                                            |
| `stats`             | Storage root + counts.                                                      |

### Lightweight retrieve, by design

`retrieve` strips heavy fields by default and reports their presence
under an `_omitted` map:

```jsonc
"_omitted": {
  "full-description": {"chars": 412},
  "examples":         {"items": 2},
  "callees":          {"items": 1},
  "called-by":        {"items": 5}
}
```

Pull each one in only when needed via the matching `include_*`
flag — this lets agents walk a deep call graph without blowing the
context window.

### Why `add_callee`

`callees` / `called-by` is the data backbone of *thread-safety
auditing* on this codebase. By walking `called-by` upward you can
prove which contexts (ISR, task, …) can ever reach a given
function — the most common bug class on this MCU codebase is a
function called from both an ISR and a task without the right lock.

`add_callee("a::caller", "b::callee")` writes both sides at once. If
`b::callee` is not yet documented, the back-edge is recorded as a
forward-only fact and gets reconciled when `b::callee` is later
registered.

See [`prompts/thread_safety_agent.md`](prompts/thread_safety_agent.md)
for a ready-to-paste system prompt that walks the graph and surfaces
findings.

See [`AGENTS.md`](AGENTS.md) for the agent playbook and
[`prompts/`](prompts/) for ready-to-paste system prompts.

## Naming rules

* Use `::` between qualifier parts. Templates may appear on any part.
* Static / file-private symbols pass `file: "vector.c"` and end up at
  `docs/.../<leaf>.<file>.yaml` (or `<Class>.<file>/__index__.yaml`).
* Function overloads are matched by parameter *types* — names and
  defaults are stored but not part of the variant key.
