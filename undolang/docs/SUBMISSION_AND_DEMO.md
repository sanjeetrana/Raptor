# UndoLang Hackathon Submission and 5-Minute Demo Plan

This plan must use only behavior that genuinely exists in the final build.

The copyable five-minute operator sequence is in
[`DEMO_RUNBOOK.md`](DEMO_RUNBOOK.md). This document remains the submission
outline and checklist; the runbook is the canonical live-demo procedure.

## 1. Submission positioning

**Track:** F — Open / Wildcard

**Pitch:**

> UndoLang is a crash-safe filesystem transaction runtime and tiny DSL for reversible automation. It lets humans and AI agents describe coordinated file changes, inspect the exact plan, apply them through a durable journal, verify the final state, and recover or roll back when execution fails — all in one zero-dependency Go binary.

Core model: a `.undo` file is a filesystem program with one or more named transactions; each transaction is its own recoverable boundary. `undo run FILE` runs all in source order, while `--transaction NAME` selects one.

### Why Track F is defensible

A reasonable engineer would normally reach for a mix of:

- CLI framework;
- parser/DSL library;
- filesystem helper library;
- transaction/rollback machinery;
- UUID package;
- structured logging;
- hashing/checksum helpers;
- test/assertion helpers;
- possibly filesystem snapshot/system tooling.

UndoLang implements the needed narrow behavior directly from Go stdlib primitives and a handwritten DSL/runtime.

It is useful beyond being a constraint stunt: multi-file migrations and agent-driven file changes can leave half-applied state when one step fails.

## 2. Bonus target

### Reproducible Build +5

Show two builds on the same machine/toolchain with identical SHA-256.

### STDLIB Log +3

Show `STDLIB.md` with >=10 real substitutions.

Do not claim Single File.

Do not claim Package Killer unless final implementation truly qualifies.

## 3. Five-minute video outline

### 0:00–0:25 — Problem + artifact

Show landing page briefly and say:

> A script can change twenty files and fail on step seventeen. Your filesystem is then neither the old version nor the new one. UndoLang makes the migration itself transactional and recoverable.

Immediately show native `undo` binary and empty `go.mod` dependency graph.

### 0:25–0:55 — Language

Show a short real `.undo` program with:

- require;
- move/replace/write;
- assert.

Explain relative paths use transaction root and external paths require explicit capability.

### 0:55–1:30 — Check + plan

Run:

```bash
undo check demo.undo
undo plan demo.undo --root ./demo-app
```

Show exact creates/modifies/moves/deletes and rollback estimate.

Optionally show JSON agent plan:

```bash
undo plan demo.undo --root ./demo-app --json
```

### 1:30–2:15 — Successful transaction

Run real transaction.

Show:

```text
PLAN -> PREPARED -> RUNNING -> VERIFYING -> COMMITTED
```

Inspect files afterward.

### 2:15–3:35 — Real crash + recovery

Set up a transaction with enough real work that an external process can be killed after at least one journaled mutation.

Start `undo run` in a shell/process and **kill the real process externally** after a known observable operation/journal checkpoint.

Do not use a fake `--fail-after` flag.

Show the filesystem is in an interrupted transaction state and `.undo` contains durable state.

Then:

```bash
undo recover --root ./demo-app --yes
```

Show journal validation and reverse rollback.

Compare important pre/post hashes or file tree to prove restoration.

### 3:35–4:05 — AI-agent interface

Show:

```bash
undo capabilities --json
undo schema --json
```

Explain any coding agent that can write a file and execute a CLI can use UndoLang without a custom SDK.

### 4:05–4:35 — Zero dependency craftsmanship

Show:

```bash
cat go.mod
go list -m all
```

Then `STDLIB.md` highlights:

- `flag` instead of Cobra;
- handwritten parser;
- `os.Root` for path capabilities;
- custom journal with `encoding/binary` + `hash/crc32`;
- stdlib UUID;
- streaming file operations;
- stdlib testing.

### 4:35–4:55 — Reproducible build

Run/show actual result:

```text
build A SHA256: ...
build B SHA256: ...
MATCH
```

### 4:55–5:00 — Close

> One binary. One tiny language. No packages, no database, no daemon — and failed filesystem automation does not have to become an archaeology project.

## 4. Demo fixture rules

- fixture data may be synthetic, but product behavior must be real;
- no mocked transaction engine;
- no fake recovery;
- no prerecorded output represented as current CLI result;
- crash is real process termination;
- hashes come from real files/builds;
- JSON comes from real CLI.

## 5. Submission files checklist

- [ ] public GitHub repository
- [ ] OSI-approved license
- [ ] `go.mod` no require block
- [ ] `README.md`
- [ ] `STDLIB.md`
- [ ] `deps-proof.txt`
- [ ] `reproducible-build.txt`
- [ ] `.zero-dep.toml` with Track F/pitch
- [ ] one-command build documented
- [ ] tests pass with GOPROXY=off
- [ ] examples parse/plan
- [ ] marketing/docs static
- [ ] 5-minute demo video
- [ ] honest support matrix/limitations
- [ ] no code from before eligible window unless rule-compliant/disclosed (project code should all be new)

## 6. Write-up side quest outline

Potential title:

> I Built a Filesystem Transaction Language Without a Single Package

Sections:

1. partial-state problem;
2. why arbitrary shell execution would destroy reversibility;
3. designing a deliberately tiny DSL;
4. using `os.Root` for capability-safe paths;
5. journal frame and crash ordering;
6. the edge case that consumed the most time (likely symlink/recovery/rename semantics);
7. streaming large-file replace without a package;
8. reproducible build;
9. what stdlib made easy and what it did not;
10. honest limitations.


## Multi-transaction demo requirement

Show a `.undo` file containing at least two transactions. Demonstrate `undo plan FILE`, run one named transaction with `--transaction`, then show a whole-file run or explain source-order execution. If demonstrating a later failure, explicitly show that the current transaction rolls back while an earlier committed transaction remains committed and later transactions are skipped.
