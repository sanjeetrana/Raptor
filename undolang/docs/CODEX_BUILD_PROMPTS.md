# Ordered Codex Build Prompts — UndoLang

Use these prompts **in order**. The first prompt assumes Codex is opened at the empty/new repository root and this documentation bundle has been copied into the repository.

Prompts after Prompt 0 are designed as follow-up prompts in the same Codex project/thread, but they remain explicit enough to recover from a fresh context. Do not paste all prompts at once.

---

## Prompt 0 — Bootstrap, read the specs, create the implementation plan

```text
You are the principal engineer responsible for implementing UndoLang, a production-grade crash-safe filesystem transaction runtime and DSL in Go 1.27 for the Zero Dependency hackathon.

Before writing any implementation code, read and obey the root AGENTS.md. Then read every document it lists in its mandatory reading order, especially HACKATHON_CONTEXT.md, PRD.md, PROGRAM_EXECUTION_MODEL.md, DSL_LANGUAGE_SPEC.md, TECHNICAL_SPEC.md, SECURITY_AND_EDGE_CASES.md, TEST_PLAN.md, STDLIB_PLAN.md, ENVIRONMENT_AND_RELEASE.md, and .agent/PLANS.md.

Non-negotiable: the runtime is Go 1.27 standard library only. go.mod must never gain a require block. Do not use golang.org/x, third-party packages, vendored source, package managers, external runtime executables, databases, cloud APIs, or frameworks. If you feel tempted to add a dependency, stop and solve the narrow requirement with stdlib/manual code or report a real blocker.

For this prompt, do NOT implement the product yet.

Tasks:
1. Inspect the repository and documentation.
2. Restate the locked architecture and public semantics in a concise engineering summary, including the program-vs-transaction model, default whole-file source-order execution, `--transaction` selection, and fail-fast cross-transaction boundary.
3. Resolve the public module path if the repository remote already makes it obvious. If not, use a clearly marked placeholder in the plan and ask me for the module path before committing go.mod; do not invent my GitHub username.
4. Create an ExecPlan for Phase 1 according to .agent/PLANS.md.
5. Create the skeleton directory structure specified in REPO_STRUCTURE.md only if doing so does not require choosing an unknown module path. Documentation-only directories/files are fine.
6. Identify any genuine spec contradiction or decision that requires me. Do not ask questions already answered in the docs.
7. Tell me exactly what you intend to implement in Phase 1 and the tests that will prove it.

Do not proceed into Phase 1 implementation in this prompt. Do not add dependencies. Do not generate placeholder success behavior.
```

Expected outcome: Codex has fully ingested the repository rules and created a concrete plan, not code-dumped the whole system.

---

## Prompt 1 — Go bootstrap + lexer + parser + AST + semantic validator

```text
Proceed with Phase 1: establish the Go 1.27 project and implement the complete UndoLang language front-end.

First reread AGENTS.md, PROGRAM_EXECUTION_MODEL.md, DSL_LANGUAGE_SPEC.md, relevant TECHNICAL_SPEC.md sections, SECURITY_AND_EDGE_CASES.md parser cases, TEST_PLAN.md sections 3-5, and the current ExecPlan. Update the ExecPlan before coding if needed.

Implement:
- go.mod with Go 1.27 and NO require block;
- cmd/undo minimal entrypoint sufficient for language commands as appropriate;
- token/source span model with byte offset + 1-based line/column;
- UTF-8 lexer;
- comments;
- quoted strings with specified escapes;
- raw backtick strings for Windows-friendly paths;
- all keywords/operators;
- recursive-descent parser;
- immutable/clean AST model;
- one or more uniquely named top-level transactions preserving source order;
- AST `Program` containing an ordered transaction slice;
- strict require* -> mutation* -> assert* phase semantics;
- all required operations and conditions from DSL_LANGUAGE_SPEC.md;
- semantic checks including SHA-256 syntax and replace empty-pattern rejection;
- useful diagnostics and stable language error codes;
- small stdlib-only spelling suggestion for unknown instruction if you can implement it cleanly.

Do NOT implement filesystem mutation, transaction journal, recovery, or fake stubs that claim these work. If CLI commands depend on future phases, they may return a clearly labeled not-yet-wired internal development error, but do not ship fake success.

Testing:
- exhaustive table tests for lexer/parser/validator, including multiple transactions and duplicate-name rejection;
- error line/column tests;
- CRLF and LF tests;
- Windows raw path tests;
- malformed input/panic resistance;
- fuzz tests for lexer/parser if practical with stdlib fuzzing.

Run:
GOPROXY=off go test ./...
GOPROXY=off go vet ./...
go list -m all

The module list must contain only the main module.

Update the ExecPlan with actual results. Report files changed, grammar implemented, tests run/results, any documented deviation, and stop. Do not begin Phase 2.
```

