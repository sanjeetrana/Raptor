# UndoLang Implementation Plan

This file is the living implementation plan for UndoLang.

Codex must:

- Read `AGENTS.md` first.
- Read `docs/HACKATHON_CONTEXT.md`.
- Read `docs/PROGRAM_EXECUTION_MODEL.md`.
- Read `docs/PRD.md`, `docs/DSL_LANGUAGE_SPEC.md`, and `docs/TECHNICAL_SPEC.md`.
- Update this plan before beginning each implementation phase.
- Mark completed work honestly.
- Record architectural decisions, blockers, unresolved questions, and verification results.
- Never introduce a third-party dependency.
- Never silently change product semantics.

## Current Phase

Complete through Phase 11. The final usability handoff adds only repository
convenience documentation; no product implementation phase is currently
active.

## Completed

- Phase 0: repository/bootstrap plan recorded.
- Phase 1: Go 1.27 module, source spans, UTF-8 lexer, recursive-descent parser, ordered AST, semantic validator, spelling suggestions, and initial `check`/`version` entrypoint.
- Phase 2: `os.Root` capability set, most-specific absolute mapping, reserved/escape policy, safe stat/open behavior, and bounded-memory contains/SHA-256 evaluation.
- Phase 3: exact/deferred program planner, conservative conflict analysis, rollback estimates, `undo-cli/1` JSON envelopes, and production read-only CLI commands.
- Phase 4: restrictive `.undo` layout, UUIDv7 metadata, exclusive active lock, validated state transitions, synced atomic status writes, CRC32C framed journal, strict replay, torn-tail detection, and history/inspection foundations.
- Phase 5: serializable prepare/apply/verify/undo metadata; verified backups; mkdir, copy, move, write, literal streaming replace, and delete primitives; complete-entry overwrite restoration; root-safe temporary installation; basic mode preservation; explicit symlink/special-file policies; and fail-closed inverse verification.
- Phase 6: crash-classifiable prepared metadata, strict journal state replay, source-order execution, post-lock revalidation, postconditions, journal-driven reverse rollback, idempotent recovery, real `run`/`recover`, and nine real-process kill/recover checkpoints.
- Phase 7: complete help and approval UX, whole-program JSON results, stable exit classes, history/inspect, expanded schema/capabilities, compiled-binary contract tests, and local shell/PowerShell installers.
- Phase 8: static newsprint landing/docs site, canonical runtime guides, five parser-validated examples, downloadable agent context, responsive navigation, and automated snippet/link/command correctness tests.
- Phase 9: version 0.1.0, MIT license, Track F metadata, 15-entry stdlib ledger, dependency receipts, byte-identical build proof, local installers, and five-target cross-build/checksum tooling.
- Phase 10: hostile path/state/journal/planner/CLI review, canonical-root and symlink-identity fixes, strict recovery ownership, structured agent failures, permission/no-space classifications, active fuzzing, 100k-tree/256 MiB stress, and final acceptance evidence.
- Phase 11: final submission-readiness audit, explicit 26-item acceptance matrix, refreshed dependency/reproducibility receipts, complete implementation handoff, and copyable real-kill demo runbook.
- Final usability handoff: added a dependency-free `Makefile` for build, gate,
  proof, release, and common CLI commands, plus `TESTING.md` with real
  end-to-end, rollback, JSON-agent, and crash-recovery instructions.

## In Progress

- None.

## Next

- Submission-only work outside implementation: publish the public repository, upload release artifacts/checksums if desired, record/publish the five-minute demo, and complete the hackathon form.

## Decisions Made During Implementation

