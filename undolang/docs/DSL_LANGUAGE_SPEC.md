# UndoLang DSL Language Specification

**Language version:** 0.1 / schema version `undo-dsl/1`

**File extension:** `.undo`

**Runtime:** `undo`

---

## 1. Design goals

UndoLang is a deliberately small, non-general-purpose language for filesystem transactions.

The language must be:

- easy to read and write by humans;
- easy for AI agents to generate correctly;
- trivial to parse with a handwritten recursive-descent parser;
- explicit about destructive behavior;
- deterministic;
- non-Turing-complete in the hackathon release;
- impossible to use as an arbitrary shell escape;
- composed only of operations the runtime understands well enough to plan, journal, recover, and reverse.

## 2. Source encoding and lexical rules

- Source is UTF-8.
- Invalid UTF-8 is a lexical error.
- Keywords are lowercase and case-sensitive.
- Whitespace outside strings is insignificant.
- Newlines are not statement terminators; fixed statement grammar determines boundaries.
- `#` begins a line comment outside a string and continues to newline.
- Double-quoted strings support escapes.
- Backtick raw strings support literal path text without escape processing and are recommended for Windows paths.

### 2.1 Double-quoted string escapes

Required escapes:

- `\\` backslash
- `\"` quote
- `\n` newline
- `\r` carriage return
- `\t` tab
- `\uXXXX` Unicode BMP escape (optional if time constrained; if omitted, document and reject explicitly rather than partially implementing)

Unknown escapes are lexical errors.

### 2.2 Raw strings

Example:

```undo
copy `C:\ProgramData\MyApp\config.json` -> `C:\ProgramData\MyApp\backup\config.json`
```

Raw strings cannot contain a backtick. No interpolation occurs.

## 3. Top-level structure

A `.undo` file is a filesystem program containing **one or more named transactions**.

```undo
transaction "prepare" {
    mkdir "backup"
}

transaction "upgrade" {
    require exists "config.json"

    move "plugins" -> "extensions"

    assert exists "extensions"
}
```

Transaction names must be non-empty and unique within a file. Source order defines default whole-program execution order.

Inside each transaction, the semantic phases are strict:

1. zero or more `require` statements;
2. zero or more mutation statements;
3. zero or more `assert` statements.

A `require` after the first mutation is a semantic error. A mutation after the first `assert` is a semantic error.

This phase restriction makes transaction semantics obvious and prevents accidental mid-transaction condition behavior. A transaction may omit `require` and/or `assert`; real filesystem/operation failures are detected independently of assertions.

## 4. EBNF

```ebnf
program          = transaction , { transaction } , EOF ;

transaction      = "transaction" , string , "{" ,
                   { require_stmt } ,
                   { mutation_stmt } ,
                   { assert_stmt } ,
                   "}" ;

require_stmt     = "require" , condition ;
assert_stmt      = "assert" , condition ;

mutation_stmt    = mkdir_stmt
                 | copy_stmt
                 | move_stmt
                 | write_stmt
                 | replace_stmt
                 | delete_stmt ;

mkdir_stmt       = "mkdir" , path ;
copy_stmt        = "copy" , path , "->" , path , [ "overwrite" ] ;
move_stmt        = "move" , path , "->" , path , [ "overwrite" ] ;
write_stmt       = "write" , path , "=" , string ;
replace_stmt     = "replace" , path , string , "->" , string ;
delete_stmt      = "delete" , path ;

condition        = exists_cond
                 | not_exists_cond
                 | is_file_cond
                 | is_dir_cond
                 | contains_cond
                 | sha256_cond ;

exists_cond      = "exists" , path ;
not_exists_cond  = "not_exists" , path ;
is_file_cond     = "is_file" , path ;
is_dir_cond      = "is_dir" , path ;
contains_cond    = "contains" , path , string ;
sha256_cond      = "sha256" , path , "=" , string ;

path             = string ;
string           = quoted_string | raw_string ;
```

## 5. Statement semantics

### 5.1 `transaction`

```undo
transaction "upgrade-v2" { ... }
```

- Name is required and must be non-empty after whitespace validation.
- Transaction name is descriptive/selectable; runtime identity is still a generated UUID per execution.
- Names must be unique within the containing program.
- Name is stored in journal metadata and JSON output.
- `undo run FILE` executes all transactions in source order; `undo run FILE --transaction NAME` selects exactly one. The entire source must parse/validate in either mode.