---

## Prompt 2 — Path capabilities, transaction root, reserved state, safe condition reads

```text
Proceed with Phase 2: implement the filesystem capability/path security layer and non-mutating condition evaluation.

Reread AGENTS.md, PROGRAM_EXECUTION_MODEL.md, PRD path requirements, TECHNICAL_SPEC sections 4 and 13, DSL_LANGUAGE_SPEC path semantics, SECURITY_AND_EDGE_CASES sections 2-5 and platform path cases, TEST_PLAN path/condition sections, and update/create the Phase 2 ExecPlan.

Implement:
- transaction root resolution: default invocation cwd, --root override;
- script file location independent from root;
- capability-root representation;
- repeatable --allow-path directory handling model;
- absolute-path mapping to most-specific capability root;
- relative-path binding to primary root;
- traversal-resistant actual file access with Go os.OpenRoot/os.Root;
- reserved .undo state path detection;
- rejection of root escape via .. and symlink traversal;
- typed resolved path structure used by later planner/executor;
- safe stat/lstat semantics;
- condition evaluator for exists, not_exists, is_file, is_dir, contains, sha256;
- contains and sha256 must stream and use bounded memory;
- clear path-policy error codes.

Do not mutate target files in this phase.

Important: do not rely on filepath prefix checks as the security boundary. filepath may assist normalization/mapping, but os.Root should enforce the declared root during actual access.

Add tests for relative/absolute/allowed/denied paths, script outside root, .. escapes, symlink escapes, reserved state, large-file contains/hash, Windows-oriented lexical path cases where platform allows.

Run all gates with GOPROXY=off and report.
```

---

## Prompt 3 — Planner and `check` / `plan` CLI, human + JSON contracts

```text
Proceed with Phase 3: build the immutable execution planner and production-quality non-mutating CLI flows.

Reread AGENTS.md, PROGRAM_EXECUTION_MODEL.md, PRD planning/CLI/AI-agent sections, TECHNICAL_SPEC plan/CLI/JSON/error sections, SECURITY_AND_EDGE_CASES conflict rules, TEST_PLAN planner/CLI/agent sections, and update the Phase 3 ExecPlan.

Implement:
- explicit stdlib flag.FlagSet subcommand dispatch without Cobra;
- check command: parse + semantic/path validation, no target mutation;
- check command returns ordered transaction names and rejects duplicate names;
- plan command: exact current-state plan for a selected transaction, and multi-transaction ProgramPlan with later state-sensitive checks explicitly deferred; no target mutation;
- `--transaction NAME` selection for plan;
- immutable ProgramPlan/Plan/PlannedOperation/PlannedCondition models;
- operation effect classification: create/modify/move/delete/overwrite/no-op;
- planner conflict detection specified in docs;
- recursive source inspection needed to plan directory operations safely;
- estimated rollback bytes/counts where determinable without unbounded memory;
- transaction-level safe_to_execute for exact plans; program-level safe_to_start plus per-transaction ready/deferred/unsafe status; warnings/reasons;
- human plan rendering;
- versioned JSON API (`undo-cli/1`);
- stable error object model;
- documented exit-code classes;
- --json output discipline (valid JSON only on stdout);
- --no-color / NO_COLOR behavior kept simple and dependency-free;
- capabilities --json;
- schema --json;
- agent-guide;
- version command.

Do NOT implement mutations yet. Do not let `run` pretend to work; it should clearly state it is unavailable until transaction engine is wired if still exposed during development.

Test that check/plan make no target mutations by snapshot/hash fixtures before/after. Test JSON as JSON, not string snapshots only. Test agent schema completeness.

Run full GOPROXY=off gates and report.
```

---

## Prompt 4 — Journal, state directory, lock, transaction state machine foundations

