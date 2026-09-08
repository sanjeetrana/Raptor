# UndoLang Technical Specification

**Target implementation:** Go 1.27, standard library only

**Architecture goal:** production-grade local filesystem transaction runtime within hackathon scope

---

## 1. System architecture

```text
.undo source
    |
    v
Lexer -> Parser -> AST -> Semantic Validator
                              |
                              v
                    Path/Capability Resolver
                              |
                              v
                         Program Planner / Selector
                    /              |              \
          static program view   selected tx   deferred txs
                    \              |              /
                              v
                    Sequential Program Runner
                              |
                     fresh transaction plan
                    /         |        \
             Preconditions  Effects  Backup estimate
                    \         |        /
                              v
                     Transaction Engine
                   /        |          \
             Journal    FS Executor   Verifier
                 |            |          |
                 +------ Rollback <------+
                              |
                              v
                         Recovery
```

Key separation rule: parser/validator/planner code must not directly mutate target filesystem state. Mutation begins only inside transaction execution after successful preflight.

---

## 2. Recommended packages

All imports must be standard library or same-module packages.

```text
cmd/undo                  CLI entrypoint
internal/cli              subcommand parsing, human/JSON output, exit codes
internal/lang/token       tokens and source spans
internal/lang/lexer       UTF-8 lexer
internal/lang/ast         AST/domain syntax types
internal/lang/parser      recursive-descent parser
internal/lang/validate    DSL phase and semantic validation
internal/pathcap          transaction root and allowed-root capability mapping
internal/plan             immutable program/transaction plans and conflict analysis
internal/program          transaction selection + sequential fail-fast whole-program runner
internal/condition        pre/postcondition evaluation
internal/fsop             real filesystem operations + inverse metadata
internal/streamutil       bounded-memory copy/search/replace helpers
internal/journal          framed append-only durable journal
internal/txn              transaction state machine/orchestration
internal/recovery         journal replay and rollback recovery
internal/state            state directory, locks, history metadata
internal/report           human + versioned JSON result models
internal/buildinfo        version/schema constants only
```

Avoid needless interfaces. Create interfaces only where they express stable domain boundaries; do not build a mock-heavy abstraction maze.

---

## 3. Standard-library primitives

Expected important packages include:

- `flag`
- `os`
- `io`
- `io/fs`
- `bufio`
- `path/filepath`
- `strings`
- `bytes`
- `unicode`, `unicode/utf8`
- `errors`
- `fmt`
- `encoding/binary`
- `encoding/hex`
- `encoding/json/v2` (Go 1.27) or classic `encoding/json` only if v2 creates unnecessary compatibility friction
- `crypto/sha256`
- `hash/crc32`
- `uuid` (Go 1.27)
- `time`
- `sync` only where justified
- `runtime`
- `testing`

Use `os.OpenRoot` / `os.Root` for traversal-resistant operations inside declared capability roots. `os.Root` was introduced in Go 1.24 and expanded in Go 1.25; the project pins Go 1.27.

---

## 4. Path capability model

### 4.1 Effective roots

At runtime build a set of capability roots:

1. primary transaction root;
2. each explicit `--allow-path DIRECTORY` root.

Each root is canonicalized and opened with `os.OpenRoot`.

### 4.2 Mapping a DSL path

For every DSL path:

1. Determine whether lexical path is absolute.
2. If relative, bind to primary transaction root.
3. If absolute, determine the most specific capability root containing it.
4. Convert absolute path to a relative path beneath that root.
5. Reject if no declared capability contains it.
6. Use `os.Root` methods for actual operations to prevent traversal/symlink escape.

`filepath.Rel` may help with lexical containment, but **must not be the sole security barrier**; `os.Root` is the execution boundary.

### 4.3 Root default

- Default root = absolute current working directory captured at process start.
- `--root` overrides.
- `.undo` script location is independent.

### 4.4 Absolute path policy

- absolute path inside transaction root: permitted;
- outside transaction root: denied unless covered by `--allow-path`;
- `--allow-path` entries should be existing directories at preflight so `os.OpenRoot` can bind them safely.

