# Documentator schema reference

Drop this into the agent's context whenever it needs to remember the
exact shape of a registration or query call. Single source of truth
for required vs. optional fields.

## `register_class`

```jsonc
{
  "fullname":          "ns::sub::ClassName<TArgs>",   // REQUIRED
  "short_description": "one-sentence summary",         // REQUIRED
  "full_description":  "multi-line prose",             // REQUIRED
  "dangers":           "thread-safety / locking / etc.", // STRONGLY ENCOURAGED
  "extends":           "ns::sub::ParentClass",         // optional, null to clear
  "pseudocode":        "...",                          // optional
  "file":              "vector.c",                     // optional, file-private
  "examples": [                                        // optional, list
    "ring_buffer_t rb; ring_buffer_init(&rb);",
    {"title": "irq path", "description": "...", "code": "..."}
  ]
}
```

The server writes:

```yaml
type: class
fullname: <fullname>
extends: <extends if any>
extended-by: [...]            # AUTO-MAINTAINED — do not set
short-description: ...
dangers: ...
full-description: ...
pseudocode: ...
examples:
  - {title: ..., description: ..., code: ...}
file: ...
```

## `register_function`

```jsonc
{
  "fullname":          "ns::sub::Cls<T>::method",     // REQUIRED, no trailing (...)
  "short_description": "...",                          // REQUIRED
  "full_description":  "...",                          // REQUIRED
  "dangers":           "ISR-only / task-only / lock to hold / ...",  // STRONGLY ENCOURAGED
  "parameters": [                                      // REQUIRED for clarity (use [] if no args)
    {"type": "Vector<X>", "name": "first"},
    {"type": "Vector<X>", "name": "second", "default": "{}"}
  ],
  "returns":     "Vector<X>",                          // optional
  "overrides":   ["matrix::sum(vector, vector)"],      // optional, fullnames+sigs
  "pseudocode":  "...",                                // optional
  "file":        "vector.c",                           // optional, file-private
  "examples": [                                        // optional, list
    "rb_push(&rb, b);",
    {"title": "from ISR", "code": "rb_push(&rb, b);"},
    {"title": "from task — needs lock",
     "code": "irq_lock(); rb_push(&rb, b); irq_unlock();"}
  ]
}
```

`callees` and `called-by` are NOT accepted as input. They are managed
exclusively by `add_callee` / `remove_callee` and are preserved
across re-registration.

The server writes one YAML document per registration:

```yaml
type: function
fullname: <fullname>
parameters:
  - {type: ..., name: ..., default: ...}
returns: ...
overrides: [...]
short-description: ...
dangers: ...
full-description: ...
pseudocode: ...
examples:
  - {title: ..., description: ..., code: ...}
callees: ["other::fn(int)"]                 # AUTO-MAINTAINED
called-by: ["other::fn2(int)"]              # AUTO-MAINTAINED
file: ...
```

Multiple variants of the *same* `fullname` accumulate as separate
documents in the same file (`---` separated).

## `register_variable`

```jsonc
{
  "fullname":          "ns::sub::CONST_OR_FIELD",     // REQUIRED
  "short_description": "...",                          // REQUIRED
  "full_description":  "...",                          // REQUIRED
  "dangers":           "read-from-ISR / write-from-task / lock / ...",  // STRONGLY ENCOURAGED
  "var_type":          "const uint32_t",               // optional but encouraged
  "pseudocode":        "...",                          // optional
  "file":              "vector.c",                     // optional, file-private
  "examples": [                                        // optional, list
    "static_assert(PI > 3.14);"
  ]
}
```

## `add_callee` / `remove_callee`

```jsonc
{
  "caller":             "ns::cls::caller_fn",          // REQUIRED
  "callee":             "ns::cls::callee_fn",          // REQUIRED
  "caller_parameters":  [{"type":"int"}],              // optional, disambiguates overloads
  "callee_parameters":  [{"type":"uint8_t"}],          // optional, disambiguates overloads
  "caller_file":        "vector.c",                    // optional, static caller
  "callee_file":        "ringbuf.c"                    // optional, static callee
}
```

`add_callee` updates BOTH sides:
* `caller`'s ``callees`` gets the callee ref appended.
* `callee`'s ``called-by`` gets the caller ref appended.

If the callee isn't documented yet, only the caller side is written.
The back-edge is filled in automatically when the callee is later
registered (the server scans incoming refs at register time).

`remove_callee` is symmetric: drops the edge from both sides.

Refs in the YAML look like ``"ns::cls::fn(int, uint8_t)"`` for normal
functions and ``"static fn(int) @vector.c"`` for static / file-private
functions. You don't construct these strings yourself — they appear
in `callees` / `called-by` lists when you read a doc.

## `retrieve`

```jsonc
{
  "name":       "ns::sub::sum",                        // REQUIRED, full or short
  "parameters": [{"type": "int"}, {"type": "int"}],    // optional, narrows function variants
  "file":       "vector.c",                            // optional, hint for file-private

  // Heavy fields — OFF by default. Toggle one or more on demand:
  "include_full_description": false,
  "include_examples":         false,
  "include_callees":          false,
  "include_called_by":        false,
  "include_pseudocode":       false
}
```

Default response shape:

```jsonc
{
  "found":      true,
  "mode":       "exact" | "short" | "miss",
  "short_name": "sum",
  "matches": [
    {
      "entry": {
        "kind": "function", "fullname": "...",
        "path": "...", "signature": "(int, int)", "static": true
      },
      "doc": {
        "type": "function",
        "fullname": "...",
        "parameters": [...],
        "returns": "...",
        "short-description": "...",
        "dangers": "...",
        // overrides, extends, extended-by, var-type, file when applicable.
        "_omitted": {
          "full-description": {"chars": 412},
          "examples":         {"items": 2},
          "callees":          {"items": 3},
          "called-by":        {"items": 5}
          // only the heavy fields actually present in the YAML appear here.
        }
      }
    }
  ]
}
```

`_omitted` advertises that those fields exist on disk — re-call
`retrieve` with the matching `include_*` flag to load any of them.

## `search`

```jsonc
{ "short_name": "sum" }
```

Returns the parsed `index/sum.txt` lines (no YAML bodies).

## `list_namespace`

```jsonc
{ "namespace": "ns::sub" }
```

`""` = all entries.

## `remove_*`

* `remove_class(fullname, file?)` — refuses if class folder has
  children.
* `remove_function(fullname, parameters?, file?)` — without
  `parameters`, removes every variant.
* `remove_variable(fullname, file?)`.
