# AGENTS.md — How to drive Documentator MCP

This file tells an LLM *how* to use the Documentator MCP correctly. It
is meant to be read by an agent before it starts producing or
consuming documentation. The companion files in [`prompts/`](prompts/)
are ready-to-paste system prompts for individual roles.

## Roles

There are three useful agent roles. You can run them as one agent that
switches modes, or as three separate sub-agents.

| Role               | Reads                              | Writes                       |
|--------------------|------------------------------------|------------------------------|
| **Documenter**     | source code                        | calls `register_*` MCP tools |
| **Reader**         | calls `retrieve` / `search` / `list_namespace` | nothing            |
| **Maintainer**     | source code + existing docs        | `register_*` and `remove_*`  |

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
6. **Read before writing.** Call `retrieve` first if you suspect the
   symbol may already be documented; `register_*` is upsert, so
   accidentally clobbering an older, better description is easy.

## The standard documenter workflow

For each symbol you want to document:

1. **Identify the symbol's fullname.** Walk back through `namespace`,
   `class`, `struct`, `module` declarations until you reach the file
   level. Concatenate with `::`.
2. **Decide its kind.** Class / struct / interface → `register_class`.
   Function / method / lambda binding → `register_function`. Variable
   / field / constant / enum value → `register_variable`.
3. **Read the surrounding code thoroughly** before writing
   `full_description`. Things to capture:
   * What the symbol does (one line) → `short_description`.
   * Pre-conditions and invariants (locking, ordering, allocation
     ownership) → either in `full_description` or a dedicated
     `dangers` field.
   * Side effects (global state, IO, IRQ-context behaviour).
   * Error modes (which return values mean what; which exceptions /
     panics can leak).
   * Threading contract (re-entrant? IRQ-safe? thread-safe?
     async-cancellation-safe?).
   * Lifetime / ownership of pointer parameters and return values.
4. **Mention `dangers` when at least one of these is true:** known
   data-race window, undefined behaviour on misuse, ABI fragility,
   non-obvious aliasing rule, irq-lock requirement, async-signal
   unsafety.
5. **Use `pseudocode` only when the algorithm is non-obvious.** A
   verbatim copy of the source is noise.
6. **For a function**, fill in `parameters` as a list. The recommended
   shape is `{"type": "...", "name": "..."}` per parameter.
   Omit the name if it isn't part of the public contract. Use
   `default` for default arguments.
7. **For a class with a parent**, set `extends`. Do not also try to
   list yourself in the parent's `extended-by` — that happens
   automatically.
8. **For overrides of virtual / trait methods**, populate
   `overrides: ["base::method(types)"]`.

## The standard reader workflow

You're answering "what does X do?" or "is there already something that
does Y?". Use this order — it's cheapest first:

1. `search(short_name)` — one cheap read; tells you if anything by
   that name exists and how many homonyms there are.
2. `retrieve(fullname, parameters?)` — for a precise match. Pass
   `parameters` to disambiguate overloads.
3. `retrieve(short_name)` — fall-back when you don't know the
   namespace; returns every YAML body for that short name.
4. `list_namespace("ns::sub")` — to enumerate everything under a
   namespace, e.g. when starting on a new module.

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
* **Hand-editing `extended-by`.** The server overwrites it on the next
  child registration anyway.
* **Re-registering with a different parameter *name* but same type
  list.** That's the same variant — your new docs replace the old.
* **Using `retrieve` to discover what's there.** Use
  `list_namespace` or `search` first; `retrieve` is for getting docs
  for symbols you can already name.

## Style guide for descriptions

* `short_description`: ≤ 1 sentence, indicative mood, no period needed.
* `full_description`: prose, multiple paragraphs OK. Mention every
  invariant the caller MUST uphold.
* `dangers`: comma-separated list or short paragraph. Treat this like
  a runtime warning — "if you forget X, Y happens".
* Don't describe the *implementation* of trivial code — describe the
  *contract*. The implementation is one click away in the source.
