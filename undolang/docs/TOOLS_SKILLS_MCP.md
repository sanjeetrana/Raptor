# Codex Tools, Skills, and MCP Guidance for UndoLang

## Executive recommendation

**No MCP server or external skill is required to build UndoLang correctly.**

For this project, fewer development integrations are safer because the product itself must remain zero-dependency and the architecture is intentionally based on Go's standard library.

## Required Codex control surfaces

### Root `AGENTS.md`

Use it. Codex recognizes repository `AGENTS.md` files as durable project instructions. This bundle provides one with dependency/safety/testing rules.

### `.agent/PLANS.md`

Use ExecPlans for long phases. OpenAI's Codex guidance recommends a plan document for complex multi-hour work. The supplied prompt sequence explicitly requires one per significant phase.

## Optional development-time tooling

### GitHub integration / MCP / connector — optional

Useful only for:

- creating/managing issues;
- reviewing PRs;
- checking repository state remotely;
- publishing/release workflow assistance.

It is **not needed for implementation** and must never become a runtime dependency.

If Codex already has normal local Git/terminal access, that is enough for the hackathon build.

### Web/documentation access — useful

Allow Codex to consult authoritative docs when a Go/platform semantic is uncertain, especially:

- Go 1.27 release notes;
- `os.Root` docs;
- `os.File.Sync` / `os.Rename` docs;
- package docs for stdlib APIs;
- Zero Dependency official context pack.

Prefer `go.dev` / `pkg.go.dev` and official hackathon docs.

## Skills not required

Do not install a general framework/code-generation skill merely to produce:

- CLI parsing;
- lexer/parser;
- filesystem operations;
- transaction journal;
- JSON;
- docs site.

These are exactly the layers the hackathon wants implemented with standard-library primitives.

An OpenAI docs skill is irrelevant unless the product later integrates OpenAI APIs; UndoLang v1 must not do so.

## Runtime MCP: explicitly no

UndoLang does not need to run as an MCP server for the hackathon.

AI agents can integrate universally through:

```text
undo capabilities --json
undo schema --json
undo check ... --json
undo plan ... --json
undo run ... --yes --json
undo recover ... --json
```

This requires only the `undo` binary and no SDK/protocol package.

Post-hackathon, an MCP adapter could be a separate optional project/artifact, but it should not contaminate the core dependency model.

## Important distinction

Development tools used by Codex are not shipped runtime dependencies, but they still must not cause copied/vendored third-party runtime code to land in the repository.

Before final submission, audit source/imports independently of what tools were used to author code.
