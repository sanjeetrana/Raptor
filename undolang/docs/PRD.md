# Product Requirements Document — UndoLang

**Status:** implementation-ready

**Product:** UndoLang

**CLI:** `undo`

**Language extension:** `.undo`

**Implementation:** Go 1.27 standard library only

**Hackathon:** Zero Dependency, Track F — Open / Wildcard

---

## 1. Executive summary

UndoLang is a crash-safe transaction runtime and tiny domain-specific language for filesystem automation.

Modern automation routinely performs multi-step filesystem changes: software installers replace binaries and configuration files; deployment scripts migrate directory layouts; coding agents rename, create, rewrite, and delete dozens of files; local applications migrate persisted data between versions. Operating systems provide useful atomic primitives for individual filesystem operations, but applications still have to invent their own logic for coordinated planning, backup, rollback, crash recovery, path safety, and verification across a sequence of changes.

UndoLang makes those concerns part of the execution model.

A user writes a human-readable `.undo` **program** containing one or more named transactions:

```undo
transaction "prepare" {
    mkdir "backup"
    copy "config.json" -> "backup/config.json"
}

transaction "upgrade" {
    require sha256 "config.json" = "<expected-sha256>"

    move "plugins" -> "extensions"
    replace "config.json" "schema=1" -> "schema=2"
    write "VERSION" = "2\n"

    assert exists "extensions"
    assert contains "VERSION" "2"
}

transaction "cleanup" {
    delete "legacy/"
}
```

A `.undo` file is the program; a **transaction is the atomic/recoverable unit**. `undo run migration.undo --transaction upgrade` runs one named transaction. `undo run migration.undo` runs every transaction in source order. If a later transaction fails, that transaction rolls back while already committed earlier transactions stay committed; later transactions are skipped. Authors who need several steps to roll back together put those steps in one transaction.

Before any target mutation, `undo` parses and semantically validates the entire source program and resolves static policy constraints. Each transaction receives a fresh state-sensitive plan immediately before it executes, so its `require` conditions and conflicts observe the filesystem state produced by earlier committed transactions. During execution the runtime records durable journal state before/after each critical transition. A real filesystem/I/O/permission/disk-space/verification error or a failed `assert` rolls back the current transaction automatically. The script author defines forward intent and correctness conditions; UndoLang derives recovery from actual prior state and the journal. If the process or machine stops mid-transaction, the next invocation detects the incomplete journal and performs explicit recovery.

UndoLang does **not** claim universal filesystem ACID transactions or atomic visibility across arbitrary filesystems. Its promise is narrower and defensible: safe planning, controlled filesystem capabilities, durable intent/effect journaling, recoverable execution, rollback on known failure, and honest platform-specific durability guarantees.

---

## 2. Problem statement

### 2.1 The underlying failure mode

Many real workflows treat a sequence of filesystem mutations as one logical operation:

- replace application binary,
- migrate configuration,
- rename plugin directory,
- create metadata,
- remove obsolete files,
- update version marker.

If step 4 of 6 fails, the filesystem may be neither the valid old state nor the valid new state. Every application or script must otherwise build its own safeguards.

### 2.2 Why existing primitives are insufficient by themselves

- Atomic rename is excellent for a single replacement but does not provide a general transaction across unrelated files/directories.
- Git is excellent for tracked source state, but not general untracked/ignored/runtime/system files or multiple directory trees.
- Filesystem snapshots are powerful but platform/filesystem-specific and broader than a single automation transaction.
- Configuration-management/deployment frameworks may provide rollback conventions, but are dependency-heavy and not a local zero-dependency transaction language.
- AI coding tools increasingly provide checkpoints, but those protections are tool-specific and may not cover every filesystem mutation pathway.

UndoLang provides a small portable execution layer whose operations are constrained precisely because they must be explainable and reversible.

---

## 3. Product vision

### Vision statement

> Make destructive filesystem automation inspectable before it runs and recoverable after it fails.

### Product principles

1. **No hidden effects.** A plan must enumerate what will be created, modified, moved, or deleted.
2. **No mutation before validation.** Syntax, semantics, path policy, conflicts, and preconditions complete before the first mutating operation.
3. **Reversibility by construction.** The language exposes only mutations the runtime knows how to journal and reverse.
4. **Fail closed.** Ambiguous paths, corrupted journals, policy escapes, and unsafe recovery states stop execution rather than guessing.
5. **Human and agent friendly.** Terminal output is readable; JSON contracts are stable.
6. **Zero runtime dependencies.** No packages, daemons, external executables, databases, services, plugins, or APIs.
7. **Honest guarantees.** Platform-specific rename/fsync semantics and unsupported metadata are documented.
8. **Correctness before cleverness.** A smaller reliable transaction language beats a large partially correct scripting language.

