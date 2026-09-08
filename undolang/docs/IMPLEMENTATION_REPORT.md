# UndoLang 0.1.0 Implementation Report

Status: repository implementation and local readiness gates are green as of
2026-08-29. There is no repository-level blocker. Actual submission still
requires the owner to publish the repository, upload release artifacts if
desired, record/publish the demo, and submit the hackathon form.

## What was built

UndoLang is a Go 1.27, standard-library-only filesystem transaction runtime and
small `.undo` DSL. The release includes:

- a UTF-8 lexer, recursive-descent parser, source spans, diagnostics, AST, and
  strict `require* -> mutation* -> assert*` semantic validation;
- capability-root path resolution using `os.OpenRoot`/`os.Root`, explicit
  `--allow-path` roots, reserved `.undo` protection, and symlink-safe policy;
- exact current-state transaction plans plus deferred readiness for later
  transactions in a whole-program plan;
- six real reversible operations: `mkdir`, `copy`, `move`, `write`, `replace`,
  and `delete`;
- bounded-memory streaming copy, SHA-256, contains, and literal replace;
- restrictive `.undo` state, exclusive active-root locking, UUIDv7 metadata,
  synced atomic status, and a framed CRC32C append-only journal;
- journal-authoritative reverse rollback, real process-kill recovery,
  idempotent interrupted recovery, torn-tail handling, and fail-closed
  corruption/ambiguity handling;
- sequential fail-fast multi-transaction execution, with each transaction as
  its own rollback boundary;
- human and versioned `undo-cli/1` JSON CLI output, stable error classes,
  approval gating, history/inspection, capabilities, schema, and agent guide;
- static HTML/CSS/vanilla-JS marketing and documentation pages;
- local build, install, reproducibility, dependency-proof, and five-target
  cross-build tooling.
- a root `Makefile` exposing the canonical build, offline test gates, proofs,
  release checks, and common CLI commands, plus a simple copy/paste
  [`TESTING.md`](../TESTING.md) human testing guide.

## Architecture and package map

| Package                                         | Responsibility                                                                             |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `cmd/undo`                                      | Minimal executable entrypoint.                                                             |
| `internal/buildinfo`                            | Deterministic product, DSL, and JSON API versions.                                         |
| `internal/cli`                                  | Stdlib `flag` dispatch, approvals, command behavior, human/JSON errors, and exit classes.  |
| `internal/lang/token`                           | Token kinds and byte/line/column spans.                                                    |
| `internal/lang/lexer`                           | UTF-8, comments, quoted/raw strings, escapes, and lexical diagnostics.                     |
| `internal/lang/ast`                             | Clean domain syntax types.                                                                 |
| `internal/lang/parser`                          | Recursive-descent grammar and ordered transactions.                                        |
| `internal/lang/validate`                        | Transaction uniqueness, phase order, argument, hash, and path-shape validation.            |
| `internal/lang/frontend` / `internal/lang/diag` | Source loading boundary and stable diagnostics.                                            |
| `internal/pathcap`                              | Canonical capability roots, `os.Root` mapping, and reserved/escape policy.                 |
| `internal/condition`                            | Safe condition evaluation and streaming file reads.                                        |
| `internal/plan`                                 | Static conflict analysis, exact/deferred plans, effects, warnings, and rollback estimates. |
| `internal/program`                              | Source-order selection, fail-fast orchestration, and skipped results.                      |
| `internal/streamutil`                           | Bounded-buffer copy, contains, SHA-256, and literal replace helpers.                       |
| `internal/fsop`                                 | Real filesystem prepare/apply/verify/inverse primitives and supported object policy.       |
| `internal/journal`                              | Framed append/sync, CRC32C, bounded decode, and semantic replay.                           |
| `internal/state`                                | `.undo` layout, UUIDv7 metadata, lock lifecycle, statuses, and history.                    |
| `internal/txn`                                  | One transaction's durable lifecycle and operation sequencing.                              |
| `internal/recovery`                             | Fresh-process journal replay, reverse rollback, and fail-closed recovery.                  |
| `internal/report`                               | Stable JSON envelope/error/result models.                                                  |
| `marketing`                                     | Static site; no package manifest or external runtime asset.                                |
| `tools/buildproof`                              | Stdlib-only streaming SHA-256 and byte-identity receipt helper.                            |