### 4.5 Reserved runtime state path

Default state directory:

```text
<transaction-root>/.undo/
```

Required layout:

```text
.undo/
  active.lock
  transactions/
    <uuid>/
      meta.json
      journal.bin
      backup/
      status
  history/
```

The planner rejects user operations targeting `.undo` or any descendant under the primary root with `E_RESERVED_PATH`.

If a future `--state-dir` is added, it must be an explicit advanced feature. Do not add it during core phases unless required by a real blocker.

---

## 5. Program model and selection

A parsed `.undo` file contains one or more uniquely named transactions in source order.

Public selection semantics:

- `undo run FILE --transaction NAME`: execute exactly the named transaction;
- `undo run FILE`: execute all transactions in source order;
- same selection behavior applies to `plan` where meaningful.

The entire source is lexed, parsed, and semantically validated before any target mutation, even when one transaction is selected.

Whole-program execution is an orchestration convenience, **not a super-transaction**. Every started transaction gets its own UUID, journal directory, backups, lock ownership while active, and terminal state. The runner is sequential and fail-fast. A later failure never causes automatic rollback of an earlier `COMMITTED` transaction.

Before each transaction begins, the runner performs a fresh state-sensitive plan/precondition evaluation against the filesystem as it exists after prior commits.

No automatic whole-program resume is promised in v0.1 after failure/crash. After recovery, remaining work must be selected explicitly or rerun only when authored semantics make that safe.

---

## 6. Transaction identity and states

Use Go 1.27 standard-library UUID, preferably UUIDv7 for sortable transaction identifiers.

Required transaction states:

```text
PLANNED
PREPARED
RUNNING
VERIFYING
COMMITTING
COMMITTED
ROLLING_BACK
ROLLED_BACK
RECOVERY_REQUIRED
RECOVERY_FAILED
```

Persist state transitions. In-memory state alone is never authoritative after a crash.

---

## 7. Single-active-transaction rule

Hackathon MVP supports one active transaction per primary root.

Acquire `.undo/active.lock` using `os.OpenFile(..., O_CREATE|O_EXCL, 0600)`.

Lock content should minimally contain:

- transaction ID,
- PID (diagnostic only; do not rely solely on PID liveness),
- start timestamp,
- script hash/name.

If lock exists:

- inspect referenced transaction status/journal;
- if transaction is unresolved, return `E_RECOVERY_REQUIRED`;
- do not silently delete a stale-looking lock based only on PID.

After successful commit/rollback and durable final status, remove lock.

Known limitation: separate transaction roots with overlapping external `--allow-path` trees can race. Document this. Do not claim global filesystem isolation.

---

## 8. Plan model

Planner input: validated AST + capability roots + transaction selection.

Planning has two levels:

- **Transaction plan:** exact current-state preflight for one transaction.
- **Program plan:** ordered summaries for all transactions. For a multi-transaction whole-program plan, later state-sensitive checks are `deferred_until_execution` because prior transactions may change the filesystem. Do not simulate success or expose a misleading program-wide `safe_to_execute`.

During `run`, a fresh exact transaction plan is created immediately before each transaction starts.

Planner output should be immutable and contain resolved, typed effects.

Recommended shape:

```go
type ProgramPlan struct {
    APIVersion   string
    ScriptPath   string
    ScriptSHA256 string
    Mode         string // "all" or "selected"
    SelectedName string
    Transactions []TransactionPlanSummary
    SafeToStart  bool
}

type Plan struct {
    APIVersion    string
    TransactionID uuid.UUID
    Name          string
    ScriptPath    string
    ScriptSHA256  string
    Root          string
    AllowedRoots  []string
    Preconditions []PlannedCondition
    Operations    []PlannedOperation
    Assertions    []PlannedCondition
    Summary       PlanSummary
    Warnings      []Warning
    SafeToExecute bool
}
```

The planner detects before mutation:

