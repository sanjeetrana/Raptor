# UndoLang

**A programming language for transactional filesystem operations that can fail halfway, roll back safely, and commit only when the declared work and its postconditions succeed.**

UndoLang is a small, deliberately constrained `.undo` language and a crash-recoverable Go runtime for the dangerous work that ordinary scripts treat as a handful of unrelated file calls. A migration, deployment, configuration rewrite, generated-artifact update, or AI-assisted refactor can create several files, replace content, move a directory, and then discover that the final check cannot be satisfied. If the process dies between those steps—or a permission error appears after the first few mutations—an ordinary script often leaves a half-updated filesystem. UndoLang turns that work into an inspectable program: validate the entire source, evaluate preconditions, compute a plan, acquire a capability-scoped root, journal inverse state before each mutation, apply in order, verify assertions, and commit the transaction only after the complete sequence is known to be correct. On an operation failure, assertion failure, or interruption, the runtime reconstructs the durable journal and rolls back the affected transaction instead of guessing from in-memory state.

The result is not a general-purpose scripting language and it is not a promise of magical atomic visibility. It is a focused safety boundary for filesystem changes whose intermediate state matters. External programs may observe the work while it is running, and platform-specific durability limits are documented honestly; what UndoLang adds is an explicit program model, a reviewable plan, a durable record of what happened, and a recovery path when reality does not follow the happy path.

## Submission