- Public module path: `github.com/daniel-oluwadunsin/undolang`.
- Go version: 1.27.0, standard library only, with no `require` block.
- The user explicitly authorized continuous work through Prompt 5, overriding per-prompt stop points.
- Prompt 5 ends at real reversible filesystem primitives; production `run`/recovery orchestration remains Phase 6.
- Quoted strings implement `\\uXXXX` and reject surrogate code points.
- Empty `contains` needles are semantic errors.
- Symlink copy is rejected in v1; symlink move/delete operate on the link entry.
- JSON uses Go 1.27 `encoding/json/v2`; transaction IDs use standard-library `uuid.NewV7`.
- The user authorized continuous implementation through Phase 10 with phase-specific verification and commits.
- Recovery classifies each prepared operation against durable before/after descriptors. Any state matching neither descriptor is ambiguous and fails closed with backups retained.
- A torn final journal frame may be truncated only to a fully validated prefix; complete-frame corruption is never repaired.
- Mutating JSON/noninteractive CLI use requires `--yes`; interactive confirmation is added in Phase 7.
- Source installers now auto-bootstrap the pinned Go 1.27.0 archive only when a source build lacks Go 1.27.x. Archives are fetched from `go.dev`, checked against pinned SHA-256 values for supported host architectures, installed under a user-local toolchain directory, and never added to the shipped runtime. `--no-install-go` / `-NoInstallGo` retains an explicitly offline path; prebuilt binaries never invoke the bootstrap.

## Open Questions

None blocking Phases 0-5.

## Verification

