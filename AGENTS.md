# AGENTS.md — How to drive Documentator MCP

This file tells an LLM *how* to use the Documentator MCP correctly. It
is meant to be read by an agent before it starts producing or
consuming documentation. The companion files in [`prompts/`](prompts/)
are ready-to-paste system prompts for individual roles.

## Roles

There are four agent roles. Run them as one agent that switches
modes, or as separate sub-agents.

| Role                       | Reads                                         | Writes                                              |
|----------------------------|-----------------------------------------------|-----------------------------------------------------|
| **Documenter**             | source code                                   | `register_*` + `add_callee`                         |
| **Reader**                 | docs (lightweight by default)                 | nothing                                             |
| **Maintainer**             | source code + existing docs                   | `register_*`, `remove_*`, `add_callee`, `remove_callee` |
| **Thread-Safety Auditor**  | docs (with `include_callees` / `include_called_by`) | nothing — read-only                          |

Pick the system prompt for your role from `prompts/`. They are
self-contained — no other context needed.

## Core invariants

1. **Fullnames are the primary key.** `mynamespace::math_n::vector<X>::sum`
   is a different symbol from `vector<X>::sum`. Always include every
   enclosing namespace and class.
2. **Templates stay on the part they belong to.** Write
   `vector<int X>::sum`, not `vector::sum<int X>`.
3. **Function overloads share a YAML file.** Different parameter *types*
   = different variants. Different parameter *names* alone = same
   variant; calling `register_function` again will overwrite.
4. **Static / file-private items pass `file:`.** Without it they collide
   with namespace-level items in different translation units.
5. **`extends` is what *you* set; `extended-by` is auto-managed.**
   Never set `extended-by` yourself — the server populates it from
   reverse-lookups whenever a child registers.
6. **`callees` / `called-by` are auto-managed via `add_callee` /
   `remove_callee`.** Never include them in `register_function`
   payloads. They are preserved across re-registration.
7. **Thread-safety lives in `dangers`.** On this MCU codebase, every
   function and shared variable MUST have a non-empty `dangers`
   field naming the calling context (ISR-only / task-only / any) and
   the lock the caller must hold (`irq_lock`, etc.). Empty `dangers`
   means "I forgot to think about it." See the dedicated section
   below.
8. **Read before writing.** Call `retrieve` first if you suspect the
   symbol may already be documented; `register_*` is upsert, so
   accidentally clobbering an older, better description is easy.
9. **`retrieve` is lightweight by default.** Heavy fields
   (`full-description`, `examples`, `callees`, `called-by`,
   `pseudocode`) are stripped unless the matching `include_*` flag is
   set. Default responses leave a `_omitted` hint so you can decide.

## Thread-safety documentation (mandatory)

This codebase runs on a microcontroller. The most prominent bug
class is "shared state touched from two contexts without the right
lock." Documentation is the lever that prevents these.

For *every* function and every mutable variable / class field, the
`dangers` field MUST answer:

1. **Which contexts may call / read / write this?** Use the
   project's vocabulary: `ISR-only`, `task-only`, `any-context`,
   or a specific task name. Fall back to `IRQ-safe` for routines
   designed to be called from both.
2. **Which lock must the caller hold?** Name it by symbol:
   `irq_lock`, `scheduler_lock`, `device->lock`, etc.
3. **What happens on misuse?** Be specific — "data race on
   `ring.head` produces silently corrupted reads", not
   "undefined".

Examples of acceptable `dangers` strings:

> "ISR-only. Reads `pending_events` without a lock — that field is
> only written from this same handler."

> "task-only. Acquires `irq_lock` internally; do NOT call from ISR
> (would deadlock the device)."

> "pure / stack-only — no threading hazard."

The empty string is rarely correct. If you genuinely have no
threading concerns, *say so explicitly* with the third pattern
above.

## The standard documenter workflow

For each symbol you want to document:

1. **Identify the symbol's fullname.** Walk back through `namespace`,
   `class`, `struct`, `module` declarations until you reach the file
   level. Concatenate with `::`.
2. **Decide its kind.** Class / struct / interface → `register_class`.
   Function / method / lambda binding → `register_function`. Variable
   / field / constant / enum value → `register_variable`.
3. **Read the surrounding code thoroughly** before writing
   `full_description`. Capture:
   * What the symbol does (one line) → `short_description`.
   * Pre-conditions and invariants (locking, ordering, allocation
     ownership) → in `full_description` and `dangers`.
   * Side effects (global state, IO, IRQ-context behaviour).
   * Error modes (return values, exceptions, panics).
   * **Threading contract** (mandatory — see section above).
   * Lifetime / ownership of pointer parameters and return values.
