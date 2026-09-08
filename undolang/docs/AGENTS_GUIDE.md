# Using UndoLang from an AI Agent

UndoLang gives an agent an inspectable boundary between generated intent and mutation.

```text
capabilities -> schema -> author -> check -> plan -> approval -> run -> inspect/recover
```

Recommended workflow:

```sh
undo capabilities --json
undo schema --json
undo check change.undo --root /workspace --json
undo plan change.undo --root /workspace --json
undo run change.undo --root /workspace --yes --json
```

Never infer approval from `--json`; noninteractive mutation also requires `--yes`. For a multi-transaction plan, only the first transaction is exact and later state-sensitive entries are deferred. During `run`, every transaction receives a fresh exact plan immediately before it starts.

Read `api_version`, `ok`, stable error `code`, and ordered transaction results rather than parsing prose. A failed transaction may report `rolled_back`, `recovery_required`, or `recovery_failed`; later transactions appear as `skipped`. If recovery is required, stop new mutation and run `undo recover --root ROOT --yes --json`.

The DSL cannot execute commands or access the network. Generate only operations described by `schema --json`, use explicit capabilities, prefer strong preconditions such as SHA-256 for sensitive edits, and present destructive effects and rollback estimates to the human approver.