- missing required sources;
- unexpected destinations;
- destination collisions;
- source/destination aliasing;
- copying/moving a directory into itself/descendant;
- operations touching reserved state path;
- capability escapes;
- operation ordering conflicts (e.g., delete path then use it later);
- multiple writes to same path when semantics would be ambiguous;
- unsupported file types;
- invalid overwrite behavior.

Do not mutate simply to discover whether a plan is legal.

---

## 9. Journal format

### 8.1 Goals

Journal must be:

- append-only during active transaction;
- incrementally durable;
- detect torn/incomplete final records;
- detect checksum corruption;
- replayable without external database;
- self-versioning;
- not store whole target file contents.

### 8.2 Framed record proposal

Use binary framing with JSON v2 payloads for inspectability and typed evolution.

Example frame:

```text
magic        4 bytes  "UNDO"
version      u16      journal format version
record_type  u16
sequence     u64
payload_len  u32
payload      N bytes  canonical-enough JSON for our own decoder; exact byte preservation not externally promised
crc32c       u32      checksum over header fields after magic + payload
```

Use `hash/crc32` Castagnoli table.

Do not rely on CRC as a security primitive; it is corruption/torn-write detection only.

### 8.3 Record classes

At minimum:

- `TX_BEGIN`
- `TX_STATE`
- `OP_PREPARED`
- `OP_APPLIED`
- `ASSERT_RESULT`
- `ROLLBACK_PREPARED`
- `ROLLBACK_APPLIED`
- `TX_COMMIT`
- `TX_ROLLBACK_COMPLETE`

Each operation record references operation ID and inverse/backup metadata.

### 8.4 Sync discipline

When a journal record is relied on to decide recovery behavior after a crash:

1. append full frame;
2. call `File.Sync()`;
3. only then advance to filesystem mutation/state that assumes the record is durable.

The exact ordering per operation is below.

### 8.5 Replay corruption policy

- Incomplete bytes at EOF that cannot form a complete frame: treat as a possible torn tail; preserve diagnostics, stop at last valid record, and allow recovery based on preceding durable state only if no ambiguity exists.
- Checksum failure on a complete/non-tail record: `E_JOURNAL_CORRUPT`; fail closed; do not guess.
- Sequence discontinuity: corruption error.
- Unknown future record type/version: fail closed unless explicitly forward-compatible.

Never silently skip arbitrary bad records.

---

## 10. Backup model

Backups live under:

```text
.undo/transactions/<txid>/backup/<operation-id>/...
```

Directory mode: `0700` where supported.

Principles:

- backup before destructive overwrite/delete;
- backup content via bounded-memory streaming;
- do not put full content in journal;
- record SHA-256 for important copied backup data to detect incomplete/corrupt backup;
- preserve basic mode bits where portable;
- preserve symlink metadata according to explicit policy;
- ACLs/xattrs/ownership are not universally portable in Go stdlib and must be listed as limitations;
- if a backup itself cannot be made durably enough for promised rollback, fail before destructive mutation.

For performance, same-filesystem rename-to-stash may be used for `delete` if it is demonstrably safe and recovery metadata is durable first. A simple copy-then-delete implementation is acceptable if correct and documented, but must stream and report estimated backup cost.

---

## 11. Per-operation execution protocol

Use operation IDs ordered by plan index.

Generic pattern:

1. Validate current state still matches plan assumptions immediately before operation.
2. Prepare any required backup/temp output.
3. Sync backup/temp contents.
4. Append `OP_PREPARED` with inverse metadata; sync journal.
5. Apply mutation.
6. Sync changed file(s) where applicable; sync containing directory on Unix where implemented/appropriate.
7. Append `OP_APPLIED`; sync journal.

If step 5/6 errors after state may have changed, transaction enters rollback/recovery logic using the prepared metadata and actual filesystem inspection.

### 10.1 Directory sync

Go does not offer one uniform promise across all platforms. On Unix, opening a directory and `Sync()` may be used where supported to improve rename/dentry durability. On platforms where this is unsupported, document the limit. Do not claim stronger guarantees than tested.

### 10.2 Rename caveat