```text
Proceed with Phase 4: implement the durable state layer and journal, without yet wiring all filesystem mutation operations.

Reread AGENTS.md, TECHNICAL_SPEC sections 5-10 and 14-18, SECURITY_AND_EDGE_CASES journal/recovery/state sections, TEST_PLAN journal tests, STDLIB_PLAN, and update the Phase 4 ExecPlan.

Implement:
- .undo state layout;
- secure directory/file modes where supported;
- active.lock using O_CREATE|O_EXCL;
- UUIDv7 transaction IDs using Go 1.27 stdlib uuid;
- transaction metadata/status persistence;
- binary framed journal with magic/version/type/sequence/payload length/payload/CRC32C as specified (or an equally defensible format documented before implementation);
- strict decoder with payload-size caps;
- append + File.Sync discipline;
- transaction state transition validation;
- journal replay model;
- torn-tail handling;
- checksum/sequence/version corruption fail-closed behavior;
- history/inspect metadata foundation.

Do not add a database. Do not add a package. Do not implement a fake journal in memory.

Tests must cover every corruption/torn-record case in TEST_PLAN and fuzz the decoder for panic/allocation safety where practical.

Run all gates and report actual journal format/invariants.
```

---

## Prompt 5 — Real filesystem operations + inverse metadata + streaming algorithms

```text
Proceed with Phase 5: implement the real filesystem mutation primitives and their reversible metadata, using the path capability layer and journal-safe design.

Reread AGENTS.md, DSL_LANGUAGE_SPEC operation semantics, TECHNICAL_SPEC operation/backup/stream/symlink sections, SECURITY_AND_EDGE_CASES operation/file-type/large-file/cross-device sections, TEST_PLAN operation tests, and update the Phase 5 ExecPlan.

Implement real production operations:
- mkdir;
- copy regular file;
- recursive directory copy;
- move;
- write;
- literal streaming replace-all;
- delete;
- overwrite behavior exactly as grammar specifies;
- backup/staging for destructive target state;
- inverse metadata sufficient for rollback;
- bounded-memory io.CopyBuffer-style copying;
- streaming SHA-256 verification;
- streaming contains/replace boundary correctness;
- temp-file + sync + replacement protocol;
- supported mode preservation;
- explicit symlink policy; reject unsafe unsupported cases rather than following blindly;
- special-file rejection;
- cross-device move fallback only when the underlying error can be identified safely; otherwise fail clearly.

Do not wire a production demo/failure flag. These operations must be real.

Tests: all operation integration cases, rollback primitives, huge/chunk-boundary files, directory trees, overwrite restoration, symlink policy, special files where platform supports creating them.

Run all gates and report.
```

---

## Prompt 6 — Transaction execution, rollback, postconditions, real crash recovery

```text
Proceed with Phase 6: wire the complete transaction runtime, rollback, and crash recovery. This is the core correctness phase; favor safety over feature breadth.

Reread AGENTS.md, PROGRAM_EXECUTION_MODEL.md, PRD transaction/recovery acceptance criteria, TECHNICAL_SPEC sections 6-16, SECURITY_AND_EDGE_CASES recovery/TOCTOU/disk-full sections, TEST_PLAN transaction and crash sections, and update the Phase 6 ExecPlan in detail before coding.

Implement:
- run command real execution;
- revalidation after lock acquisition;
- precondition gate;
- sequential fail-fast whole-program runner: default all transactions in source order, `--transaction NAME` selection;
- fresh exact planning/precondition evaluation immediately before each transaction;
- prior committed transactions remain committed if a later transaction fails; later transactions become skipped;
- transaction begin/state journaling;
- per-operation prepared/applied ordering;
- actual operation execution from Plan;
- postcondition verification;
- commit state and safe cleanup;
- rollback in reverse from durable journal state;
- rollback prepared/applied records;
- recovery command driven by journal replay, not in-memory state;
- recovery idempotency if interrupted during rollback;
- stale unresolved lock behavior;
- preserve backups on ambiguous/corrupt/recovery-failed state;
- clear outcome/error codes for committed, rollback-success, recovery-required, recovery-failed.

Do NOT claim atomic visibility/isolation. Do NOT silently repair mid-journal corruption. Do NOT add fake crash flags to production.

Create real crash tests using subprocesses/test-only helper mechanisms and actual process termination at multiple durable-state points. Then run recover from a fresh process and compare restored filesystem state.

Also test operation failure and failed postcondition rollback.

Run full tests, race tests where supported, vet, module proof. Report exact crash tests passed and any platform-specific limitations.
```

