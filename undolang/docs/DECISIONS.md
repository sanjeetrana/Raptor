# UndoLang — Locked Product Decisions

This file captures decisions already made. Do not reopen them unless implementation reveals a genuine safety/correctness blocker.

## Product and track

- Product name: **UndoLang**.
- CLI executable: **`undo`**.
- Script extension: **`.undo`**.
- Hackathon submission track: **Track F — Open / Wildcard**.
- Implementation language: **Go 1.27**.
- Runtime dependency policy: **Go standard library only. `go.mod` must contain no `require` block.**
- Marketing/docs: static HTML + CSS + vanilla JavaScript under `marketing/`; no framework, no npm, no CDN requirement.

## Language philosophy

- UndoLang is a **small filesystem transaction DSL**, not a general-purpose language.
- A `.undo` file may live anywhere and can be passed to `undo run` by relative or absolute script path.
- A `.undo` file is a **filesystem program** containing **one or more named top-level transactions**.
- Transaction names are non-empty and unique within a file.
- A transaction is the atomic/recoverable unit; the whole file is not an implicit super-transaction.
- `undo run FILE --transaction NAME` runs exactly one named transaction.
- `undo run FILE` runs all transactions in source order (or the only transaction when there is one).
- Whole-program execution is sequential and fail-fast. If a later transaction fails, that transaction rolls back; earlier committed transactions remain committed; later transactions are skipped.
- No loops, functions, user-defined types, imports, arbitrary code execution, arbitrary subprocess execution, package execution, network calls, or shell commands.
- Every mutation must be representable, inspectable, journalable, and reversible by the Undo runtime.

## Path model

- Relative filesystem paths resolve against the **transaction root**, not the script's directory.
- Default transaction root is the caller's current working directory.
- `--root PATH` overrides the root.
- Absolute paths are supported.
- Absolute paths that fall inside the transaction root are allowed.
- Absolute paths outside the transaction root require one or more explicit `--allow-path DIRECTORY` capabilities.
- `..` traversal and symlink escape outside a capability root must be rejected.
- Use Go `os.Root` / `os.OpenRoot` as the primary traversal-resistant filesystem primitive.
- The `.undo` state directory is reserved and cannot be targeted by script mutations.

## Agent compatibility

UndoLang must be self-describing. Required machine-friendly commands/interfaces include:

- `undo capabilities --json`
- `undo schema --json`
- `undo agent-guide`
- `undo check FILE --json`
- `undo plan FILE --json`
- `undo run FILE --json`
- `undo recover --json`

All important errors need stable error codes and deterministic exit codes.

## Transaction semantics

- Whole source program lexes, parses, and validates **before** any filesystem mutation. Each selected transaction is then freshly state-planned immediately before it executes.
- All `require` preconditions for a transaction are checked before that transaction mutates. Real operation/I/O failures are also first-class transaction failures; `assert` is not the only failure detector.
- Mutating operations run only after planning and safety validation succeed.
- All `assert` postconditions are checked after mutations and before commit.
- A failed filesystem operation, operation verification, or postcondition initiates automatic rollback of the current transaction from runtime-owned prior-state/journal data. Script authors do not define normal rollback code.
- An interrupted transaction is detected on the next invocation and requires recovery.
- Core promise is **crash-safe recoverability**, not magical cross-platform ACID isolation.
- Do not claim all multi-file changes are atomically invisible to other processes.
- Only one active UndoLang transaction per transaction root in MVP.

## Core operation set

Required mutation statements:

- `mkdir`
- `copy`
- `move`
- `write`
- `replace`
- `delete`

Required conditions:

- `exists`
- `not_exists`
- `is_file`
- `is_dir`
- `contains`
- `sha256`

## Safety

- No implicit shell/environment-variable expansion in paths or content.
- No automatic `$HOME`, `%APPDATA%`, or `${VAR}` substitution in MVP.
- No external command execution under any syntax.
- Path access outside declared capability roots fails closed.
- Journal/state files use restrictive permissions where the platform supports them.
- Journal metadata must not duplicate full file contents; content backups live in the protected backup area.

## Distribution

- Primary distribution is a native compiled Go executable.
- End users do not need Go when using prebuilt release binaries.
- Running the downloaded binary directly is supported; installation is optional.
- Provide a local `install.sh` convenience path for macOS/Linux and a PowerShell equivalent for Windows, but these must not be runtime requirements. If a source build lacks Go 1.27.x, the installers may fetch and checksum-verify the official Go 1.27.0 archive into a user-local toolchain directory; copying a prebuilt binary remains fully offline. `--no-install-go` / `-NoInstallGo` disables bootstrap.
- No installer may make the product depend on a daemon, package manager, database, or cloud service.

## Bonus strategy

- Target reproducible build (+5).
- Target STDLIB Log (+3).
- Do not pursue Single File if it harms architecture/code quality.
- Package Killer only if honestly earned by the final implementation.