Go's `os.Rename` documentation explicitly notes that even within the same directory, rename is not atomic on non-Unix platforms. Therefore UndoLang must describe atomicity/durability by platform and focus its portable promise on recoverable state plus verification.

---

## 12. Real filesystem operation design

### 11.1 File copying

- open source read-only under capability root;
- create temporary destination safely;
- use `io.CopyBuffer` with bounded reusable buffer;
- compute SHA-256 while copying using `io.MultiWriter` if verification needed;
- `Sync()` temp file;
- apply mode using file handle where possible;
- close;
- rename/replace into final destination;
- never invoke `cp`, `rsync`, or external utilities.

### 11.2 Directory copy

- use `fs.WalkDir`/`filepath.WalkDir` or a root-safe recursive traversal that never follows symlink directories implicitly;
- create directories top-down;
- copy files streaming;
- apply directory modes after children if necessary;
- deterministic traversal ordering: stdlib walker ordering or explicit sorting where needed and documented;
- record created entries for rollback without retaining file data in memory.

### 11.3 Streaming contains

Implement literal byte subsequence search with chunk carry of at most `len(needle)-1`. Empty needle is invalid for this condition or explicitly true; choose one and test. Recommended: reject empty needle as semantic error to avoid useless conditions.

### 11.4 Streaming replace

Implement all non-overlapping literal replacements with bounded buffer/carry. Do not use regex. Ensure patterns spanning chunk boundaries work. Write result to temp file; original remains untouched until complete result is durable and original backup is prepared.

### 11.5 Hashing

Use `crypto/sha256`, stream via `io.Copy` into hash, encode with `encoding/hex`.

---

## 13. Symlink policy

Symlink behavior is security-sensitive.

Recommended v1 policy:

- path traversal for actual target operations is constrained by `os.Root`;
- `delete` on a symlink removes the link itself, not recursively its target;
- `move` on a symlink moves the link entry itself where root-safe rename semantics permit;
- `copy` of symlink must either:
  - safely recreate only links whose target remains within allowed capability policy, **or**
  - be rejected in v1 with `E_UNSUPPORTED_SYMLINK_COPY`.

Prefer rejecting symlink copy if implementation cannot prove the policy correctly in time. Never silently dereference an external symlink.

Hard links are treated as independent file content in v1; link identity preservation is not promised.

---

## 14. Preconditions and assertions

Conditions use safe resolved paths and real filesystem reads.

Preconditions are evaluated twice where TOCTOU matters:

- once during `plan`/preflight for user visibility;
- execution re-validates operation assumptions/preconditions after lock acquisition immediately before mutation begins.

Do not assume a plan generated minutes earlier still reflects filesystem state.

Postconditions run after all mutations. Any failure initiates rollback.

---

## 15. Rollback algorithm

Rollback examines journal replay state, not only in-memory completed operation list.

1. Transition/persist `ROLLING_BACK`.
2. Determine definitely applied operations from valid journal records.
3. Iterate applied operations in reverse order.
4. Before each inverse, append/sync `ROLLBACK_PREPARED`.
5. Apply inverse using backup/inverse metadata.
6. Verify expected restored state where practical (existence/hash).
7. Append/sync `ROLLBACK_APPLIED`.
8. After all inverses succeed, persist `ROLLED_BACK` and final journal record.
9. Remove active lock only after final status is durable.

If any inverse cannot safely complete:

- stop destructive guessing;
- persist `RECOVERY_FAILED` if possible;
- retain backups/journal;
- return specific error with transaction ID and inspection command.

---

## 16. Recovery algorithm

`undo recover --root X`:

1. Discover active/incomplete transaction metadata.
2. Open journal read-only first.
3. Validate frame sequence/checksums.
4. Determine last valid durable state.
5. Reject ambiguous/corrupt mid-journal data.
6. If transaction already committed/rolled back, reconcile stale lock and return status without replaying mutation.
7. If incomplete, set/persist recovery state.
8. Execute rollback using journal-defined applied operations.
9. Verify rollback.
10. finalize status and lock cleanup.