## Required local toolchain and environment

Source builds require exactly Go **1.27.x**; the verified local toolchain is
`go1.27.0`. Git is useful for source control but is never invoked by the
runtime. No database, Node.js, Python, Docker, package manager, service, cloud
account, or API key is required.

Runtime environment variables: **none**. `NO_COLOR` is an optional convention;
the shipped human output is intentionally ANSI-free.

Optional build/release variables are standard Go controls only:

- `GOTOOLCHAIN=go1.27.0` selects the pinned toolchain;
- `GOPROXY=off` proves network-disabled module resolution;
- `CGO_ENABLED=0` produces the canonical native binary without a CGO runtime;
- `GOOS` and `GOARCH` select cross-build targets.

The transaction state directory is `<transaction-root>/.undo/` and is reserved
from DSL operations. Relative DSL paths resolve against `--root`, or the
invocation working directory when `--root` is omitted. The script location is
independent. External absolute paths require explicit repeatable
`--allow-path` capabilities.

## Exact setup, build, install, and run commands

From a checkout:

```sh
make help
make build
```

The direct canonical build is:

```sh
GOTOOLCHAIN=go1.27.0 GOPROXY=off CGO_ENABLED=0 \
  go build -trimpath -buildvcs=false -o undo ./cmd/undo
./undo version
```

The one-command judge build may omit the environment selectors:

```sh
go build -trimpath -buildvcs=false -o undo ./cmd/undo
```

For local convenience installation on macOS/Linux, copy an existing binary or
build the checkout and install it with:

```sh
./install.sh ./undo "$HOME/.local/bin"
```

On Windows PowerShell:

```powershell
.\install.ps1 -SourceBinary .\undo.exe
```

If the source build needs a compiler, either installer downloads the official
Go 1.27.0 archive from `go.dev`, verifies its pinned SHA-256 checksum, and
installs it under a user-local UndoLang toolchain directory. An existing
compatible Go 1.27.x is reused. Pass `--no-install-go` to `install.sh` or
`-NoInstallGo` to `install.ps1` to require an entirely offline/local-only
install. A prebuilt native binary can simply be run directly and never needs
Go.

Human flow:

```sh
./undo check migration.undo --root /target
./undo plan migration.undo --root /target
./undo run migration.undo --root /target
./undo history --root /target
./undo inspect TXID --root /target --json
```

Interactive `run` asks for confirmation. Automation must pass `--yes`; JSON
does not grant approval:

```sh
./undo run migration.undo --root /target --yes --json
```

If an execution is interrupted, use a fresh process:

```sh
./undo recover --root /target --yes --json
```

Do not delete `.undo` to bypass recovery.

## Complete human end-to-end flow

1. Build `undo` with the canonical command above.
2. Create or choose a fixture root and a `.undo` file containing one or more
   named transactions.
3. Run `check`; it validates the entire source and makes no target mutation.
4. Run `plan`; review paths, effects, destructive operations, readiness, and
   rollback estimate. A whole-program plan marks later state-sensitive work as
   deferred.
5. Run with interactive confirmation or explicit `--yes`. The whole file runs
   in source order; each transaction is freshly planned immediately before it
   starts.
6. Confirm the resulting files and use `history`/`inspect` for the local audit
   record.
7. For a real interruption, kill the running process externally, observe the
   unresolved `.undo` state, then run `recover --yes` from a newly started
   process. Recovery rolls back only the interrupted transaction; earlier
   committed transactions remain committed.
8. For the timed version of this flow, use
   [`DEMO_RUNBOOK.md`](DEMO_RUNBOOK.md).
9. For a beginner-friendly copy/paste version of this flow, use
   [`TESTING.md`](../TESTING.md).

## Complete agent usage flow

An agent that has never seen the repository can use the binary as follows:

```sh
./undo capabilities --json
./undo schema --json
./undo check change.undo --root /workspace --json
./undo plan change.undo --root /workspace --json
# Obtain approval from the controlling human/workflow.
./undo run change.undo --root /workspace --yes --json
```

