# Example session

A concrete walk-through of registering and retrieving the symbols from
the spec. Treat this as a sanity check — every tool call shown below
should succeed against a fresh `DOCUMENTATOR_ROOT`.

## 1. Register a class

```jsonc
register_class({
  "fullname": "mynamespace::math_n::matrix",
  "short_description": "2-D dense numeric container",
  "full_description": "Owns a contiguous buffer of `rows*cols` elements...",
  "dangers": "not thread-safe; copy is shallow"
})
// → { ok: true, action: "created", path: "docs/mynamespace/math_n/matrix/__index__.yaml" }
```

## 2. Register a derived class

```jsonc
register_class({
  "fullname": "mynamespace::math_n::vector<int X>",
  "extends":  "mynamespace::math_n::matrix",
  "short_description": "Data structure holding a vector allocated as pointer + dimensions",
  "full_description": "Single-row specialisation of matrix...",
  "dangers": "is not thread-safe, needs to be protected by irq lock"
})
// matrix.__index__.yaml is auto-updated:  extended-by: [mynamespace::math_n::vector<int X>]
```

## 3. Register a method with two overloads

```jsonc
register_function({
  "fullname": "mynamespace::math_n::vector<int X>::sum",
  "parameters": [
    {"type": "Vector<X>", "name": "first"},
    {"type": "Vector<X>", "name": "second"}
  ],
  "returns": "Vector<X>",
  "overrides": ["matrix::sum(vector, vector)"],
  "short_description": "Element-wise sum of two vectors",
  "full_description": "..."
})

register_function({
  "fullname": "mynamespace::math_n::vector<int X>::sum",
  "parameters": [
    {"type": "Vector<X>", "name": "first"},
    {"type": "scalar",    "name": "scalar"}
  ],
  "returns": "Vector<X>",
  "short_description": "Add a scalar to each element",
  "full_description": "..."
})
// docs/mynamespace/math_n/vector/sum.yaml now contains TWO YAML documents.
// index/sum.txt now contains TWO function lines for the same fullname.
```

## 4. Register a static / file-private function

```jsonc
register_function({
  "fullname":   "sum",
  "parameters": [{"type": "int", "name": "a"}, {"type": "int", "name": "b"}],
  "returns":    "int",
  "short_description": "Internal sum used by vector.c only",
  "full_description":  "Hot inner loop helper; not exported.",
  "file":       "vector.c"
})
// → docs/sum.vector.c.yaml
// index/sum.txt now also contains:  static function sum(int, int) at "docs/sum.vector.c.yaml"
```

## 5. Retrieve

```jsonc
// Exact, by fullname:
retrieve({"name": "mynamespace::math_n::vector<int X>::sum",
          "parameters": [{"type":"Vector<X>"},{"type":"Vector<X>"}]})
// → { found: true, mode: "exact", matches: [{entry, doc}] }

// Short-name fallback — returns BOTH the static and all overloads:
retrieve({"name": "sum"})
// → { found: true, mode: "short", matches: [ ... 3 docs ... ] }
```

## 6. Remove a single overload

```jsonc
remove_function({
  "fullname":   "mynamespace::math_n::vector<int X>::sum",
  "parameters": [{"type":"Vector<X>"},{"type":"scalar"}]
})
// scalar overload gone, element-wise overload remains, sum.yaml still exists.
```

## 7. Remove the class

```jsonc
remove_class({"fullname": "mynamespace::math_n::vector<int X>"})
// → ok=false, message="class folder not empty — remove 1 child entries first"
// (sum.yaml is the leftover child)

remove_function({"fullname": "mynamespace::math_n::vector<int X>::sum"})
// removes the file outright (no parameters → all variants)

remove_class({"fullname": "mynamespace::math_n::vector<int X>"})
// → ok=true. matrix.__index__.yaml's extended-by drops the vector entry.
```