Recovery is idempotent: if recovery itself is interrupted, running `recover` again must resume safely based on rollback journal records.

---

## 17. CLI architecture

Use stdlib `flag.FlagSet` per subcommand; do not use Cobra.

Root dispatch is a small explicit switch on `os.Args[1]`.

Commands:

```text
undo version
undo check <file> [--root ...] [--allow-path ...] [--json]
undo plan <file> [--root ...] [--allow-path ...] [--json]
undo run <file> [--root ...] [--allow-path ...] [--yes] [--json]
undo recover [--root ...] [--json]
undo history [--root ...] [--json]
undo inspect <txid> [--root ...] [--json]
undo capabilities [--json]
undo schema [--json]
undo agent-guide
```

Because `flag` does not natively provide repeatable string slices ergonomically, implement a small stdlib-only `flag.Value` type for `--allow-path`.

---

## 18. JSON API

All machine-readable structures include:

```json
{
  "api_version": "undo-cli/1",
  "ok": true
}
```

Errors:

```json
{
  "api_version": "undo-cli/1",
  "ok": false,
  "error": {
    "code": "E_PATH_ESCAPE",
    "message": "path escapes declared capability root",
    "path": "../../secrets",
    "root": "/home/user/project"
  }
}
```

Never mix progress prose into JSON stdout. If progress is necessary, either suppress it in JSON mode or send structured events; for MVP, suppress non-result progress and use stderr only for fatal startup diagnostics that cannot be encoded.

---

### Multi-transaction CLI behavior

- `check FILE` always validates the whole program and reports ordered transaction names.
- `plan FILE --transaction NAME` returns an exact plan for one transaction.
- `plan FILE` with multiple transactions returns a program plan with later state-sensitive entries clearly deferred.
- `run FILE --transaction NAME` executes one transaction.
- `run FILE` executes all transactions sequentially in source order.
- JSON whole-program run output contains one result entry per declared transaction; entries not reached after a failure are `skipped`.
- In interactive mode, approval must cover the declared whole-program run, while each transaction is still freshly validated/planned immediately before execution. `--yes` is still required for non-interactive mutation.

## 19. Error code taxonomy

Required stable codes include at least:

```text
E_USAGE
E_IO
E_UTF8
E_LEX
E_SYNTAX
E_UNKNOWN_INSTRUCTION
E_SEMANTIC
E_PHASE_ORDER
E_PATH_INVALID
E_PATH_ESCAPE
E_ABSOLUTE_DENIED
E_RESERVED_PATH
E_SOURCE_MISSING
E_DESTINATION_EXISTS
E_CONFLICT
E_UNSUPPORTED_FILE_TYPE
E_UNSUPPORTED_SYMLINK_COPY
E_PRECONDITION_FAILED
E_POSTCONDITION_FAILED
E_HASH_MISMATCH
E_REPLACE_PATTERN_NOT_FOUND
E_TRANSACTION_ACTIVE
E_RECOVERY_REQUIRED
E_JOURNAL_CORRUPT
E_ROLLBACK_FAILED
E_RECOVERY_FAILED
E_PERMISSION
E_NO_SPACE
```

Map to documented process exit-code classes rather than unique exit code for every error.

Suggested exit classes:

- `0` success
- `1` usage/syntax/semantic validation
- `2` precondition/plan not executable
- `3` permission/path policy/conflict
- `4` transaction failed, rollback succeeded
- `5` recovery required/incomplete transaction
- `6` rollback/recovery/journal integrity failure
- `7` internal invariant failure

---

## 20. Human output

Human output should answer:

- what transaction is this?
- what root/capabilities are active?
- what will change?
- what is destructive?
- how much rollback data is estimated?
- did it commit, rollback, or require recovery?
- what exact command should user run next when needed?

Honor `NO_COLOR`; use ANSI only when stdout/stderr is appropriate TTY and color enabled. Since Go stdlib lacks a first-class cross-platform isatty helper with full ergonomics, keep color optional/minimal; `--no-color` must always work.

---

