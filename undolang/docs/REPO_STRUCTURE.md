# UndoLang Repository Structure

Use a conventional Go layout with clear ownership. Do not create unnecessary micro-packages.

```text
undolang/
├── AGENTS.md
├── README.md
├── STDLIB.md
├── LICENSE
├── go.mod
├── .zero-dep.toml
├── deps-proof.txt
├── Makefile                    # optional convenience; canonical go build must remain obvious
├── TESTING.md                  # simple copy/paste human testing guide
├── install.sh                  # local convenience; verified optional Go bootstrap
├── install.ps1
│
├── cmd/
│   └── undo/
│       └── main.go
│
├── internal/
│   ├── cli/
│   │   ├── app.go
│   │   ├── flags.go
│   │   ├── output.go
│   │   └── exitcodes.go
│   ├── lang/
│   │   ├── token/
│   │   ├── lexer/
│   │   ├── ast/
│   │   ├── parser/
│   │   └── validate/
│   ├── pathcap/
│   ├── plan/
│   ├── program/              # whole-file transaction selection + sequential fail-fast orchestration
│   ├── condition/
│   ├── fsop/
│   ├── streamutil/
│   ├── journal/
│   ├── state/
│   ├── txn/
│   ├── recovery/
│   ├── report/
│   └── buildinfo/
│
├── examples/
│   ├── app-upgrade.undo
│   ├── project-refactor.undo
│   ├── config-migration.undo
│   └── agent-safe-refactor.undo
│
├── tests/
│   ├── fixtures/
│   ├── crashhelper/            # test-only helper program/process if required
│   └── e2e/                    # optional black-box fixture data; Go tests may live with packages too
│
├── scripts/
│   ├── build.sh
│   ├── build.ps1
│   ├── deps-proof.sh
│   ├── repro-build.sh
│   └── release.sh              # local cross-build packaging, no third-party tooling required
│
├── marketing/
│   ├── index.html
│   ├── assets/
│   │   ├── styles.css
│   │   └── site.js
│   └── docs/
│       ├── index.html
│       ├── getting-started.html
│       ├── language.html
│       ├── transactions.html
│       ├── paths.html
│       ├── agents.html
│       ├── security.html
│       └── limitations.html
│
├── docs/
│   ├── HACKATHON_CONTEXT.md
│   ├── LANGUAGE.md
│   ├── TRANSACTIONS.md
│   ├── SECURITY.md
│   ├── AGENTS.md               # usage docs, not Codex control file; rename if confusing
│   └── SUPPORT_MATRIX.md, e.t.c
│
└── .agent/
    └── PLANS.md
```

## Package dependency direction

Desired rough direction:

```text
cmd/undo
   -> cli
       -> lang parser/validate
       -> pathcap
       -> plan
       -> txn/recovery
       -> report

plan
   -> ast/domain types
   -> pathcap
   -> condition metadata

program
   -> plan
   -> txn
   -> report

 txn
   -> journal
   -> fsop
   -> condition
   -> state
   -> plan

recovery
   -> journal
   -> fsop
   -> state
```

Avoid circular dependencies by keeping domain models small and placing shared result structs in appropriate low-level domain packages rather than a giant `utils` package.

## Forbidden repository content

- `vendor/`
- generated third-party source
- npm lockfiles
- `package.json` for marketing site
- third-party JS/CSS assets
- binary dependencies checked into source unless they are **our own release outputs** and clearly excluded from source build
- `go.sum` caused by external modules
- `golang.org/x/...` imports
- copied parser/CLI libraries

## `go.mod`

Only:

```go
module <public-module-path>

go 1.27
```

No `require` block.

## Naming guidance

- exported names only when package boundary/user API needs them;
- internal packages stay internal;
- avoid `Manager`, `Helper`, `Util` unless the type truly models that concept;
- prefer explicit types: `Plan`, `Journal`, `CapabilityRoot`, `Transaction`, `OperationRecord`, `SourceSpan`.
