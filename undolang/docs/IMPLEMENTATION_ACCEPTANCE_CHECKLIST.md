# UndoLang Final Acceptance Checklist

Final local audit: 2026-08-29 on macOS arm64 with Go 1.27.0. Repository
criteria below are green unless explicitly marked as an external submission
task.

## Hackathon dependency compliance

- [x] Go 1.27 pinned/documented.
- [x] `go.mod` has no `require` block.
- [x] No `go.sum` needed for runtime project.
- [x] No `golang.org/x/...` imports.
- [x] No vendored/copied third-party library source.
- [x] Runtime invokes no external executable.
- [x] `GOPROXY=off go test ./...` passes.
- [x] `GOPROXY=off go build ...` passes.
- [x] `go list -m all` shows only main module.

## DSL

- [x] one or more named transactions/file.
- [x] duplicate transaction names rejected.
- [x] `run FILE` executes all in source order.
- [x] `run FILE --transaction NAME` executes only selected transaction.
- [x] entire source validates before any mutation.
- [x] whole-program execution is fail-fast; prior commits persist; later transactions skip.
- [x] UTF-8 lexer.
- [x] quoted/raw strings.
- [x] comments.
- [x] line/column diagnostics.
- [x] require phase.
- [x] all six operations.
- [x] assert phase.
- [x] all six conditions.
- [x] invalid/unknown syntax fails safely.
- [x] no shell/exec/import/plugin path.

## Paths/security

- [x] default root = cwd.
- [x] `--root` works.
- [x] script location independent.
- [x] absolute path inside root works.
- [x] external absolute path denied by default.
- [x] `--allow-path` works.
- [x] os.Root enforcement.
- [x] `..` escape blocked.
- [x] symlink escape blocked.
- [x] `.undo` reserved.
- [x] secret content not logged.

## Planner

- [x] no mutations.
- [x] operation effects accurate.
- [x] conflicts detected.
- [x] dangerous overwrite explicit.
- [x] backup estimate.
- [x] human output.
- [x] JSON output/version.

## Transaction engine

- [x] durable state directory.
- [x] exclusive active lock.
- [x] journal frames + CRC.
- [x] journal sync ordering.
- [x] backups before destructive changes.
- [x] all real operations.
- [x] large files streamed.
- [x] preconditions revalidated.
- [x] postconditions trigger rollback.
- [x] real filesystem/I/O/verification error triggers rollback independent of assertions.
- [x] operation error triggers rollback.
- [x] runtime derives rollback/recovery; no user-authored rollback required.
- [x] rollback reverse order.
- [x] backup cleanup only after safe finalization.

## Crash recovery

- [x] real child process kill tested.
- [x] interrupted execute recovered.
- [x] interrupted rollback recovered/idempotent.
- [x] torn tail handled.
- [x] mid-journal CRC corruption fails closed.
- [x] ambiguous state keeps backups.
- [x] unresolved lock blocks new run.

## CLI / AI agents

- [x] check.
- [x] plan.
- [x] run.
- [x] recover.
- [x] history.
- [x] inspect.
- [x] capabilities --json.
- [x] schema --json.
- [x] agent-guide.
- [x] stable error codes.
- [x] documented exit codes.
- [x] `--json` never polluted with prose.
- [x] noninteractive mutation requires explicit approval.

## Distribution/docs

- [x] static marketing folder, zero package dependencies.
- [x] README matches implementation.
- [x] language docs match parser.
- [x] security/limitations honest.
- [x] support matrix says tested vs cross-built.
- [x] prebuilt release strategy documented.
- [x] install.sh/install.ps1 convenience only; source builds can bootstrap a pinned Go 1.27.0 user-locally with checksum verification, while prebuilt installs stay offline.
- [x] no runtime environment variables/API keys.

## Bonuses/submission

- [x] STDLIB.md >=10 real substitutions.
- [x] build twice byte-identical.
- [x] both SHA-256 hashes published.
- [x] deps-proof.txt current.
- [x] reproducible-build.txt current.
- [x] `.zero-dep.toml` Track F.
- [x] public license.
- [ ] Five-minute demo video recorded and published (external submission task; the copyable live procedure is [`DEMO_RUNBOOK.md`](DEMO_RUNBOOK.md)).