### 5.2 `require`

Precondition evaluated during planning/run before any target mutation.

```undo
require exists "config.json"
require sha256 "config.json" = "<64 hex chars>"
```

If false, execution terminates with `E_PRECONDITION_FAILED`; no mutation begins.

### 5.3 `assert`

Optional semantic postcondition evaluated after all mutation operations but before commit. `assert` is not the only failure detector: filesystem/I/O/permission/disk-space errors and operation verification failures also fail and roll back the current transaction.

```undo
assert exists "extensions"
assert contains "VERSION" "2"
```

If false, transaction fails and rollback begins.

### 5.4 `mkdir`

```undo
mkdir "backup"
```

Semantics:

- create a single directory and required parent chain only if planner explicitly represents the chain;
- implementation may use recursive creation internally, but every newly created path must be represented in inverse state;
- if target exists as a directory, treat as an idempotent no-op and record this in the plan;
- if target exists as a non-directory, fail.

Recommended planner output distinguishes `create` versus `already_exists`.

### 5.5 `copy`

```undo
copy "config.json" -> "backup/config.json"
copy "templates" -> "backup/templates"
copy "a" -> "b" overwrite
```

Semantics:

- source may be regular file or directory;
- directories are recursively copied without following symlink directory traversal;
- default destination collision is an error;
- explicit `overwrite` allows replacing an existing destination after it is safely backed up;
- preserve basic permission mode for regular files/directories where portable;
- preserve file contents exactly;
- do not silently preserve unsupported ACL/xattr/ownership semantics;
- symlink behavior is defined in `SECURITY_AND_EDGE_CASES.md` and must be explicit in implementation/docs.

### 5.6 `move`

```undo
move "plugins" -> "extensions"
move "old.conf" -> "new.conf" overwrite
```

Semantics:

- default destination collision is an error;
- `overwrite` requires destination backup before mutation;
- prefer same-filesystem rename where supported;
- if a portable/safely detectable cross-device move requires copy+verify+delete, the journal must represent each stage sufficiently for recovery;
- never pretend cross-device move is atomic.

### 5.7 `write`

```undo
write "VERSION" = "2\n"
```

Semantics:

- creates file if absent;
- replaces file content if present after backup;
- writes to a temporary file in the destination directory, syncs it, then replaces destination according to platform semantics;
- intended for reasonably small literal content in the `.undo` file;
- no environment interpolation or template evaluation.

### 5.8 `replace`

```undo
replace "config.env" "PORT=3000" -> "PORT=8080"
```

Semantics:

- literal byte-sequence replacement, not regex;
- replaces all non-overlapping matches from left to right;
- `old` must not be empty;
- source must be a regular file;
- if no match exists, fail with `E_REPLACE_PATTERN_NOT_FOUND` rather than silently succeeding;
- implementation should stream with bounded memory and a carry buffer so matches spanning read chunks are handled correctly;
- output goes to a synced temp file, then replaces original after original backup state is durable.

### 5.9 `delete`

```undo
delete "legacy.json"
delete "old-cache"
```

Semantics:

- path must exist;
- regular files, symlinks, and directory trees are supported according to explicit file-type policy;
- deletion is made reversible by stashing/copying required prior state before final removal;
- missing path is an error; use `require`/design a different transaction rather than silently ignoring it.

## 6. Condition semantics

### `exists PATH`
True if an entry exists under the effective capability path.

### `not_exists PATH`
True if no entry exists.

### `is_file PATH`
True only for a regular file; symlink-to-file behavior must not silently blur `Lstat` vs followed target. The runtime should define this as the resolved safe target being a regular file while preventing capability escape.

### `is_dir PATH`
True only for a directory under safe resolution.

### `contains PATH TEXT`
- regular files only;
- literal byte sequence;
- stream search with bounded memory;
- no regex.

### `sha256 PATH = HEX`
- regular file only;
- stream SHA-256 using `crypto/sha256`;
- expected digest must be exactly 64 hexadecimal characters;
- case-insensitive hex input is acceptable, normalized to lowercase internally.

## 7. Paths

Paths are strings. They are not shell expressions.

### Relative

```undo
copy "config/app.json" -> "backup/app.json"
```

Resolved against transaction root supplied by `--root` or default current working directory.

### Absolute inside root

