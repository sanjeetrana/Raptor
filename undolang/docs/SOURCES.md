# Sources and Authoritative References

These references informed the handoff. Product behavior should always follow the repository specifications plus verified official docs.

## Zero Dependency hackathon

- Official site: https://zerodepshack.com/
- Official cheat sheets: https://zerodepshack.com/cheatsheets
- Official context pack: https://zerodepshack.com/zero-dependency-context.txt
- Discord for rulings not covered by the pack: https://discord.com/invite/xfYPDZYqeh

## Go 1.27

- Go 1.27 release notes: https://go.dev/doc/go1.27
- Go 1.27 release announcement: https://go.dev/blog/go1.27
- Go standard library docs: https://pkg.go.dev/std
- `os` package: https://pkg.go.dev/os
- `path/filepath`: https://pkg.go.dev/path/filepath
- `hash/crc32`: https://pkg.go.dev/hash/crc32
- Go modules reference: https://go.dev/ref/mod

## Traversal-resistant filesystem roots

- Go blog — Introducing `os.Root`: https://go.dev/blog/osroot

Important verified points:

- `os.Root` / `os.OpenRoot` provide traversal-resistant operations under a directory and reject escapes through relative components/symlinks.
- `os.OpenRoot` was introduced in Go 1.24; additional Root methods were added later. Project pins Go 1.27.
- Go `os.Rename` documentation warns that rename is not atomic on all non-Unix platforms. UndoLang must not claim universal atomic rename.
- `File.Sync` commits current file contents toward stable storage subject to OS/filesystem semantics.

## Codex repository guidance

- OpenAI Codex repository AGENTS.md behavior/spec source: https://github.com/openai/codex
- OpenAI Cookbook — ExecPlans/PLANS.md for long Codex work: https://github.com/openai/openai-cookbook/blob/main/articles/codex_exec_plans.md

Relevant principle: root/nested `AGENTS.md` files are a durable way to instruct Codex about repository conventions and verification; an ExecPlan is useful for long significant work.

## Source priority

For hackathon rules: `HACKATHON_CONTEXT.md` is authoritative.

For Go API behavior: use the exact Go 1.27 official documentation/source, not remembered behavior from older Go versions.

For filesystem durability claims: be conservative and platform-specific. Do not upgrade “works in a test” into a universal filesystem guarantee.
