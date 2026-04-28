# Documentator schema reference

Drop this into the agent's context whenever it needs to remember the
exact shape of a registration call. It is the single source of truth
for required vs. optional fields.

## `register_class`

```jsonc
{
  "fullname":          "ns::sub::ClassName<TArgs>",   // REQUIRED
  "short_description": "one-sentence summary",         // REQUIRED
  "full_description":  "multi-line prose",             // REQUIRED
  "dangers":           "footguns / locking / etc.",    // optional, default ""
  "extends":           "ns::sub::ParentClass",         // optional, null to clear
  "pseudocode":        "...",                          // optional
  "file":              "vector.c"                      // optional, set for file-private classes
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
file: ...
```

## `register_function`

```jsonc
{
  "fullname":          "ns::sub::Cls<T>::method",     // REQUIRED, no trailing (...)
  "short_description": "...",                          // REQUIRED
  "full_description":  "...",                          // REQUIRED
  "parameters": [                                      // REQUIRED for clarity (use [] if no args)
    {"type": "Vector<X>", "name": "first"},
    {"type": "Vector<X>", "name": "second", "default": "{}"}
  ],
  "returns":     "Vector<X>",                          // optional
  "dangers":     "...",                                // optional
  "overrides":   ["matrix::sum(vector, vector)"],      // optional, fullnames+sigs
  "pseudocode":  "...",                                // optional
  "file":        "vector.c"                            // optional, file-private
}
```

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
  "var_type":          "const uint32_t",               // optional but encouraged
  "dangers":           "...",                          // optional
  "pseudocode":        "...",                          // optional
  "file":              "vector.c"                      // optional, file-private
}
```

## `retrieve`

```jsonc
{
  "name":       "ns::sub::sum"                         // REQUIRED, full or short
  "parameters": [{"type": "int"}, {"type": "int"}],    // optional, narrows function variants
  "file":       "vector.c"                             // optional, hint for file-private
}
```

Result:

```jsonc
{
  "found":      true,
  "mode":       "exact" | "short" | "miss",
  "short_name": "sum",
  "matches": [
    {
      "entry": {"kind": "function", "fullname": "...", "path": "...", "signature": "(int, int)", "static": true},
      "doc":   { ...the YAML body... }
    }
  ]
}
```

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