---

## 4. Primary users

### 4.1 Software/tool authors

Need a safe way to perform in-place upgrades and migrations without embedding bespoke rollback machinery into every application.

### 4.2 DevOps/SRE/backend engineers

Need coordinated local configuration/layout migrations that either finish successfully or leave enough durable state to restore the prior filesystem state.

### 4.3 AI coding and automation agents

Need an inspectable boundary between generated intent and filesystem mutation. An agent can generate `.undo`, validate it, inspect a JSON plan, request/obtain approval, run it, and reason over machine-readable errors.

### 4.4 Developers performing project migrations

Need a safer way to restructure large local projects, including untracked/generated/local files that source control may not fully protect.

### 4.5 Local application migration authors

Need explicit preconditions, verified migration steps, postconditions, and crash recovery when upgrading persisted file layouts.

---

## 5. Critical use cases

### UC-1 — Application installer/updater

A version upgrade needs to replace several files and directories. A failure halfway through must not silently leave an unknown mixed state.

**Required behavior:** plan changes, verify expected starting state, journal mutations, rollback on failure, recover after interruption.

### UC-2 — AI-agent filesystem refactor

An agent wants to rename directories, rewrite configuration, create files, and delete obsolete files.

**Required behavior:** agent discovers syntax via CLI, generates `.undo`, runs `check` and `plan --json`, then executes only after explicit approval policy. All errors are machine-readable.

### UC-3 — Production/local configuration migration

Several related configuration files must change together before a service is restarted externally.

**Required behavior:** hash/existence preconditions prevent editing an unexpected state; postconditions verify final layout; no service restart is executed by UndoLang itself.

### UC-4 — Application data/layout migration

A local app transforms v1 directory layout into v2.

**Required behavior:** version precondition, deterministic operations, final version marker written only as part of the planned mutation sequence, rollback if final assertions fail.

### UC-5 — Certificate/config bundle rotation

Multiple certificate/key/config files must be replaced coherently.

**Required behavior:** protected backups, strict permissions where supported, no secret content printed in logs, postconditions, rollback on failure.

### UC-6 — Destructive batch file operation

A user reorganizes/renames/deletes many files.

**Required behavior:** explicit plan summary, destructive-operation warning, bounded-memory file handling, recoverable mutations.

---

## 6. Scope

### 6.1 Required hackathon scope

The shipped product must include:

- handwritten lexer,
- handwritten parser,
- AST,
- semantic validator,
- planner,
- path/capability resolver,
- transaction executor,
- durable append-only journal,
- rollback engine,
- crash recovery,
- real filesystem operations,
- real SHA-256 conditions,
- CLI with human and JSON output,
- self-description for AI agents,
- static marketing/docs site,
- zero-dependency proof,
- reproducible-build proof,
- comprehensive tests,
- install/release instructions,
- honest limitations.

### 6.2 Required DSL mutation statements

- `mkdir`
- `copy`
- `move`
- `write`
- `replace`
- `delete`

### 6.3 Required DSL conditions

- `exists`
- `not_exists`
- `is_file`
- `is_dir`
- `contains`
- `sha256`

### 6.4 Required CLI commands

- `undo version`
- `undo check FILE`
- `undo plan FILE`
- `undo run FILE`
- `undo run FILE --transaction NAME` (selection mode of `run`, not a separate command)
- `undo recover`
- `undo history`
- `undo inspect TXID`
- `undo capabilities`
- `undo schema`
- `undo agent-guide`

### 6.5 Required common flags

Where applicable:

- `--root PATH`
- `--transaction NAME` for `plan`/`run` when selecting one transaction from a program
- repeatable `--allow-path PATH`
- `--json`
- `--yes` for explicitly non-interactive execution
- `--no-color` or `NO_COLOR` support

### 6.6 Required program/transaction behavior

