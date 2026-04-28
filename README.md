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
full-description: |
  ...
---
type: function
fullname: mynamespace::math_n::vector<int X>::sum
parameters:
  - {type: "Vector<X>", name: first}
  - {type: scalar,        name: scalar}
returns: Vector<X>
short-description: Add a scalar to every element.
full-description: |
  ...
```

### Variable

```yaml
type: variable
fullname: mynamespace::math_n::PI
var-type: const double
short-description: Mathematical constant π.
full-description: |
  ...
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

| Tool                | Purpose                                                    |
|---------------------|------------------------------------------------------------|
| `register_class`    | Create or update a class doc; auto-syncs `extended-by`     |
| `register_function` | Insert/update one variant (overload-aware)                 |
| `register_variable` | Create or update a variable / field / constant             |
| `remove_class`      | Delete a class (refuses if folder still has children)      |
| `remove_function`   | Delete one variant or every variant                        |
| `remove_variable`   | Delete a variable                                          |
| `retrieve`          | Fullname → exact doc, or short name → all matches          |
| `search`            | Read the raw `index/<short>.txt` lines                     |
| `list_namespace`    | All entries under `ns::ns::...`                            |
| `stats`             | Storage root + counts                                       |

See [`AGENTS.md`](AGENTS.md) for the agent playbook and
[`prompts/`](prompts/) for ready-to-paste system prompts.

## Naming rules

* Use `::` between qualifier parts. Templates may appear on any part.
* Static / file-private symbols pass `file: "vector.c"` and end up at
  `docs/.../<leaf>.<file>.yaml` (or `<Class>.<file>/__index__.yaml`).
* Function overloads are matched by parameter *types* — names and
  defaults are stored but not part of the variant key.
