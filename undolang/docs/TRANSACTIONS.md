# Programs, Transactions, and Recovery

A `.undo` file is a program. A named transaction is its atomic/recoverable unit.

`undo run migration.undo` executes every transaction in source order. `undo run migration.undo --transaction upgrade` executes only `upgrade`, while still parsing and validating the entire source file. Whole-program execution is sequential and fail-fast: if transaction B fails, B rolls back, A remains committed, and C is skipped.

## Transaction protocol

Each transaction follows:

```text
PLAN -> LOCK -> PREPARE -> JOURNAL -> APPLY -> VERIFY -> COMMIT
                                                failure -> ROLLBACK
```

The runtime replans and rechecks preconditions after acquiring the root lock. Before each mutation it creates and verifies required backups, syncs an `OP_PREPARED` record, applies and verifies the operation, then syncs `OP_APPLIED`. Assertions run after all mutations. Commit is recorded only after every assertion succeeds.

## Failure and rollback

Operation errors and failed assertions trigger reverse rollback. Rollback decisions come from the durable journal, not an in-memory completed-operation list. If current state matches neither the recorded before state nor expected after state, UndoLang retains backups and fails closed.

## Crash recovery

An interrupted transaction leaves `<root>/.undo/active.lock` and a versioned CRC32C journal. Run:

```sh
undo recover --root /target --yes
```

Recovery validates the journal, repairs only an incomplete final frame after a valid prefix, and resumes inverse operations idempotently. Complete-frame corruption is never skipped or silently repaired. Recovery does not automatically resume later program transactions.

## Guarantees and boundaries

UndoLang provides controlled planning, durable intent/effect records, verified rollback, and crash recovery for supported operations. It does not provide isolation or atomic visibility across a sequence of filesystem changes. External applications can observe intermediate state, and rename/fsync durability differs by operating system and filesystem.