Allowed after mapping into the root capability.

### Absolute outside root

Requires an explicit capability:

```bash
undo run deploy.undo --root /opt/myapp --allow-path /etc/myapp
```

The allowed path should represent a directory tree, not an arbitrary glob.

### No interpolation

These are literal strings in MVP:

```undo
write "$HOME/file" = "x"
write "${APP_HOME}/file" = "x"
```

They do not expand environment variables.

## 8. Reserved paths

The runtime state tree (default `.undo/` under transaction root or exact location chosen in `TECHNICAL_SPEC.md`) is reserved.

Any DSL operation attempting to read/mutate runtime internals in a way that can interfere with journal/backup correctness must be rejected with `E_RESERVED_PATH`.

## 9. Error positions

Every token stores:

- byte offset,
- 1-based line,
- 1-based column,
- original lexeme span where safe.

Example:

```text
migration.undo:7:5: E_UNKNOWN_INSTRUCTION

    mve "old" -> "new"
    ^^^

unknown instruction "mve"; did you mean "move"?
```

Suggestion logic may be a small handwritten edit-distance function; do not add a package for it.

## 10. AST model

Recommended core model:

```go
type Program struct {
    Transactions []Transaction
}

type Transaction struct {
    Name         string
    Requires     []Condition
    Operations   []Operation
    Assertions   []Condition
    Span         Span
}
```

Each operation/condition carries source span and typed arguments.

Do not preserve parser tokens as the execution model. Parser output should become immutable/validated domain structures before planning.

## 11. Program selection and execution semantics

- `undo check FILE` validates the complete program and returns the ordered transaction names.
- `undo plan FILE --transaction NAME` plans one named transaction exactly against current state.
- `undo plan FILE` with multiple transactions emits a program plan; later state-dependent checks may be marked deferred until preceding transactions have committed.
- `undo run FILE --transaction NAME` runs only that transaction.
- `undo run FILE` runs all transactions in source order.
- Each transaction is an independent recovery boundary with its own runtime ID/journal/backups/history.
- Whole-program execution stops on the first failed/precondition-failed/rolled-back/recovery-required transaction.
- Already committed earlier transactions are never implicitly rolled back.
- The runtime, not the script author, derives rollback from captured prior state and durable journal records. No `on_failure`/manual rollback block exists in DSL v1.

## 12. Versioning

The DSL contract is versioned independently from binary version.

Hackathon release may hard-code `undo-dsl/1` in `capabilities --json` and `schema --json`.

Do not add a source-level version directive unless there is a real compatibility need during the hackathon.

## 13. Examples

### Multi-transaction program

```undo
transaction "prepare" {
    mkdir "backup"
    copy "config.json" -> "backup/config.json"
}

transaction "upgrade" {
    require exists "config.json"
    move "plugins" -> "extensions"
    write "VERSION" = "2"
    assert exists "extensions"
}

transaction "cleanup" {
    delete "legacy"
}
```

Run all in source order:

```bash
undo run migration.undo
```

Run only one:

```bash
undo run migration.undo --transaction upgrade
```

### Safe project migration

```undo
transaction "auth-refactor" {
    require exists "src/auth"
    require not_exists "internal/auth"

    mkdir "internal/auth"
    move "src/auth/login.go" -> "internal/auth/login.go"
    move "src/auth/token.go" -> "internal/auth/token.go"
    delete "src/auth/legacy.go"

    assert exists "internal/auth/login.go"
    assert exists "internal/auth/token.go"
    assert not_exists "src/auth/legacy.go"
}
```

### System configuration with explicit external capability

```undo
transaction "rotate-app-config" {
    require is_file "/etc/myapp/app.conf"

    replace "/etc/myapp/app.conf" "PORT=3000" -> "PORT=8080"

    assert contains "/etc/myapp/app.conf" "PORT=8080"
}
```

Run:

```bash
undo run rotate.undo --root /opt/myapp --allow-path /etc/myapp
```

## 14. Features forbidden in DSL v1

The parser must reject rather than silently ignore attempts to introduce:

- `exec`, `shell`, `run`, or subprocess syntax;
- imports/includes;
- network URLs as operations;
- loops;
- conditions controlling branches;
- variables;
- environment interpolation;
- user functions;
- regex replacement;
- package/plugin invocation.

The constraint is a safety property, not missing polish.