- a `.undo` file contains one or more named transactions;
- transaction names are unique within a file;
- entire source parses/validates before any target mutation;
- `undo run FILE` runs all transactions in source order;
- `undo run FILE --transaction NAME` runs only the selected transaction;
- every started transaction has its own transaction ID, journal, backups, state machine, and history entry;
- execution is fail-fast across transactions;
- failure/rollback of transaction N never automatically rolls back already committed transactions 1..N-1;
- transactions after a failed/recovery-required transaction are not started;
- normal recovery behavior is generated by UndoLang, not authored as rollback blocks in the DSL.

### 6.6 Required path behavior

- script path may be relative or absolute;
- script location never implicitly becomes transaction root;
- default transaction root = process working directory at invocation;
- relative DSL paths resolve under transaction root;
- absolute DSL paths inside transaction root are allowed;
- absolute DSL paths outside transaction root require explicit `--allow-path` capability;
- all capability roots are traversal resistant;
- path escapes through `..` or symlinks are rejected;
- state directory is reserved from transaction mutations.

---

## 7. Explicit non-goals for hackathon release

Do not implement these unless every core requirement and test is already complete:

- general-purpose shell execution,
- arbitrary subprocess execution,
- package/plugin system,
- network operations,
- remote execution,
- loops,
- user functions,
- variables or environment interpolation,
- imports/includes,
- conditional branching,
- concurrency inside one transaction,
- automatic service restarts,
- Git integration,
- database integration,
- MCP server,
- LSP server,
- VS Code extension,
- package manager,
- GUI framework,
- cloud telemetry,
- automatic updates,
- filesystem snapshot integration,
- universal ACL/xattr/ownership preservation,
- universal cross-platform atomic-visibility claim.

---

## 8. Main user workflows

### 8.1 Human author workflow

1. Write `migration.undo` with one or more named transactions.
2. `undo check migration.undo` to validate the entire program.
3. `undo plan migration.undo --root /target` for a whole-program plan, or add `--transaction NAME` for an exact current-state plan of one transaction.
4. Review transaction order, declared effects, exact first/selected transaction preflight, and any later deferred state-sensitive checks.
5. `undo run migration.undo --root /target` to run all transactions in source order, or add `--transaction NAME` to run one.
6. Receive an ordered per-transaction result; each started transaction has its own transaction ID.
7. If a transaction is interrupted, run `undo recover --root /target`. Earlier committed transactions remain committed.

### 8.2 AI-agent workflow

1. `undo capabilities --json`
2. `undo schema --json`
3. Agent writes `.undo`.
4. `undo check file.undo --json` and inspect ordered transaction names.
5. Repair syntax/semantic errors if any.
6. `undo plan file.undo --root ... --json` (or `--transaction NAME` for a selected exact plan).
7. Inspect per-transaction readiness, path capabilities, destructive effects, warnings, and rollback estimates; do not treat deferred later transactions as already safe.
8. Obtain required approval from the controlling workflow/user.
9. `undo run file.undo --root ... --yes --json` to run all, or select one with `--transaction NAME`.
10. If interrupted/error state requires recovery, `undo recover --root ... --json`; do not assume prior committed transactions were undone.

### 8.3 Recovery workflow

1. Any command opening a root checks for incomplete transaction state.
2. If recovery is required, mutating commands refuse to start a new transaction.
3. `undo recover` validates journal integrity and transaction metadata.
4. If the journal has only a torn final record, recover to the last valid framed record according to the technical spec.
5. Replay state to determine which operations definitely reached an applied state.
6. Roll them back in reverse order.
7. Verify rollback targets where possible.
8. Mark transaction `ROLLED_BACK` or fail closed with `E_RECOVERY_FAILED` / `E_JOURNAL_CORRUPT`.

---

## 9. Planning requirements

`undo plan` must perform no mutations to target data.

For one selected transaction, it produces an exact current-state plan. For a multi-transaction whole-program plan, it must not simulate prior commits by mutating the filesystem or falsely claim later state-sensitive checks are known. It reports source order and static effects for all transactions, fully preflights the first transaction, and marks later state-sensitive checks `deferred_until_execution`. `undo run` performs a fresh exact plan immediately before each transaction starts.

The plan should include at minimum:

- ordered transaction names and selection mode;
- per-transaction readiness (`ready` / `deferred` / unsafe reason);
- selected/current transaction name where applicable,
- script path,
- transaction root,
- explicit allowed capability roots,
- normalized/resolved operation paths,
- operation ordering,
- creates,
- modifications,
- moves,
- deletions,
- overwrite/conflict information,
- preconditions and their result,
- postconditions to be checked after execution,
- estimated rollback bytes when determinable without reading entire large files into memory,
- path-policy warnings,
- unsupported-file-type warnings,
- `safe_to_execute` only for an exact selected/current transaction plan;
- program-level `safe_to_start` plus deferred markers for later transactions;
- reasons when unsafe/deferred.