---

## Prompt 7 — CLI completion, history/inspect, AI-agent ergonomics, installation behavior

```text
Proceed with Phase 7: finish the CLI as a real installable product and harden the machine-readable agent contract.

Reread AGENTS.md, PROGRAM_EXECUTION_MODEL.md, PRD AI/CLI/distribution sections, TECHNICAL_SPEC CLI/JSON/history sections, ENVIRONMENT_AND_RELEASE.md, TEST_PLAN CLI/agent sections, and update the ExecPlan.

Implement/refine:
- complete help UX;
- run interactive program/transaction plan summary + explicit confirmation;
- `run FILE` executes all transactions source-order; `run FILE --transaction NAME` selects one;
- `plan FILE` multi-transaction deferred-readiness semantics and `plan FILE --transaction NAME` exact current-state semantics;
- whole-program JSON ordered per-transaction results including skipped entries after failure;
- --yes for intentional noninteractive mutation;
- --json behavior with no prompts/prose corruption;
- history;
- inspect TXID;
- capabilities --json;
- schema --json;
- agent-guide;
- stable exit codes/error codes;
- version/build info without nondeterministic build timestamps;
- local installation convenience design from ENVIRONMENT_AND_RELEASE.md;
- install.sh and install.ps1 if specified, but ensure they are conveniences and not product runtime dependencies.

Do not add MCP yet. CLI + JSON is the universal integration surface.

Add black-box tests against compiled binary. Ensure any .undo file path works and root remains independent from script location.

Run all gates and report.
```

---

## Prompt 8 — Static marketing site and full documentation

```text
Proceed with Phase 8: build the zero-dependency static landing page and docs pages and synchronize all public docs with real implemented behavior.

Read docs/MARKETING_AND_DOCS_SPEC.md, PRD marketing requirements, current README/docs, actual CLI help/schema, docs/DESIGN.md and AGENTS.md. Update the ExecPlan.

Hard rule: marketing/ uses only hand-written HTML, CSS, and vanilla browser JavaScript. No npm, package.json, React, Next.js, Tailwind, Vite, CDN libraries, external font dependencies, analytics, or cloud API required for viewing.

Implement:
- polished landing page communicating the partial-state problem and UndoLang's plan/journal/apply/verify/commit-or-rollback model;
- installation section;
- real .undo example matching parser exactly;
- docs pages: getting started, language, programs/transaction selection, transactions/recovery, paths/capabilities, AI agents, security, limitations;
- responsive accessible layout;
- code snippets with hand-written CSS only;
- no fake playground unless it executes the real language semantics; do not duplicate a toy parser that can drift from Go runtime;
- README with build/run/limits/track rationale;
- docs/SUPPORT_MATRIX.md based only on actually tested platforms.
- the docs pages should be like popular documentation pages that are well-designed and easy to navigate. i should be able to go to a specific section and understand it quickly.
- the docs should be well detailed, from understanding installation and setup guide for all platforms (windows, linux and mac), to understanding each syntaxses, commands, file structure, etc. to examples and using it in real world scenarios.
- for the examples, i want there to be multiple examples that showcase different use cases of the language.
- it should also have places talking about how best agents can understand it
- there should also be a copy context to agent button for the agent to understand the full docs at once.
- example .undo files should be formatted well and easy to understand.


Audit every marketing claim against tests/code. Run relevant CLI tests again after docs examples are added, and if practical add tests that parse example .undo files from docs/examples.

Report pages created
```

---

## Prompt 9 — Zero-dependency proof, reproducible build, release artifacts