- **Demo video:** [UndoLang on YouTube](https://youtu.be/0CjBEfw2E6o)
- **Live documentation and landing page:** [stalwart-sunshine-8747ed.netlify.app](https://stalwart-sunshine-8747ed.netlify.app/)
- **Source repository:** [github.com/daniel-oluwadunsin/undolang](https://github.com/daniel-oluwadunsin/undolang)
- **Track:** [Zero Dependency Hackathon](https://zerodepshack.com/) — **Track F, Open/Wildcard**
- **License:** MIT — see [`LICENSE`](LICENSE)

UndoLang is a Track F project because it is a useful systems tool that normally invites a CLI framework, parser generator, filesystem utility library, transaction engine, database, checksum package, and recovery framework. The submission replaces those layers with an intentionally small implementation built on Go’s standard library. The empty module graph, [`STDLIB.md`](STDLIB.md), [`deps-proof.txt`](deps-proof.txt), reproducible-build receipt, and one-command Makefile workflow are the evidence, not marketing shorthand.

### How the submission maps to the judging rubric

| Judging dimension                    | What this repository demonstrates                                                                                                                                                                               |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Functionality & Usefulness (35%)** | A runnable language and CLI for real multi-file migrations, upgrades, cleanup, and agent-reviewed filesystem work; six reversible operations; planning, execution, rollback, recovery, history, and inspection. |
| **Zero-Dependency Craft (30%)**      | Go 1.27 standard library only, an empty `go.mod` dependency graph, a concrete [`STDLIB.md`](STDLIB.md) substitution ledger, offline tests, dependency proof, and no runtime shell-outs.                         |
| **Code Quality & Idiom (25%)**       | Small ownership-focused packages, bounded streaming algorithms, explicit state machines, capability-root enforcement, defensive parsing, durable sync points, fuzz tests, race tests, and fail-closed recovery. |
| **Innovation (10%)**                 | A constrained filesystem programming language that makes rollback intent, preconditions, postconditions, and crash recovery inspectable without a workflow framework or database.                               |

The repository also supplies the **Reproducible Build** and **STDLIB Log** bonus evidence: `make reproducible-build` prints two byte-identity hashes, and `STDLIB.md` documents more than ten real package-to-standard-library substitutions.

## Why filesystem transactions matter

Filesystem automation is deceptively stateful. Consider an application upgrade that writes a new configuration, moves the old release directory, copies generated assets, updates a version marker, and removes obsolete files. A crash after the move but before the configuration assertion can leave a machine that is neither the old release nor the new one. A deployment script can report an error while the first four writes remain on disk. An AI agent can produce syntactically plausible file instructions without understanding that the fifth instruction depends on the first four or that the destination already contains irreplaceable state.

UndoLang makes those assumptions explicit:

1. **The source is a program.** All transactions, syntax, argument shapes, and semantic rules are parsed and validated before any target mutation.
2. **A transaction is the rollback boundary.** Requirements run before mutations; mutations run in source order; assertions run after mutations.
3. **The plan is reviewable.** `check` and `plan` report paths, effects, conflicts, readiness, warnings, and rollback estimates without creating `.undo` state or changing target data.
4. **The journal is authoritative.** Backups and operation records are synced before destructive assumptions are made. Recovery replays durable records from a fresh process.
5. **Success is earned.** A transaction reaches `COMMITTED` only after operations and assertions pass, the commit record is durable, and cleanup is safe.
6. **Ambiguity fails closed.** Corrupt journals, unsafe paths, uncertain post-crash state, unsupported file types, and incomplete recovery preserve evidence and backups rather than making a destructive guess.

This is useful for release tooling, configuration migration, data-layout changes, workspace cleanup, generated-code updates, and agent-authored changes where the operator wants a bounded, explainable filesystem capability instead of unrestricted shell access.

## The execution model: program versus transaction

A `.undo` file is an ordered **program** containing one or more uniquely named **transactions**:

```text
program     = transaction+
transaction = "transaction" STRING "{" require* mutation* assert* "}"
```

The default `run FILE` behavior executes every transaction in source order. `run FILE --transaction NAME` selects exactly one named transaction, but the complete source file is still parsed and semantically validated first. Whole-file execution is sequential and fail-fast, never an implicit super-transaction:

- the current transaction gets a fresh exact plan immediately before it starts;
- if it commits, that commit remains committed even if a later transaction fails;
- if it fails, only that transaction is rolled back (or marked recovery-required if rollback is ambiguous);
- later transactions are reported as `skipped` and are not attempted.

The same distinction appears in planning. A selected transaction—or a single-transaction program—can receive an exact current-state plan. In a multi-transaction plan, the first transaction is exact and later state-sensitive work is marked `deferred` because those files may be changed by earlier transactions before execution.

## A complete example

This is real UndoLang syntax and can be parsed by the repository’s front end:

```undo
# A precondition, mutations, and postconditions in one recoverable boundary.
transaction "prepare-release" {
  require is_dir "workspace"
  require contains "workspace/VERSION" "1.4"

  mkdir "workspace/staging"
  copy "workspace/config.next" -> "workspace/staging/config" overwrite
  write "workspace/staging/VERSION" = "1.5"
  replace "workspace/staging/config" "environment=staging" -> "environment=production"
  delete "workspace/staging/obsolete.txt"

  assert is_dir "workspace/staging"
  assert contains "workspace/staging/VERSION" "1.5"
}
```

If `mkdir`, `copy`, `write`, `replace`, or `delete` fails—or either assertion is false—the runtime uses the durable inverse metadata for this transaction to restore the prior state. If every operation and assertion succeeds, the commit record is synced and the backup set can be cleaned.

## Language reference

### Operations

| Instruction | Form                                | Meaning                                                                                                               | Reversibility                                                                                    |
| ----------- | ----------------------------------- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `mkdir`     | `mkdir PATH`                        | Create a directory and any missing parent directories, recording exactly what this transaction created.               | Removes only directories created by the operation, in safe reverse order.                        |
| `copy`      | `copy SOURCE -> TARGET [overwrite]` | Copy a regular file or recursively copy a directory tree. Symlink copying is rejected.                                | Removes the created destination or restores a backed-up destination when `overwrite` is present. |
| `move`      | `move SOURCE -> TARGET [overwrite]` | Rename within a capability, or use a verified copy/sync/delete fallback for explicitly recognized cross-device cases. | Moves the entry back or restores the overwritten destination.                                    |
| `write`     | `write PATH = STRING`               | Write a complete file through a root-safe temporary file, sync, and replacement protocol.                             | Restores the previous entry or removes a newly created file.                                     |
| `replace`   | `replace PATH OLD -> NEW`           | Literal, non-overlapping, streaming replacement across chunk boundaries.                                              | Restores the original file bytes and mode.                                                       |
| `delete`    | `delete PATH`                       | Delete a regular file, directory tree, or symlink entry itself.                                                       | Restores the backed-up entry.                                                                    |

Destination parents must already exist for `copy`, `move`, `write`, and `replace`; `mkdir` is the explicit parent-chain operation. `overwrite` means replace the complete destination entry after backing it up—it never silently merges directory trees.

### Conditions

```text
require exists PATH
require not_exists PATH
require is_file PATH
require is_dir PATH
require contains PATH TEXT
require sha256 PATH = HEX

assert exists PATH
assert not_exists PATH
assert is_file PATH
assert is_dir PATH
assert contains PATH TEXT
assert sha256 PATH = HEX
```

`contains` and SHA-256 stream through bounded buffers; arbitrary files are not loaded into memory. SHA-256 values must be exactly 64 hexadecimal characters. Empty `contains` needles and empty `replace` patterns are rejected semantically. Conditions use safe `lstat`/`stat` behavior according to the operation and never grant a script implicit shell, network, package, or environment interpolation features.

### Strings, comments, and paths

- Double-quoted strings support the documented escapes, including `\\`, `\"`, `\n`, `\r`, `\t`, and `\uXXXX`.
- Backtick raw strings are available for Windows-friendly paths such as `` `C:\\Users\\me\\data` ``.
- `#` starts a comment outside a string.
- UTF-8 input is lexed with byte offsets and 1-based line/column positions. CRLF is counted as one newline, and malformed UTF-8 produces a diagnostic rather than a panic.
- There are no variables, loops, functions, imports, arbitrary commands, plugins, hidden interpolation, or network calls. The constrained surface is part of the safety argument.

## Safety pipeline

Every mutating run follows an explicit sequence:

```text
parse complete source
    -> semantic validation and phase ordering
    -> capability/path validation
    -> exact preflight plan and conflict analysis
    -> unresolved-state check and durable root lock
    -> re-plan and re-evaluate preconditions after locking
    -> PREPARED / RUNNING journal state
    -> prepare + verify backup + OP_PREPARED (sync)
    -> apply one operation + verify + OP_APPLIED (sync)
    -> VERIFYING and assertion records
    -> COMMITTING + TX_COMMIT (sync)
    -> COMMITTED and safe backup cleanup
```

Failure at any point enters journal-authoritative rollback. Recovery never depends on an in-memory slice of “completed operations”; it validates the durable prefix, classifies each prepared/applied operation as forward, restored, or ambiguous, and only performs an inverse when the state is provable. A checksum error, sequence gap, semantic mismatch, or ambiguous filesystem state is a recovery failure with backups retained.

## Capabilities and path security

UndoLang treats filesystem access as a capability rather than a string-prefix convention:

- the primary transaction root defaults to the invocation working directory and can be set with `--root`;
- relative DSL paths always bind to the primary root, never to the script’s directory;
- repeatable `--allow-path DIR` flags add explicit capability roots for external absolute paths;
- an absolute path is mapped to the most-specific declared capability root;
- actual opens and traversal use Go 1.27 `os.OpenRoot`/`os.Root` enforcement;
- lexical `..` escapes, root mutation, reserved `.undo` state, unsafe symlink traversal, and undeclared absolute paths are rejected;
- symlink entries may be moved or deleted as entries, but unsafe dereference and symlink copy are rejected;
- FIFOs, sockets, devices, unsupported reparse points, and other special files are rejected.

The path layer is intentionally conservative. A path that is merely textually beneath a root is not considered safe until root-scoped filesystem access and entry-type policy agree.

## Durable state, journal, and recovery

The runtime stores protected state below the transaction root:

```text
<root>/.undo/
├── active.lock
└── transactions/<UUIDv7>/
    ├── metadata.json
    ├── status.json
    ├── journal.bin
    └── backups/...
```

The state directory and metadata use restrictive modes where the platform supports them. `active.lock` is acquired with exclusive creation and unresolved locks are never cleared solely because a recorded PID is no longer alive. Transaction IDs are sortable UUIDv7 values from the Go standard library.

The append-only journal uses a bounded, checksummed frame:

```text
UNDO magic | version u16 | type u16 | sequence u64 |
payload length u32 | JSON payload | CRC32C u32
```

Payloads are capped before allocation. Sequences begin at one and are strictly monotonic. The decoder rejects unknown versions/types, gaps, duplicates, transaction-ID mismatches, invalid operation references, checksum failures, and semantic state inconsistencies. Only incomplete bytes at the end of an otherwise valid prefix are treated as a torn tail; complete corruption fails closed. Recovery may truncate and sync only that incomplete final frame.

The durable lifecycle is:

```text
PLANNED -> PREPARED -> RUNNING -> VERIFYING -> COMMITTING -> COMMITTED
                                      \-> rollback -> ROLLED_BACK
```

`recover --root ROOT --yes` discovers unresolved state, validates metadata and journal correspondence, and rolls back only the unresolved transaction. Recovery is idempotent when interrupted during rollback. It retains backups and reports a recovery-specific failure when the inverse cannot be proven safe. UndoLang does not claim isolation, universal atomic visibility, or post-commit undo.

## CLI

Build `undo` and use `undo --help` for the full command surface:

| Command        | Purpose                                                                           | Mutates targets?               |
| -------------- | --------------------------------------------------------------------------------- | ------------------------------ |
| `check FILE`   | Parse, validate, and validate paths/capabilities.                                 | No                             |
| `plan FILE`    | Show exact or deferred effects, conflicts, readiness, and rollback estimates.     | No                             |
| `run FILE`     | Execute all transactions in source order, or one with `--transaction NAME`.       | Yes, with journal and rollback |
| `recover`      | Reconcile and roll back unresolved durable state.                                 | Yes, only as recovery          |
| `history`      | List local transaction metadata, newest first.                                    | No                             |
| `inspect TXID` | Validate and inspect metadata, journal records, operations, and backup retention. | No                             |
| `capabilities` | Describe supported operations, path model, and recovery classifications.          | No                             |
| `schema`       | Print the versioned language and workflow schema.                                 | No                             |
| `agent-guide`  | Print the machine-agent workflow and approval rules.                              | No                             |
| `version`      | Print deterministic product, DSL, API, and Go version information.                | No                             |

Common options are `--root DIR`, repeatable `--allow-path DIR`, `--transaction NAME`, `--json`, and `--no-color`. Mutating commands require explicit `--yes` in noninteractive or JSON use. Interactive `run` summarizes the complete declared program and asks for confirmation when stdin and stdout are terminals. `--json` never grants approval and never mixes progress prose into stdout.

### Machine-readable contract

JSON responses use API version `undo-cli/1`, stable result fields, ordered transaction entries, and structured errors with stable codes. A failed whole-program run can include committed, rolled-back, recovery-required, and skipped entries in source order. Important statuses include `committed`, `rolled_back`, `failed_preflight`, `recovery_required`, `recovery_failed`, and `skipped`.

Exit classes are stable and documented in `undo schema --json`:

| Exit | Class                                            |
| ---: | ------------------------------------------------ |
|    0 | Success                                          |
|    1 | Usage, language, approval, or cancellation       |
|    2 | Unsafe plan or failed precondition               |
|    3 | Path, conflict, permission, or no-space failure  |
|    4 | Transaction failed but rollback succeeded        |
|    5 | Recovery required                                |
|    6 | Rollback, recovery, or journal-integrity failure |
|    7 | Internal invariant failure                       |

For an agent, the safest workflow is:

```sh
undo capabilities --json
undo schema --json
undo check FILE.undo --root ROOT --json
undo plan FILE.undo --root ROOT --json
# obtain human approval for the returned plan
undo run FILE.undo --root ROOT --yes --json
# if recovery_required is returned:
undo recover --root ROOT --yes --json
```

## Build and install

UndoLang’s source build uses Go **1.27.x** and no third-party modules. The shortest checkout build is:

```sh
git clone https://github.com/daniel-oluwadunsin/undolang.git
cd undolang
go build -trimpath -buildvcs=false -o undo ./cmd/undo
./undo version
```

The canonical offline/reproducible form is:

```sh
CGO_ENABLED=0 GOTOOLCHAIN=go1.27.0 GOPROXY=off \
  go build -trimpath -buildvcs=false -o undo ./cmd/undo
```

`make build` is the convenient equivalent. A prebuilt binary does not need Go, a runtime service, or an API key. For local source installation:

```sh
# macOS / Linux: uses ./undo if present, otherwise builds the checkout.
./install.sh

# Windows PowerShell:
.\install.ps1
```

If no compatible compiler is found, the installers can download the official Go 1.27.0 archive, verify its pinned SHA-256 checksum, and place it in a user-local UndoLang toolchain directory. Use `--no-install-go` or `-NoInstallGo` to require an entirely offline/local install. No administrator privileges are required.

## Reproducible build bonus

Run one Make target to build twice with the pinned toolchain and print both hashes:

```sh
make reproducible-build
```

`make repro` is an alias. The script uses `CGO_ENABLED=0`, `GOTOOLCHAIN=go1.27.0`, `GOPROXY=off`, `-trimpath`, and `-buildvcs=false`, then hashes both binaries with the repository’s own standard-library helper. The checked-in receipt is [`docs/reproducible-build.txt`](docs/reproducible-build.txt); it is published only after byte-identical output is demonstrated on the same machine and toolchain.

## Zero-dependency proof

The shipped runtime has an empty dependency manifest:

```go
module github.com/daniel-oluwadunsin/undolang

go 1.27
```

There is no `require` block, no `go.sum`, no vendored source, no database, no cloud service, and no runtime subprocess invocation. The proof command is:

```sh
make deps-proof
GOTOOLCHAIN=go1.27.0 GOPROXY=off go list -m all
```

The module list contains only `github.com/daniel-oluwadunsin/undolang`. [`STDLIB.md`](STDLIB.md) records concrete substitutions, including:

- `flag.FlagSet` and explicit dispatch instead of Cobra or a CLI framework;
- a UTF-8 lexer and recursive-descent parser instead of a parser generator;
- `os.OpenRoot`, `io/fs`, and `filepath` instead of a sandbox package;
- bounded `bufio`/`bytes` state machines instead of a streaming search package;
- `crypto/sha256`, `hash/crc32`, and `encoding/hex` instead of hashing/checksum modules;
- `uuid.NewV7` instead of a UUID dependency;
- `encoding/json/v2` and concrete structs instead of a schema/JSON framework;
- an append-only synced journal and status files instead of SQLite;
- explicit transaction state machines and journal replay instead of a workflow engine;
- `io.CopyBuffer` and root-safe recursion instead of a file-copy utility;
- `testing`, fuzzing, race detection, and real subprocesses instead of a mock stack;
- hand-written HTML/CSS/JavaScript instead of a website framework.

See [`deps-proof.txt`](deps-proof.txt), [`docs/deps-proof.txt`](docs/deps-proof.txt), [`STDLIB.md`](STDLIB.md), and [`docs/STDLIB.md`](docs/STDLIB.md) for the receipts and source references.

## Architecture

UndoLang is split into small ownership layers so the safety story can be reviewed independently:

| Package                                                     | Responsibility                                                                                      |
| ----------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `cmd/undo`                                                  | Minimal executable entrypoint.                                                                      |
| `internal/cli`                                              | Stdlib flag dispatch, approvals, human/JSON output, and exit classes.                               |
| `internal/lang/token`, `lexer`, `parser`, `ast`, `validate` | Tokens/spans, UTF-8 lexing, grammar, AST, diagnostics, and semantic validation.                     |
| `internal/pathcap`                                          | Capability roots, safe path mapping, `os.Root` access, reserved-state and symlink policy.           |
| `internal/condition`                                        | Bounded-memory exists/type/contains/SHA-256 evaluation.                                             |
| `internal/plan`                                             | Immutable plans, symbolic overlays, conflict detection, effects, readiness, and rollback estimates. |
| `internal/streamutil`                                       | Bounded copy, streaming search, hash, and literal replacement.                                      |
| `internal/fsop`                                             | Prepare/apply/verify/undo primitives, backups, tree traversal, and supported file-type policy.      |
| `internal/journal`                                          | Framed append/sync, CRC32C, bounded decoding, torn-tail handling, and replay validation.            |
| `internal/state`                                            | `.undo` layout, UUIDv7 metadata, lock lifecycle, statuses, history, and inspection.                 |
| `internal/txn`                                              | One transaction’s durable lifecycle and operation sequencing.                                       |
| `internal/program`                                          | Source-order selection, fail-fast execution, and skipped results.                                   |
| `internal/recovery`                                         | Fresh-process journal replay and restartable reverse rollback.                                      |
| `internal/report`                                           | Versioned JSON envelopes and stable error models.                                                   |
| `marketing/`                                                | Static site with no package manifest or external runtime assets.                                    |
| `tools/buildproof`                                          | Standard-library streaming hash helper for release evidence.                                        |

## Verification and evidence

The repository includes table-driven and integration coverage for:

- lexer/parser/validator spans, escapes, CRLF, raw Windows paths, duplicate names, malformed input, and fuzz panic resistance;
- relative and absolute capabilities, `..` traversal, reserved `.undo`, symlink escapes, script/root independence, large-file conditions, and path policy;
- planner overlays, effects, duplicate writers, self-copy/move, use-after-delete/move, deferred multi-transaction readiness, and no-mutation snapshots;
- framed-journal corruption, payload caps, sequence/version/checksum failures, semantic replay, torn tails, and decoder fuzzing;
- real copy, recursive tree copy, move, write, replace, delete, overwrite restoration, modes, symlink policy, special-file rejection, streaming boundaries, and cleanup failures;
- operation failure, failed postconditions, real process termination at durable points, fresh-process recovery, stale locks, and repeated/idempotent recovery;
- compiled-binary CLI behavior, JSON purity, approvals, exit codes, history, inspect, examples, and documentation snippets;
- race detection, opt-in large-file/tree stress checks, dependency proof, reproducible builds, and Linux/macOS/Windows cross-builds.

`go list -m all` is intentionally part of the submission evidence: it must print only the main module.

## Documentation and agent context

The static site at [stalwart-sunshine-8747ed.netlify.app](https://stalwart-sunshine-8747ed.netlify.app/) contains getting started, installation for macOS/Linux/Windows, the language reference, program and transaction semantics, capabilities, recovery, security, AI-agent guidance, examples, and limitations. The repository equivalents are:

- [`docs/LANGUAGE.md`](docs/LANGUAGE.md) — syntax and operation reference;
- [`docs/TRANSACTIONS.md`](docs/TRANSACTIONS.md) — planning, journaling, rollback, and recovery;
- [`docs/SECURITY.md`](docs/SECURITY.md) — threat model and supported boundaries;
- [`docs/AGENTS_GUIDE.md`](docs/AGENTS_GUIDE.md) — machine-agent workflow and JSON contract;
- [`docs/SUPPORT_MATRIX.md`](docs/SUPPORT_MATRIX.md) — tested versus cross-built platforms;
- [`docs/IMPLEMENTATION_REPORT.md`](docs/IMPLEMENTATION_REPORT.md) — package map, verification evidence, and limitations;
- [`examples/fs.undo`](examples/fs.undo) — a real parseable example;
- [`TESTING.md`](TESTING.md) — copy/paste local testing workflow.

For an agent, retrieve capabilities and schema before proposing a mutation. Treat the plan as an approval artifact, pass `--yes` only after approval, keep JSON stdout separate from human logs, and stop for `recover` whenever the runtime reports `recovery_required`.

## Repository map

```text
cmd/undo/                 executable
internal/                 language, capabilities, planner, state, journal, runtime
tests/                    documentation and black-box coverage
examples/                 real `.undo` programs
docs/                     specifications, security, support, receipts, report
marketing/                static landing page and documentation shell
scripts/                  offline proof, reproducible build, release, installers
tools/buildproof/         stdlib-only binary hashing helper
Makefile                  one-command build, test, proof, release, and CLI entrypoints
go.mod                    empty third-party dependency manifest
STDLIB.md                 stdlib substitution ledger
deps-proof.txt            dependency proof receipt
```

## Status

UndoLang 0.1.0 is a complete submission artifact for the Zero Dependency Hackathon: a real language front end, capability-scoped planner, durable journal, reversible filesystem primitives, transaction runner, fresh-process crash recovery, machine-readable CLI, static documentation site, and reproducible-build/dependency receipts. The project chooses a narrow, explainable filesystem surface over shell compatibility or a claim of universal filesystem atomicity.

Built by [Daniel Oluwadunsin](https://github.com/daniel-oluwadunsin).