The human output should be concise but explicit. The JSON structure must be versioned.

---

## 10. Program execution behavior

- Whole-file execution is sequential and fail-fast.
- The complete source is parsed/semantically validated before the first mutation.
- Transaction N is freshly planned and its preconditions checked only after transaction N-1 has committed.
- A preflight/precondition failure in transaction N performs no mutation for N and stops the program.
- A real operation failure or operation-verification failure in N rolls back N automatically and stops the program.
- A failed `assert` rolls back N and stops the program.
- A crash/recovery-required state in N prevents later transactions from starting.
- Earlier committed transactions remain committed. There is no implicit cross-transaction rollback.
- If all steps must share one rollback boundary, author them inside one transaction.
- v0.1 does not automatically resume remaining transactions after recovery; the user/agent explicitly selects remaining work or reruns when safe.

---

## 11. Transaction behavior requirements

### 10.1 Pre-execution

A transaction must not mutate target files until all of these have succeeded:

- complete lexical analysis,
- complete parse,
- AST validation,
- language phase validation (`require*`, mutations, `assert*`),
- path capability validation,
- state-directory validation,
- reserved-path validation,
- operation conflict validation,
- precondition evaluation,
- recovery-required check,
- transaction lock acquisition,
- journal initialization.

### 10.2 During execution

For each mutation, UndoLang must persist enough durable state to distinguish at least:

- operation prepared but not applied,
- operation applied,
- rollback prepared,
- rollback applied.

The exact journal protocol is defined in `TECHNICAL_SPEC.md`.

### 10.3 Postconditions

All `assert` conditions execute after all mutations. Any failed assertion is a transaction failure and triggers rollback.

### 10.4 Commit

A commit is recorded only after all operations and postconditions succeed and durable transaction state is written according to the platform guarantee.

### 10.5 Known failure

A mutation/postcondition error triggers reverse rollback. If rollback itself fails, return a distinct recovery failure and retain all transaction state/backups for manual inspection/retry.

### 10.6 Crash/interruption

An incomplete transaction remains discoverable. A new mutating transaction is not allowed to silently continue over an unresolved transaction state.

---

## 12. AI/automation requirements

UndoLang must be usable by an agent that has never seen the project documentation.

### `capabilities --json`

Must provide:

- CLI version,
- DSL schema version,
- supported operations,
- supported conditions,
- path model,
- available workflow commands,
- JSON API version.

### `schema --json`

Must describe each statement/condition with syntax, argument types, reversibility, destructive classification, and examples.

### Error contract

Every structured failure must include:

- stable error code,
- human message,
- source position where relevant,
- filesystem path where relevant,
- transaction ID where relevant,
- retry/recovery classification where relevant.

No agent should need to regex terminal prose to determine what happened.

---

## 13. CLI usability requirements

- Clear `--help` for root and each subcommand.
- Distinguish stdout from stderr correctly.
- Machine JSON must go to stdout; diagnostic prose should not corrupt JSON output.
- Stable non-zero exit codes by error class.
- Respect non-TTY output and `NO_COLOR`.
- Do not print full sensitive file content.
- Do not prompt when `--json` is used; mutation requires `--yes` in non-interactive mode.
- `check` and `plan` are non-mutating.
- `run` displays a plan summary before confirmation in interactive mode.

---

## 14. Performance and scale requirements

The product is a local transaction tool, not a distributed system. “Scalability” therefore means predictable resource use and correctness on large real files/trees.

Required engineering targets:

- stream file copy and hashing; do not load entire large files into RAM;
- streaming `contains` and `replace` implementation with bounded overlap buffers;
- directory traversal via stdlib streaming walkers;
- bounded buffers (document chosen buffer size);
- journal append is incremental;
- no full-file bytes embedded into the journal;
- plan metadata should remain reasonable for at least 100k filesystem entries;
- test files of at least multi-hundred-MB where the CI/environment permits; architecture must support multi-GB files;
- mutation execution may remain sequential in MVP to preserve deterministic rollback ordering;
- correctness and durability are preferred over unsafe parallelism.

