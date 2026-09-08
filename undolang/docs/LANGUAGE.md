# UndoLang Language Reference

UndoLang is deliberately small: a UTF-8 `.undo` file contains one or more uniquely named transactions, and each transaction contains preconditions, mutations, then postconditions.

```text
program      = transaction+
transaction  = "transaction" string "{" require* mutation* assert* "}"
require      = "require" condition
assert       = "assert" condition
```

Statements preserve source order. `require` statements must come first, followed by mutations, followed by `assert` statements. Comments begin with `#` and continue to the end of the line.

## Strings and paths

Quoted strings support `\\`, `\"`, `\n`, `\r`, `\t`, and `\uXXXX`. Invalid UTF-8 and surrogate Unicode escapes are rejected. Backtick raw strings are useful for Windows paths:

```text
copy `C:\staging\app.conf` -> `C:\ProgramData\Acme\app.conf` overwrite
```

Paths never interpolate environment variables. Relative paths bind to the transaction root, not the script directory.

## Mutations

| Statement | Meaning |
|---|---|
| `mkdir PATH` | Create the missing directory chain. |
| `copy SOURCE -> TARGET [overwrite]` | Stream-copy a regular file or directory tree. |
| `move SOURCE -> TARGET [overwrite]` | Move an entry; verified copy/delete is used across capabilities. |
| `write PATH = STRING` | Durably replace or create a regular file. |
| `replace PATH OLD -> NEW` | Literal, non-overlapping, left-to-right replacement. |
| `delete PATH` | Remove a file, directory tree, or symlink entry. |

`overwrite` is explicit and replaces the complete destination entry; directories are not merged. Symlink copy and special files are rejected. Every supported mutation has runtime-owned inverse metadata.

## Conditions

Conditions are `exists PATH`, `not_exists PATH`, `is_file PATH`, `is_dir PATH`, `contains PATH TEXT`, and `sha256 PATH = HEX`. `contains` and SHA-256 stream with bounded memory. SHA-256 values contain exactly 64 hexadecimal characters and empty `contains` needles are invalid. `exists`/`not_exists` inspect a symlink entry itself; `is_file` and `is_dir` return false for symlinks; content conditions refuse to dereference symlink targets.

## Program example

```undolang
transaction "upgrade" {
  require contains "VERSION" "1"
  copy "release/app" -> "bin/app" overwrite
  write "VERSION" = "2"
  assert contains "VERSION" "2"
}
```
