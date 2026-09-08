# AGENTS.md — UndoLang Engineering Instructions

These instructions apply to the entire repository. Any nested `AGENTS.md` may add stricter local rules but must not weaken these constraints.

## Read first — mandatory

Before planning or changing implementation, read in this order:

1. `docs/HACKATHON_CONTEXT.md`
2. `docs/PRD.md`
3. `docs/PROGRAM_EXECUTION_MODEL.md`
4. `docs/DSL_LANGUAGE_SPEC.md`
5. `docs/TECHNICAL_SPEC.md`
6. `docs/SECURITY_AND_EDGE_CASES.md`
7. `docs/REPO_STRUCTURE.md`
8. `docs/TEST_PLAN.md`
9. `docs/STDLIB_PLAN.md`
10. `docs/ENVIRONMENT_AND_RELEASE.md`
11. `docs/MARKETING_AND_DOCS_SPEC.md`
12. `docs/TOOLS_SKILLS_MCP.md`
13. `.agent/PLANS.md`

If these documents conflict, priority is:

1. `docs/HACKATHON_CONTEXT.md` for competition/dependency rules;
2. explicit user instruction;
3. `docs/SECURITY_AND_EDGE_CASES.md` for safety;
4. `docs/PROGRAM_EXECUTION_MODEL.md` for program-vs-transaction execution semantics;
5. `docs/DSL_LANGUAGE_SPEC.md` for language syntax/semantics;
6. `docs/TECHNICAL_SPEC.md` for implementation details;
7. `PRD.md` for product scope.

If a conflict remains material, stop that specific implementation decision and ask the user rather than inventing semantics.

## Zero-dependency law

This repository competes in the Zero Dependency hackathon.

**The shipped runtime must have zero third-party runtime dependencies.**

For Go:

- Go 1.27 standard library only.
- `go.mod` must have no `require` block.
- Never run `go get` to add a library.
- Never import `golang.org/x/...`.
- Never vendor/copypaste a third-party implementation to fake an empty module graph.
- Never shell out at runtime to Git, curl, sed, cp, mv, rsync, tar, PowerShell, Python, Node, or another separately installed program to implement product functionality.
- Use the Go standard library and code written in this repository during the eligible hackathon window.

Before suggesting a dependency, stop and find the stdlib/manual implementation. If Go stdlib genuinely has no answer, implement the required narrow behavior ourselves or report the limitation; do not smuggle in a package.

## Product definition

UndoLang (`undo`) is a crash-safe filesystem transaction runtime and small `.undo` DSL.

A `.undo` file is a filesystem program containing one or more uniquely named transactions. A transaction is the atomic/recoverable unit. `run FILE` runs all in source order; `run FILE --transaction NAME` selects one. Whole-file execution is sequential/fail-fast, never an implicit super-transaction.

It is **not** a general-purpose programming language.

Never add:

- arbitrary shell/command execution;
- plugins;
- package loading;
- network/cloud dependencies;
- loops/functions/imports/variables unless the user later explicitly changes v1 scope;
- hidden environment interpolation.

Every shipped mutating DSL operation must have understood effects, planning representation, journaling, recovery semantics, and rollback/inverse behavior.

## Engineering standard

Write as a senior systems engineer and DSL/runtime author.

Required qualities:

- idiomatic Go;
- simple explicit ownership;
- defensive input parsing;
- bounded memory for large data;
- no panic on untrusted `.undo`/journal input;
- durable state transitions before destructive assumptions;
- fail closed on ambiguous recovery;
- clear stable errors;
- cross-platform behavior documented honestly;
- tests for every significant edge case;
- no placeholders or TODO-backed “success” behavior.

Avoid over-engineering. Do not build abstractions just to look architectural.

## No mocks/fakes in shipped behavior

Production code must never pretend a transaction, rollback, recovery, file operation, dependency proof, or reproducible build succeeded.

Tests may use:

- `testing.T.TempDir`;
- test-only helper processes;
- real subprocess termination;
- generated fixture files;
- stdlib test/fuzz tooling.

Prefer real filesystem integration over mocked interfaces. Do not introduce an interface solely to create fake tests if real temp-directory tests are practical.