```text
Proceed with Phase 9: harden build/release reproducibility and produce the hackathon receipts.

Reread HACKATHON_CONTEXT.md, STDLIB_PLAN.md, ENVIRONMENT_AND_RELEASE.md, TECHNICAL_SPEC build section, TEST_PLAN reproducibility/dependency sections, and AGENTS.md. Update the ExecPlan.

Tasks:
- audit every Go import and repository asset for third-party runtime dependency;
- ensure go.mod has zero require directives and go.sum is absent/unnecessary;
- create final STDLIB.md with at least 10 real implemented substitutions and accurate source references;
- create dependency-proof script and deps-proof.txt from actual commands;
- ensure canonical build uses Go 1.27, CGO_ENABLED=0 unless proven otherwise, -trimpath, -buildvcs=false;
- build twice on same machine/toolchain and compare binary SHA-256;
- if hashes differ, diagnose nondeterminism and fix it; do not merely document failure if it is fixable;
- create reproducible-build.txt containing exact toolchain, command, both hashes, result;
- implement local cross-build/release script for agreed GOOS/GOARCH targets using only Go toolchain + shell/PowerShell build conveniences;
- ensure version embedding does not inject current time/random/VCS dirty metadata;
- create release/install instructions.

Do not claim +5 until byte-identical output is actually proven.

Run full tests after build changes. Report exact evidence.
```

---

## Prompt 10 — Adversarial audit, edge cases, scale, platform honesty

```text
Proceed with Phase 10: act as a hostile senior systems/code-review engineer and try to break UndoLang.

Read SECURITY_AND_EDGE_CASES.md and TEST_PLAN in full, then inspect actual implementation. Create/update the Phase 10 ExecPlan before modifications.

Audit and test aggressively:
- path traversal;
- symlink escape and replacement races;
- reserved state access;
- directory self-copy/move;
- duplicate/conflicting plan operations;
- malformed UTF-8/parser fuzz;
- huge journal payload lengths;
- torn/corrupt journals;
- actual process kills during execute and rollback;
- ENOSPC/permission failures where practical;
- large-file bounded-memory behavior;
- large directory trees;
- Windows/macOS/Linux behavioral gaps;
- existing destination overwrite restoration;
- special files;
- output/JSON injection via weird paths/transaction names;
- sensitive content leakage;
- lock/recovery idempotency.

For every issue found: fix it if within scope, add a regression test, and update documentation if the guarantee changes.

Do not hide limitations. Distinguish tested support from cross-compiled-only targets.

Run full gates at the end and provide a concise audit report.
```

---

## Prompt 11 — Final hackathon/submission readiness and implementation report

```text
Proceed with the final readiness pass. Do not add new product features unless necessary to fix a correctness/submission blocker.

Read HACKATHON_CONTEXT.md and every project requirement document one final time. Compare the actual repository against every PRD acceptance criterion and hackathon deliverable.

Tasks:
1. Run the complete test/build/dependency/reproducibility gates.
2. Verify go.mod empty dependency graph in five seconds.
3. Verify every examples/*.undo file parses and plans.
4. Verify marketing/docs examples match actual syntax.
5. Verify README contains one-command build, usage, Track F rationale, honest guarantees/limitations.
6. Verify STDLIB.md >=10 real substitutions.
7. Verify deps-proof.txt contains actual current output.
8. Verify reproducible-build.txt contains actual identical hashes.
9. Verify .zero-dep.toml has Track F and final one-line pitch.
10. Verify public license exists.
11. Create/update IMPLEMENTATION_REPORT.md with:
   - what was built;
   - architecture/package map;
   - exact required local toolchain;
   - all runtime environment variables (ideally none);
   - optional build/release env vars;
   - exact setup/build/install/run commands;
   - complete end-to-end test flow for a human;
   - complete agent usage flow;
   - commands/tests actually run and results;
   - tested OS/architectures vs cross-build-only;
   - known limitations;
   - any remaining issue that should block submission.
12. Create a 5-minute demo runbook/script based only on real behavior. Do not fake failures; use a real process kill where the demo needs crash recovery.

If any acceptance criterion is not met, say so explicitly and fix blockers before calling the project complete. Do not sugarcoat readiness.

At the end, give me a concise final report and exact next actions I need to perform manually (for example GitHub repo publication, release upload, video recording, Hackathon submission form). Do not invent API keys or environment variables.
```

---

## Optional Prompt 12 — Only if time remains after all gates are green

```text
All core requirements and final gates must already be green. Review the scoring rubric and identify ONE high-value polish improvement that does not weaken correctness, add a dependency, or expand the DSL into a general language. Examples could be better plan visualization, stronger journal inspection, improved install UX, or more polished documentation.

Propose the improvement first with expected score impact, implementation risk, and verification. Do not implement until I approve it.
```