No performance claim should be published without a reproducible benchmark.

---

## 15. Security and privacy requirements

- Local-only; no telemetry and no network use.
- No external command execution.
- Explicit path capabilities.
- Traversal-resistant root operations using `os.Root` where applicable.
- Reserved state directory.
- State/backups created with restrictive permissions where supported.
- Journal should refer to backup locations; do not duplicate secret file contents into JSON/prose logs.
- Human/JSON output redacts file contents by default.
- Do not automatically resolve environment variables in DSL strings.
- Symlink behavior must be explicit and tested.
- Corrupted journal fails closed.
- Existing destination overwrite must be explicit/known to the planner and backed up before replacement.

See `docs/SECURITY_AND_EDGE_CASES.md`.

---

## 16. Platform requirements

Primary supported release targets:

- Linux amd64
- Linux arm64
- macOS amd64
- macOS arm64
- Windows amd64

Go 1.27 is pinned for source builds.

Platform semantics differ. In particular, do not state that rename is atomic on every platform. Support should be tested honestly; unsupported metadata/features must be documented.

---

## 17. Marketing/docs requirements

A static zero-dependency site lives in `marketing/`.

It must include:

- landing page,
- getting started,
- language reference,
- path/root model,
- transaction/recovery model,
- AI-agent usage,
- security/threat model,
- limitations,
- install/release instructions,
- link to GitHub.

No React, Next.js, Tailwind, Vite, npm, external JavaScript libraries, CDN fonts, analytics SDK, or service dependency.

It should work as static files and be deployable to GitHub Pages, but GitHub Pages is not required for the CLI to function.

---

## 18. Hackathon-specific requirements

- `go.mod` has no `require` block.
- No `go.sum` should be necessary.
- No vendored source.
- No runtime shell-out to Git, rsync, cp, mv, sed, tar, curl, or any separately installed command.
- Provide `STDLIB.md` with at least 10 meaningful substitutions.
- Provide dependency proof.
- One-command build.
- Reproducible build script/result with identical hashes from two builds on the same machine/toolchain.
- Public source and OSI-approved license before submission.
- Five-minute demo must show real operation, real failure/recovery, empty dependency manifest, and reproducible-build proof.

---

## 19. Acceptance criteria

The hackathon core is accepted only when all of the following are true:

1. A valid `.undo` file can be parsed from any filesystem location.
2. Invalid syntax reports line/column and stable error code.
3. `check` performs no target mutation.
4. `plan` performs no target mutation and accurately describes effects.
5. Relative paths resolve against transaction root.
6. Absolute paths within root work.
7. Absolute paths outside root are blocked unless explicitly capability-allowed.
8. `..`/symlink escape attempts are rejected.
9. Each required mutation operation works against the real filesystem.
10. Preconditions prevent execution without mutation.
11. Postcondition failure rolls back completed mutations.
12. Mid-transaction operation failure rolls back prior applied operations.
13. A real process kill during a transaction leaves recoverable durable state.
14. `recover` restores the prior state for supported cases.
15. Corrupted non-tail journal data fails closed.
16. A torn final journal record can be safely identified and handled according to spec.
17. Large file copy/hash/replace use bounded memory.
18. Human CLI and JSON CLI both work.
19. AI self-description commands work without project docs.
20. All tests pass with `GOPROXY=off`.
21. `go list -m all` contains only the main module.
22. Production binary shells out to no external executable.
23. Build twice with pinned command/toolchain produces identical binary hashes.
24. `STDLIB.md` documents >=10 real substitutions.
25. Static marketing/docs site contains no third-party runtime dependency.
26. README documents unsupported/limited semantics honestly.

---

## 20. Success metrics

Hackathon success is primarily judge-visible:

- judge understands problem in <30 seconds;
- judge can build in one command;
- zero deps verifiable in <5 seconds;
- first useful plan/run in <2 minutes from README;
- crash/recovery demo succeeds deterministically when process is actually killed at a known externally orchestrated point;
- code organization reads as idiomatic Go;
- limitations are explicit;
- no feature exists only as a UI/demo facade.

Post-hackathon product metrics, if continued:

- successful transaction rate,
- rollback success rate,
- recovery success rate,
- average/95p plan and execution overhead by file count/bytes,
- number of agent integrations using JSON contract,
- user-reported prevented partial migrations.

No telemetry should be added to collect these automatically without explicit future product design/consent.