4. **Always populate `dangers` with the thread-safety contract.**
   See the section above. Empty `dangers` is almost always a
   mistake.
5. **Provide at least one `examples` entry** when the contract is
   non-trivial. Examples encode the contract in code form — the
   cheapest way to prevent misuse. Provide multiple examples when
   the function is reachable from more than one context (one per
   context — ISR vs task).
6. **Use `pseudocode` only when the algorithm is non-obvious.** A
   verbatim copy of the source is noise.
7. **For a function**, fill in `parameters` as a list. The
   recommended shape is `{"type": "...", "name": "..."}` per
   parameter. Omit the name if it isn't part of the public contract.
   Use `default` for default arguments.
8. **For a class with a parent**, set `extends`. Do not also try to
   list yourself in the parent's `extended-by` — that happens
   automatically.
9. **For overrides of virtual / trait methods**, populate
   `overrides: ["base::method(types)"]`.
10. **After registering a function, record its outgoing call edges**
    via `add_callee(this_fn, callee_fn, ...)` for every documented
    function it calls. This is what makes downstream thread-safety
    audits possible.

## The standard reader workflow

You're answering "what does X do?" or "is there already something that
does Y?". Use this order — it's cheapest first:

1. `search(short_name)` — one cheap read; tells you if anything by
   that name exists and how many homonyms there are.
2. `retrieve(fullname, parameters?)` — for a precise match. Pass
   `parameters` to disambiguate overloads. The default response is
   *lightweight* — see invariant 9 above. Pull heavy fields only
   when the user needs them, via `include_*` flags:
   * `include_full_description=true`
   * `include_examples=true`
   * `include_callees=true` / `include_called_by=true`
   * `include_pseudocode=true`
3. `retrieve(short_name)` — fall-back when you don't know the
   namespace; returns every YAML body for that short name (still
   lightweight unless flags are set).
4. `list_namespace("ns::sub")` — to enumerate everything under a
   namespace, e.g. when starting on a new module.

## Thread-safety auditing workflow

To answer "could this race?" or "what contexts can reach `X`?", use
the **Thread-Safety Auditor** prompt
([`prompts/thread_safety_agent.md`](prompts/thread_safety_agent.md)).
It walks `called-by` upward and `callees` downward, building the
reachable-context set, and flags mismatches between an anchor's
claimed context and what its callers actually run in.

The auditor is read-only. If it finds gaps in the docs (silent
`dangers`, missing edges), it stops and reports them — at which
point a Documenter or Maintainer fills the gap.

## Update vs. remove

* **Update** is just `register_*` again with the same fullname (and
  same parameter types for functions). The whole document is replaced.
* **Remove** uses `remove_class` / `remove_function` /
  `remove_variable`. `remove_class` refuses if the class folder still
  has documented members; clean those up first.

## Common mistakes

* **Forgetting the `file` argument** on `static` / file-local symbols.
  Two `static int counter;` in different `.c` files will overwrite each
  other if you don't pass `file:`.
* **Putting parameters into `fullname`.** It's tolerated (the parser
  peels them off), but cleaner to leave `fullname` as
  `ns::cls::name` and pass a structured `parameters` array.
* **Hand-editing `extended-by`, `callees`, or `called-by`.** All three
  are server-managed. `extended-by` rebuilds at every child
  registration; `callees`/`called-by` are exclusively managed via
  `add_callee`/`remove_callee`.
* **Re-registering with a different parameter *name* but same type
  list.** That's the same variant — your new docs replace the old.
  (Auto-managed fields like `callees`/`called-by` are still
  preserved.)
* **Using `retrieve` to discover what's there.** Use
  `list_namespace` or `search` first; `retrieve` is for getting docs
  for symbols you can already name.
* **Eagerly enabling all `include_*` flags on retrieve.** It blows
  the context window, especially on functions with deep
  `called-by` lists. Start lean.
* **Empty `dangers`.** On this MCU codebase, almost always wrong.
  Even pure helpers should say "pure / stack-only — no threading
  hazard" so the reader knows you considered it.

## Style guide for descriptions

* `short_description`: ≤ 1 sentence, indicative mood, no period needed.
* `full_description`: prose, multiple paragraphs OK. Mention every
  invariant the caller MUST uphold.
* `dangers`: comma-separated list or short paragraph. Treat this like
  a runtime warning — "if you forget X, Y happens".
* Don't describe the *implementation* of trivial code — describe the
  *contract*. The implementation is one click away in the source.