## Planning requirement

For each substantial phase from `CODEX_BUILD_PROMPTS.md`, create/update an ExecPlan according to `.agent/PLANS.md` before implementing.

The ExecPlan is a living artifact: record decisions, discoveries, test results, and deviations.

Do not execute all project phases in one uncontrolled pass. Finish and verify the current phase, report results, then wait for the next follow-up prompt unless the user explicitly asks otherwise.

## Filesystem safety rules

- Relative DSL paths resolve against transaction root, never script directory.
- Absolute paths outside root require explicit `--allow-path` capability.
- Use `os.OpenRoot` / `os.Root` as the primary traversal-resistant boundary.
- Never rely on string-prefix path checks alone.
- `.undo/` runtime state is reserved.
- Revalidate important filesystem assumptions after lock acquisition and immediately before mutation.
- No arbitrary symlink following.
- Do not claim cross-platform atomic rename; Go documents platform differences.

## Transaction rules

The entire source program must parse and semantically validate before any target mutation. For whole-file execution, each transaction then gets a fresh exact plan immediately before it starts. Later transaction failures never roll back earlier committed transactions.

Real filesystem/I/O/permission/disk-space/operation-verification errors are transaction failures independent of `assert`. Script authors define forward intent and correctness conditions; runtime code owns inverse/recovery behavior. Never add user-authored arbitrary rollback blocks.

No target mutation for the current transaction until:

- whole source parsed;
- semantic validation complete;
- path/capability validation complete;
- plan/conflict analysis complete;
- preconditions complete;
- recovery state checked;
- transaction lock acquired;
- journal initialized durably.

Journal/recovery state, not in-memory lists, is authoritative after crash.

If rollback/recovery becomes ambiguous, preserve backups and fail closed.

## CLI/agent contract

Machine JSON is a first-class API.

- stable API version;
- stable error codes;
- JSON stdout must never be contaminated by decorative prose;
- exit codes documented;
- `capabilities --json`, `schema --json`, `check --json`, `plan --json`, `run --json`, `recover --json` are required;
- `--json` does not itself grant permission to mutate; noninteractive mutation requires explicit approval flag (`--yes`).

## Performance rules

- never `os.ReadFile` arbitrary large mutation targets for copy/hash/contains/replace;
- use streaming and bounded buffers;
- sequential mutations are acceptable and preferred for deterministic rollback;
- do not add unsafe concurrency just to claim scalability;
- no benchmark claims without benchmark evidence.

## Testing gates after every phase

Run the smallest relevant tests during development and the full gates when a phase completes:

```bash
GOPROXY=off go test ./...
GOPROXY=off go vet ./...
```

Where supported:

```bash
GOPROXY=off go test -race ./...
```

Before completion also verify:

```bash
go list -m all
```

It must list only the main module.

## Documentation discipline

When implementation changes behavior, update the relevant docs in the same phase:

- README/usage;
- language reference;
- transaction guarantees;
- security limitations;
- STDLIB substitutions;
- support matrix.

Do not leave docs claiming semantics the code does not provide.

## Marketing site

`marketing/` is static HTML/CSS/vanilla JS only.

No npm, React, Next.js, Tailwind, Vite, external JS framework, external font dependency, analytics SDK, or CDN requirement.

The site must make only claims demonstrated by real code/tests.

## Environment and secrets

UndoLang requires no API keys and no runtime service credentials.

Do not introduce `.env` as a product requirement.

Any build/release environment variables must be documented in `ENVIRONMENT_AND_RELEASE.md` and must not affect runtime correctness.

## Final implementation handoff

At project completion, create/update:

- `README.md`
- `docs/STDLIB.md`
- `docs/deps-proof.txt`
- `docs/reproducible-build.txt`
- `docs/SUPPORT_MATRIX.md`
- `docs/IMPLEMENTATION_REPORT.md`

`docs/IMPLEMENTATION_REPORT.md` must tell the user:

- exactly what was built;
- architecture/package map;
- exact build/test commands run;
- results;
- environment variables required (ideally none at runtime);
- how to install/run;
- how to test the complete flow;
- known limitations and untested platform behavior;
- any decisions that still need user input.