The agent should read `api_version`, `ok`, stable error `code`/`message`,
transaction readiness, destructive effects, and rollback estimates. For a
multi-transaction plan, only the first transaction is exact; later stateful
checks are deferred. A whole-program JSON result includes transaction IDs and
`skipped` entries after failure. If the result is `recovery_required`, the agent
must stop new mutation and run:

```sh
./undo recover --root /workspace --yes --json
```

The agent must not infer approval from JSON and must not delete retained
`.undo` backups or journals after a recovery failure/corruption report.

## Commands and results actually verified

Fresh evidence from this checkout on macOS arm64, Go 1.27.0:

| Command                                                                                           | Result                                                                                                       |
| ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `GOPROXY=off GOTOOLCHAIN=go1.27.0 go test ./...`                                                  | PASS                                                                                                         |
| `GOPROXY=off GOTOOLCHAIN=go1.27.0 go vet ./...`                                                   | PASS                                                                                                         |
| `GOPROXY=off GOTOOLCHAIN=go1.27.0 go test -race ./...`                                            | PASS                                                                                                         |
| `UNDOLANG_LARGE_TREE=1 ... go test ./internal/plan -run '^TestStressPlan100KEntryTree$' -count=1` | PASS, 23.589s                                                                                                |
| `UNDOLANG_STRESS=1 ... go test ./internal/fsop -run '^TestStressCopy256MiB$' -count=1`            | PASS, 2.260s                                                                                                 |
| lexer/parser/journal `-fuzz` runs, 5s each                                                        | PASS; 142,471 / 73,804 / 279,128 executions reported                                                         |
| `go test ./internal/cli -run '^TestRealProcessCrashRecoveryMatrix$' -count=1`                     | PASS, 9 real kill/recover checkpoints, 5.767s                                                                |
| `examples/fs.undo` with real `check`/`plan` fixtures                                              | PASS; one program with selectable success and failure transactions                                           |
| `./scripts/deps-proof.sh`                                                                         | PASS; offline tests and build                                                                                |
| `make reproducible-build` (`./scripts/repro-build.sh`)                                            | PASS; labeled identical A/B SHA-256; reuses installer toolchain when needed                                  |
| `./scripts/release.sh`                                                                            | PASS; five cross-builds                                                                                      |
| `GOTOOLCHAIN=go1.27.0 GOPROXY=off go list -m all`                                                 | one line: main module only                                                                                   |
| `TESTING.md` temporary-root flow                                                                  | PASS; check, plan, whole-file run, selected run, JSON commands, history/inspect, and real assertion rollback |

The active fuzz commands were:

```sh
GOPROXY=off GOTOOLCHAIN=go1.27.0 go test ./internal/lang/lexer -run '^$' -fuzz '^FuzzLexNeverPanics$' -fuzztime 5s
GOPROXY=off GOTOOLCHAIN=go1.27.0 go test ./internal/lang/parser -run '^$' -fuzz '^FuzzParseNeverPanics$' -fuzztime 5s
GOPROXY=off GOTOOLCHAIN=go1.27.0 go test ./internal/journal -run '^$' -fuzz '^FuzzDecodeNeverPanics$' -fuzztime 5s
```

The five example fixture preparations and `check`/`plan` commands all exited
zero. Documentation tests also parse every repository example and the public
UndoLang snippets used in README/docs/marketing, verify local marketing links,
reject external runtime assets, and check documented command help.

## Platform evidence

Behavior tested on a real **macOS arm64** host:

- full tests, vet, race detector, lexer/parser/journal fuzzing;
- all six operations and inverse behavior;
- path/capability and symlink policy;
- journal corruption/torn-tail handling;
- real subprocess kill/recovery matrix;
- 100,000-entry planner and 256 MiB streaming stress tests;
- restrictive permissions, FIFO rejection, and hard-link limitation behavior.

Cross-build-only targets, all with `CGO_ENABLED=0` and Go 1.27.0:

- Linux amd64;
- Linux arm64;
- macOS amd64;
- macOS arm64 (the release binary cross-build also matches the tested host);
- Windows amd64.