- Go 1.27 toolchain availability: verified with `GOTOOLCHAIN=go1.27.0 go version`.
- Phase 1 `GOPROXY=off go test ./...`: pass.
- Phase 1 `GOPROXY=off go vet ./...`: pass.
- Phase 1 `GOPROXY=off go test -race ./...`: pass on macOS arm64.
- Phase 1 `go list -m all`: one module (`github.com/daniel-oluwadunsin/undolang`).
- Phase 2 offline tests, vet, and race detector: pass on macOS arm64.
- Phase 2 module proof: one main module.
- Phase 3 offline tests, vet, and race detector: pass on macOS arm64.
- Phase 3 `check`/`plan` mutation snapshots and structured JSON contract tests: pass.
- Phase 4 offline tests, vet, and race detector: pass on macOS arm64.
- Phase 4 journal corruption/torn-tail/reference tests and state lock lifecycle tests: pass.
- Phase 5 focused filesystem operation/inverse integration tests: pass on macOS arm64.
- `UNDOLANG_STRESS=1 GOPROXY=off GOTOOLCHAIN=go1.27.0 go test ./internal/fsop -run '^TestStressCopy256MiB$' -count=1`: pass.
- `GOPROXY=off GOTOOLCHAIN=go1.27.0 go test ./...`: pass.
- `GOPROXY=off GOTOOLCHAIN=go1.27.0 go vet ./...`: pass.
- `GOPROXY=off GOTOOLCHAIN=go1.27.0 go test -race ./...`: pass on macOS arm64.
- `CGO_ENABLED=0 GOOS=<target> GOARCH=amd64 GOPROXY=off GOTOOLCHAIN=go1.27.0 go test -run '^$' -exec=/usr/bin/true ./...` for linux, windows, and darwin: compilation/linking pass; foreign behavioral tests were not executed.
- `GOTOOLCHAIN=go1.27.0 go list -m all`: one module (`github.com/daniel-oluwadunsin/undolang`).
- Phase 6 `GOPROXY=off GOTOOLCHAIN=go1.27.0 go test ./...`: pass.
- Phase 6 `GOPROXY=off GOTOOLCHAIN=go1.27.0 go vet ./...`: pass.
- Phase 6 `GOPROXY=off GOTOOLCHAIN=go1.27.0 go test -race ./...`: pass on macOS arm64.
- Phase 6 crash matrix: nine externally killed subprocess checkpoints recovered by a freshly built CLI process; pass on macOS arm64.
- Phase 6 module proof: only `github.com/daniel-oluwadunsin/undolang`.
- Phase 7 offline tests, vet, and race detector: pass on macOS arm64.
- Phase 7 compiled-binary help/version/schema/capabilities tests and run/history/inspect JSON tests: pass.
- Phase 7 installer shell syntax validation: pass; PowerShell execution is untested on this host.
- Phase 8 parser validation for every repository example and public UndoLang snippet: pass.
- Phase 8 documented-command help, local-site-link, and zero-external-asset tests: pass.
- Phase 8 desktop/mobile browser review, responsive navigation, and copy-to-agent interaction: pass.
- Phase 8 offline tests, vet, and race detector: pass on macOS arm64.
- Phase 8 module proof: only `github.com/daniel-oluwadunsin/undolang`.
- Phase 9 dependency proof: `go.mod` has no `require`, `go.sum` is absent, module list contains only the main module, and offline tests/build pass.
- Phase 9 proof was regenerated after Phase 10 production fixes. Final canonical macOS arm64 builds both hashed `6a7b1ba6a62e911d4ab93759a9809615efda8369d7347a5e562bc7d336771d2d`.
- Phase 9 cross-builds: Linux amd64/arm64, macOS amd64/arm64, and Windows amd64 all pass with CGO disabled; only macOS arm64 behavior is claimed tested.
- Phase 9 offline tests, vet, and race detector: pass on macOS arm64.
- Phase 10 active fuzzing: lexer ~172k executions, parser ~246k, journal decoder ~880k; no panic or failure.
- Phase 10 opt-in scale: 100,000-entry planner test pass in 21.851s; 256 MiB copy/undo test pass in 1.883s.
- Phase 10 uncached nine-checkpoint real-process crash/recovery matrix: pass in 3.720s.
- Phase 10 final offline tests, vet, race detector, documentation validation, dependency proof, five release cross-builds, and module proof: pass.
- Phase 11 final fresh `GOPROXY=off GOTOOLCHAIN=go1.27.0 go test ./... -count=1`: pass.
- Phase 11 final `GOPROXY=off GOTOOLCHAIN=go1.27.0 go vet ./...`: pass.
- Phase 11 final `GOPROXY=off GOTOOLCHAIN=go1.27.0 go test -race ./... -count=1`: pass.
- Phase 11 final example parse/plan verification: all five `examples/*.undo` passed real `check` and `plan` commands against prepared fixtures.
- Phase 11 final documentation checks: all public `.undo` snippets parsed, marketing links/assets checks passed, and every documented command exposed help.
- Phase 11 final active fuzzing: lexer 142,471 executions, parser 73,804, journal 279,128; all pass.
- Phase 11 final stress/crash: 100k-entry planner 23.589s, 256 MiB copy 2.260s, nine real kill/recover checkpoints 5.767s; all pass.
- Phase 11 final dependency proof: one `go list -m all` line, no `require`, no `go.sum`, offline test/build pass.
- Phase 11 final reproducibility: both canonical macOS arm64 builds hash `6a7b1ba6a62e911d4ab93759a9809615efda8369d7347a5e562bc7d336771d2d`.
- Phase 11 final release cross-build: Linux amd64/arm64, macOS amd64/arm64, and Windows amd64 pass with CGO disabled.
- Installer bootstrap update: shell syntax/help and documentation were updated for the verified Go 1.27.0 user-local bootstrap; PowerShell execution remains untested on this macOS host.
- Reproducible-build UX update: `make reproducible-build` is the canonical one-command bonus proof; it builds twice with the pinned offline settings, labels both SHA-256 values, and retains `make repro` as an alias.
- Reproducible-build UX verification: `make reproducible-build` passed twice on macOS arm64; Build A and Build B both printed `6a7b1ba6a62e911d4ab93759a9809615efda8369d7347a5e562bc7d336771d2d`, and the helper reported byte-identical output.
- Live example update: replaced the abstract multi-file example set with one parser-valid `examples/live-filesystem.undo` program containing selectable seed, upgrade, overwrite, move/delete, rollback, missing-source, permission, and fail-fast transactions; mirrored it to `~/Desktop/undolang-examples` with a disposable-root README.
- Final usability handoff verification: `make help`, `make build`, `make test`,
  `make vet`, `make race`, `make examples`, `make modules`, `make verify`,
  `make fuzz`, `make stress`, `make crash-test`, `make deps-proof`, and `make
  repro` were run on macOS arm64; the copy/paste flow in `TESTING.md` was also
  exercised against temporary roots.
