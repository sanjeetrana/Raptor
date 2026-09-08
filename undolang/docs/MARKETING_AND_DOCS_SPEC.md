# UndoLang Static Marketing + Documentation Specification

## 1. Constraint

The marketing/docs site must itself embody the zero-dependency philosophy.

Use only:

- HTML5
- CSS
- vanilla browser JavaScript where genuinely useful

Do not use:

- npm/package.json
- React/Next.js/Vue/Svelte/Astro
- Tailwind/Bootstrap
- Vite/Webpack/esbuild
- Prism/highlight.js
- external icon package
- external web fonts required for rendering
- analytics SDK
- cloud API

The pages should work as static files and on GitHub Pages.

## 2. Folder

```text
marketing/
  index.html
  assets/
    styles.css
    site.js
  docs/
    index.html
    getting-started.html
    language.html
    transactions.html
    paths.html
    agents.html
    security.html
    limitations.html
```

Avoid duplicating a fake JavaScript implementation of the DSL. A “playground” is not required; if added later it must not pretend to be the real runtime.

## 3. Visual direction

Developer-tool aesthetic:

- clean typography using system font stack;
- high-contrast dark/light behavior optional via CSS preferences;
- strong monospace code treatment;
- restrained motion;
- responsive from mobile to desktop;
- accessible focus states;
- no gratuitous hackathon gradients that make it feel like a toy.

## 4. Landing page story

### Hero

Headline recommendation:

> Filesystem changes should either finish or recover.

Supporting line:

> UndoLang is a crash-safe transaction runtime and tiny DSL for reversible filesystem automation — plan changes, apply them, verify the result, and roll back when execution fails.

Primary actions:

- Get Started
- Read Docs
- View GitHub

### Immediate code example

Prefer a real multi-transaction program showing `prepare`, `upgrade`, and `cleanup`, then show both:

```bash
undo run migration.undo
undo run migration.undo --transaction upgrade
```

Explain in one sentence: the file is the program; each transaction is its own rollback boundary. Use syntax that passes the real parser.

### Problem comparison

Show:

```text
ordinary script:
move ✓
rewrite ✓
delete ✓
create ✕
=> half-migrated state
```

versus:

```text
UndoLang:
PLAN -> JOURNAL -> APPLY -> VERIFY -> COMMIT
                              \\ failure
                               -> ROLLBACK
```

### Real use cases

Prioritize:

- application upgrades;
- AI-agent refactors;
- config migrations;
- local data-layout migrations.

Do not claim it replaces databases, Git, filesystem snapshots, or full deployment frameworks.

### Zero-dependency section

State real facts:

- one native Go binary;
- Go stdlib only;
- no database/daemon/cloud;
- no runtime package install;
- website is static/no package framework.

## 5. Docs content

### Getting Started

- download/build;
- `undo check`;
- `undo plan`;
- `undo run`;
- recovery basics.

### Language

Exact grammar/operations/conditions, copied from current generated language docs, not stale marketing prose.

### Programs & Transactions

Document:

- one `.undo` file can contain one or more named transactions;
- whole-file source-order execution;
- `--transaction` selection;
- fail-fast behavior;
- prior committed transactions are not retroactively rolled back;
- later state-sensitive planning is deferred until execution.

### Transactions

Explain:

- preconditions;
- plan;
- journal;
- operation execution;
- assertions;
- commit;
- rollback;
- crash recovery;
- what is and is not atomic.

### Paths

Explain root and capabilities clearly:

```bash
undo run migrate.undo --root /opt/app --allow-path /etc/myapp
```

Explain relative vs absolute paths and why script location is independent.

### AI Agents

Show:

```text
agent -> schema/capabilities -> writes .undo -> check --json -> plan --json -> approval -> run --json
```

Document stable error/exit behavior.

### Security

- traversal-resistant roots;
- no shell escape;
- no network;
- reserved state;
- protected backups;
- symlink policy.

### Limitations

Must prominently include actual v1 limits:

- no atomic visibility/isolation across arbitrary files;
- platform rename/fsync differences;
- unsupported metadata types;
- single active transaction per root;
- no arbitrary shell commands;
- tested platform matrix.

## 6. Accessibility

- semantic headings;
- keyboard navigation;
- visible focus;
- sufficient contrast;
- avoid content only communicated by color;
- `prefers-reduced-motion` for animation;
- copy buttons optional, implemented in vanilla JS with graceful fallback.

## 7. Security/privacy

- no analytics by default;
- no external script tags;
- no third-party embeds needed;
- no user data collection.

## 8. Documentation correctness gate

Before finalization:

- parse every `.undo` snippet used in docs as part of tests if practical;
- compare CLI flags in docs with `--help`;
- compare JSON examples with actual output schema;
- remove unsupported feature claims.