Linux and Windows behavior has not been executed on a real host in this
environment. Windows PowerShell execution, Windows rename/open-handle and
reparse-point behavior, Linux filesystem durability, actual cross-device
`EXDEV`, and real ENOSPC during journal sync/rollback remain untested here.

## Acceptance and limitations

The PRD acceptance criteria were checked individually:

|   # | Criterion                                                        | Evidence/status                                                                                 |
| --: | ---------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
|   1 | Valid `.undo` parses from any filesystem location                | PASS — frontend and script-location/root integration tests.                                     |
|   2 | Invalid syntax has line/column and stable error code             | PASS — lexer/parser diagnostics tests.                                                          |
|   3 | `check` does not mutate targets                                  | PASS — CLI snapshot tests.                                                                      |
|   4 | `plan` does not mutate and describes effects                     | PASS — planner/CLI snapshot and JSON tests.                                                     |
|   5 | Relative paths use transaction root                              | PASS — path capability tests.                                                                   |
|   6 | Absolute paths inside root work                                  | PASS — path capability tests.                                                                   |
|   7 | External absolute paths require capability                       | PASS — denied/allowed path tests.                                                               |
|   8 | `..` and symlink escapes are rejected                            | PASS — traversal and symlink race-policy tests.                                                 |
|   9 | All six mutations work on real filesystems                       | PASS — `internal/fsop` integration tests.                                                       |
|  10 | Preconditions prevent mutation                                   | PASS — planner/transaction tests.                                                               |
|  11 | Failed postconditions roll back                                  | PASS — program/transaction integration tests.                                                   |
|  12 | Mid-transaction operation failure rolls back                     | PASS — operation/program failure tests.                                                         |
|  13 | Real process kill leaves recoverable state                       | PASS — nine real kill checkpoints.                                                              |
|  14 | `recover` restores prior state                                   | PASS — fresh-process crash/recovery matrix.                                                     |
|  15 | Corrupt non-tail journal fails closed                            | PASS — CRC/sequence/replay tests.                                                               |
|  16 | Torn final journal record is handled safely                      | PASS — torn-tail decoder/recovery tests.                                                        |
|  17 | Large-file operations use bounded memory                         | PASS — streaming implementation and 256 MiB stress test.                                        |
|  18 | Human and JSON CLIs work                                         | PASS — CLI and compiled-binary contract tests.                                                  |
|  19 | Agent self-description works without project docs                | PASS — capabilities/schema/agent-guide tests.                                                   |
|  20 | Tests pass with `GOPROXY=off`                                    | PASS — final offline test gate.                                                                 |
|  21 | Module list contains only the main module                        | PASS — current `go list -m all` receipt.                                                        |
|  22 | Production binary shells out to no executable                    | PASS — production imports are stdlib/internal only; shelling out appears only in tests/tooling. |
|  23 | Two canonical builds are byte-identical                          | PASS — current reproducibility receipt.                                                         |
|  24 | `STDLIB.md` has at least 10 real substitutions                   | PASS — 15 ledger rows.                                                                          |
|  25 | Static marketing/docs site has no third-party runtime dependency | PASS — asset/link/dependency tests.                                                             |
|  26 | README states unsupported/limited semantics honestly             | PASS — build, Track F rationale, guarantees, platform limits, and safety limits are documented. |

Result: **26/26 repository acceptance criteria PASS.**

The remaining limitations are intentional v0.1 boundaries:

- no isolation or atomic visibility across multiple filesystem mutations;
- rename and directory-sync durability vary by OS/filesystem;
- one active transaction per primary root; overlapping external capabilities
  can race;
- recovery handles the unresolved transaction and does not resume later program
  entries automatically;
- symlink copy and special-file mutation are rejected;
- basic modes are preserved where supported, but ownership, ACLs, xattrs,
  timestamps, sparse allocation, resource forks, alternate streams, and
  hard-link identity are not guaranteed.

No limitation should block the hackathon submission. The only submission
blockers remaining are external actions: publish the public GitHub repository,
optionally upload the cross-built release artifacts/checksums, record/publish
the real five-minute demo, and complete the hackathon submission form.
