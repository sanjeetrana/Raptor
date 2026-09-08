# Submission Checklist

- [ ] Public GitHub repository
- [ ] Track D (Data & Storage)
- [ ] Working implementation
- [ ] Go 1.27 (`go.mod` currently pins `go 1.22`, the highest version
      available in the build/test environment used for this submission;
      confirm on Go 1.27 before final submission and bump the `go`
      directive if desired — no code changes should be required)
- [ ] Zero third-party runtime dependencies (`go list -m all` /
      `go mod graph` show only `minikv` and the toolchain — see README.md
      "Dependency Proof")
- [ ] Valid go.mod
- [ ] Dependency proof included in README.md
- [ ] README.md complete
- [ ] STDLIB.md — at least 10 documented substitutions
- [ ] SECURITY.md — threat model documented
- [ ] Tests: `go test ./...` passes
- [ ] Race test: `go test -race ./...` passes
- [ ] `go vet ./...` clean
- [ ] `gofmt -l .` reports no files
- [ ] Demo video recorded (max 5:00), following DEMO_SCRIPT.md
- [ ] DEMO_SCRIPT.md present
- [ ] LICENSE present
- [ ] No secrets (API keys, tokens, credentials, machine-specific paths)
      in the repository
- [ ] No copied third-party source
- [ ] One-command build: `go build -o minikv ./cmd/minikv`
- [ ] Clean-clone test performed (see below)
- [ ] Git history compliant: all implementation commits made during the
      official 72-hour hackathon window, no fabricated timestamps, no
      imported pre-existing project code
- [ ] Team section in README.md filled in with real member details
      (currently placeholders)
- [ ] Final submission completed on the hackathon platform

## Clean-clone test (run before declaring the project finished)

```bash
git clone <repo-url> minikv-clean-test
cd minikv-clean-test
go build -o minikv ./cmd/minikv
go test ./...
go test -race ./...
./minikv set hello world
./minikv get hello
```

Confirm: clone succeeds, build succeeds, both test commands pass, the CLI
works, and (separately) that killing/reopening mid-write still recovers
correctly per the crash-recovery tests.

## Bonus tracks (only claim what's actually true)

- [ ] Reproducible build (+5): build twice, hash both binaries, document
      both hashes in the final report. Only claim this if the hashes
      actually match — if they differ, document why instead of hiding it.
- [ ] Single file (+5): only pursue if a genuinely useful single-file
      `singlefile/minikv.go` can be produced without harming the quality
      of the main multi-file implementation.
- [ ] Package Killer: only claim for a component that legitimately
      reimplements what a specific named package would normally provide
      (see the storage-engine entry in STDLIB.md as the primary
      candidate) — document package, purpose, normal usage, MiniKV's
      replacement, and its limitations.