## 21. History/inspection

`history` is local metadata, not a database. Read completed transaction metadata from `.undo/transactions` / history index.

Do not invent a custom database for this feature.

`inspect` should show:

- transaction metadata;
- final status;
- operation list;
- journal validation summary;
- warnings/limitations;
- backup retained/cleaned status.

Hackathon core does not promise arbitrary post-commit rollback after subsequent external filesystem changes.

---

## 22. Backup retention

Core safety requires backups through rollback/commit finalization.

Recommended hackathon policy:

- on successful `COMMITTED`, remove bulky backups after final commit record/status is durable;
- retain compact metadata/journal needed for history/audit;
- on `ROLLED_BACK`, clean backups only after restored-state verification and final rollback status;
- on `RECOVERY_FAILED` or journal corruption, retain all backups.

This keeps disk usage bounded and avoids pretending post-commit undo is safe after arbitrary later changes.

---

## 23. Concurrency model

- one active transaction per primary root;
- mutations are sequential and ordered;
- read-only commands may run concurrently but must recognize active state and avoid misreporting;
- no parallel mutation worker pool in v1;
- internal goroutines only if they simplify non-mutating work without weakening determinism;
- external applications may observe intermediate filesystem states: UndoLang does not claim isolation.

---

## 24. Cross-platform behavior

### Linux/macOS

Strongest target for rename/fsync behavior; implement directory sync if tested and portable under Unix build files.

### Windows

- `os.Root` handles Windows path/device restrictions;
- open handles may block replacement/rename;
- Go documentation does not promise rename atomicity;
- use real Windows CI/manual tests if available;
- on operation failure, rollback rather than pretending atomic replacement succeeded.

### Unsupported metadata

Document lack/limits for:

- ACL preservation,
- extended attributes,
- ownership portability,
- hard-link identity,
- sparse-file sparseness,
- special devices/FIFOs/sockets.

Reject special file mutation unless explicitly implemented and tested.

---

## 25. Build and dependency invariants

`go.mod`:

```go
module <chosen-public-module-path>

go 1.27
```

No `require`.

Hard gates:

```bash
go test ./...
go vet ./...
go list -m all
GOPROXY=off go test ./...
GOPROXY=off go build -trimpath -buildvcs=false -o dist/undo ./cmd/undo
```

`go list -m all` must list only the main module.

Do not import `golang.org/x/...`.

---

## 26. Reproducible build

Canonical build should use pinned Go 1.27 and remove local-path/VCS variability:

```bash
CGO_ENABLED=0 go build -trimpath -buildvcs=false -o dist/undo ./cmd/undo
```

If same-source same-toolchain hashes are not identical, investigate build metadata rather than hand-wave. If necessary and validated, consider linker build-ID controls; do not add flags blindly. The final script must build twice and compare SHA-256.

Version embedding must not inject current timestamp, dirty working directory paths, random IDs, or nondeterministic metadata into the binary.

---

## 27. Production observability

No telemetry/network logging.

Use local structured/human logs only as needed. `log/slog` is permitted but do not over-engineer logging. Transaction history/journal is the primary audit evidence.

Sensitive content must not appear in logs.

---

## 28. Internal invariants

Treat violation as internal error and stop:

- an applied operation has no durable prepared record;
- operation sequence IDs are non-monotonic;
- rollback references unknown operation;
- a capability-relative resolved path escapes root;
- state directory appears in a planned mutation;
- transaction enters commit with a failed assertion;
- lock removed before final state durability;
- journal decoder silently skips bad frame.

---

## 29. Definition of technically complete

The system is technically complete only when:

- parser and validator are independent from executor;
- path policy uses traversal-resistant root APIs;
- all six operations are real and reversible for supported file types;
- journal survives real process kill;
- recovery is driven by durable journal state;
- failed assertion causes real rollback;
- large files are streamed;
- JSON contract is stable and tested;
- zero-dependency proof passes with network-disabled Go module resolution;
- two canonical builds hash identically on same machine/toolchain;
- documented limitations match actual code.
