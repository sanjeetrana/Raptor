# UndoLang Program and Transaction Execution Model

**Status:** normative for v0.1

This document exists to remove ambiguity between a `.undo` **program** and an UndoLang **transaction**.

## 1. Core distinction

> **A `.undo` file is a filesystem program. A transaction is the atomic/recoverable execution unit inside it.**

A source file contains **one or more named transactions**:

```undo
transaction "prepare" {
    mkdir "backup"
    copy "config.json" -> "backup/config.json"
}

transaction "upgrade" {
    move "plugins" -> "extensions"
    replace "config.json" "schema=1" -> "schema=2"
    write "VERSION" = "2"
}

transaction "cleanup" {
    delete "legacy/"
}
```

Transaction names must be non-empty and unique within the file.

## 2. CLI selection semantics

### Run one named transaction

```bash
undo run migration.undo --transaction upgrade
```

Only `upgrade` is considered for execution. The **entire file is still lexed, parsed, and semantically validated first**, so malformed source elsewhere in the same program is not silently ignored.

### Run the whole program

```bash
undo run migration.undo
```

If the file contains one transaction, that transaction runs.

If the file contains multiple transactions, all transactions run **in source order**:

```text
prepare -> upgrade -> cleanup
```

Each transaction receives its own runtime transaction ID, journal, backups, state machine, commit/rollback result, and history entry.

## 3. Atomicity boundary

Transactions are independent recoverable units. A whole `.undo` program is **not** an implicit super-transaction.

Example:

```text
prepare  -> COMMITTED
upgrade  -> COMMITTED
cleanup  -> FAILS -> ROLLED_BACK
```

Final result:

- `prepare` remains committed;
- `upgrade` remains committed;
- `cleanup` is restored to its pre-`cleanup` state;
- execution stops;
- no later transaction is started.

UndoLang must never automatically roll back already committed earlier transactions just because a later transaction fails.

If the author needs several operations to succeed or roll back together, those operations belong inside **one transaction**.

## 4. Fail-fast whole-program behavior

Whole-program execution is sequential and fail-fast.

For every selected transaction, UndoLang performs:

```text
FRESH PREFLIGHT
    -> REQUIRE PRECONDITIONS
    -> JOURNAL INITIALIZATION
    -> APPLY OPERATIONS
    -> ASSERT POSTCONDITIONS
    -> COMMIT
```

Then, and only then, it moves to the next transaction.

If a transaction:

- fails preflight or `require`: it performs no mutation for that transaction and program execution stops;
- encounters a real filesystem/I/O/permission/disk-space/verification error while mutating: that transaction rolls back and program execution stops;
- fails an `assert`: that transaction rolls back and program execution stops;
- is interrupted by process/machine failure: its durable journal becomes the recovery authority and no later transaction starts.

A transaction failure is **not limited to failed `assert` statements**. Assertions are semantic postconditions; real operation failures are detected directly from the filesystem/runtime and also trigger rollback.

## 5. Recovery ownership

The `.undo` author defines **forward intent** and optional correctness conditions. The author does **not** normally write rollback code.

> **UndoLang derives, persists, and executes recovery automatically from the actual pre-mutation state and journaled operation state.**

Every mutating primitive has runtime-owned semantics for:

- preflight;
- prior-state capture;
- durable preparation;
- application;
- operation-level verification;
- rollback/recovery;
- cleanup after safe finalization.

For example, `write "VERSION" = "2"` may mean “restore the previous bytes/mode” on rollback if `VERSION` existed, or “remove the created file” if it did not. That inverse is state-dependent, so it belongs to the runtime rather than the script author.

Recovery itself must be resumable. If the process dies while rolling back, a future `undo recover` continues from durable rollback records instead of restarting blindly.

## 6. Planning semantics for multi-transaction programs

The entire program is always parsed and semantically validated before target mutation begins.

State-sensitive planning is different: transaction 2 may depend on files created or changed by transaction 1. `undo plan FILE` must not pretend it knows that future state without performing mutations.

Therefore:

### `undo plan FILE --transaction NAME`

Produces an **exact current-state plan** for the selected transaction against the current filesystem.

### `undo plan FILE` with one transaction

Produces the normal exact current-state transaction plan.

### `undo plan FILE` with multiple transactions

Produces a **program plan**:

- source order and transaction names;
- all syntax/semantic results;
- static path/capability validation that is knowable without prior mutations;
- declared effects and destructive classifications;
- an exact current-state preflight for the first transaction;
- later transactions clearly marked `deferred_until_execution` for state-sensitive checks that may depend on earlier commits.

During `undo run FILE`, each transaction receives a fresh exact plan immediately before that transaction mutates anything.

Human and JSON output must distinguish `ready`, `deferred`, `committed`, `rolled_back`, `failed_preflight`, `recovery_required`, and `skipped` where applicable. Do not expose a misleading single program-wide `safe_to_execute=true` when later transactions are deferred.

## 7. Preconditions and postconditions

Within each transaction the phase order remains strict:

```text
require* -> mutation* -> assert*
```

- `require` verifies assumptions **before** that transaction mutates target state.
- operation errors detect mechanical/runtime failure automatically.
- operation-level verification detects an operation that did not produce its defined result.
- `assert` verifies semantic final-state invariants after all mutations and before commit.

`assert` is valuable, but it is not the only failure detector and is not mandatory for every transaction. A transaction with no assertions can still fail and roll back on real operation errors.

## 8. Rerun/resume semantics

v0.1 does **not** promise automatic resumption of a whole multi-transaction program after a failure or crash.

After `undo recover` resolves the active failed/interrupted transaction:

- earlier committed transactions stay committed;
- later transactions remain unexecuted;
- the user/agent may explicitly run a remaining named transaction with `--transaction NAME`, or rerun the program if its authored preconditions/idempotency make that safe.

Do not silently skip previously committed transactions based only on name/path heuristics. A future explicit program-run/resume feature may add stronger orchestration, but it is outside the core hackathon scope.

## 9. Machine-readable contract

`check --json` must include the ordered transaction names.

`plan --json` for a multi-transaction program must include a list of transaction plan summaries and a readiness field per transaction.

`run --json` for whole-program execution must include an ordered result list. Each started transaction must expose its own transaction ID and terminal/non-terminal state. Transactions not reached after a failure must be reported as `skipped` rather than omitted ambiguously.

## 10. Design consequence

This model gives UndoLang both breadth and a clean correctness boundary:

- `.undo` files can represent installation, upgrade, repair, cleanup, or several migration phases in one readable program;
- authors can execute one named transaction or the entire file;
- the runtime never confuses “run several transactions sequentially” with “all of these are one atomic transaction.”
