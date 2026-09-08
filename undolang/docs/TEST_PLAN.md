# UndoLang Test Plan

Use only Go standard-library testing. Tests must exercise real implementation behavior; production code must not contain fake backends or mocked transaction engines.

## 1. Test philosophy

- Unit-test pure lexer/parser/planner logic.
- Use real temporary directories (`testing.T.TempDir`) for filesystem integration.
- Use real compiled subprocesses for black-box CLI tests.
- Use real process termination for crash/recovery tests.
- Do not call external tools such as `cp`, `mv`, `sed`, `git`, `rsync` as part of product behavior.
- Tests may use Go toolchain commands as development/build tooling.
- Every bug discovered gets a regression test.
- Fuzz where Go stdlib makes it useful, especially lexer/parser/journal decoder.

## 2. Required command gate

```bash
GOPROXY=off go test ./...
GOPROXY=off go test -race ./...      # where supported by the environment/toolchain
GOPROXY=off go vet ./...
```

Race detector is Go toolchain functionality, not a runtime dependency. If cross-compilation or platform limitations prevent it, document that honestly.

## 3. Lexer tests

Cover:

- every keyword;
- arrow/equal/braces;
- whitespace/newlines;
- comments;
- quoted escapes;
- raw strings;
- Windows backslash paths;
- invalid UTF-8;
- unknown escapes;
- unterminated strings/raw strings;
- line/column correctness across CRLF and LF;
- very long tokens;
- random byte input never panics.

Use Go fuzz tests for lexer panic resistance.

## 4. Parser tests

Golden/table tests for:

- minimal valid transaction;
- all conditions;
- all operations;
- overwrite modifier;
- multiline formatting;
- comments interspersed;
- missing transaction name;
- missing braces;
- malformed operation arity;
- one transaction;
- multiple top-level transactions preserve source order;
- duplicate transaction names rejected;
- trailing garbage;
- precise error spans.

## 5. Semantic validator tests

- require after mutation -> rejected;
- mutation after assert -> rejected;
- invalid SHA-256 length/hex -> rejected;
- empty replace old pattern -> rejected;
- empty transaction name -> rejected;
- duplicate transaction name -> rejected;
- invalid/empty critical path strings -> rejected;
- unsupported constructs -> rejected explicitly.

## 6. Path capability tests

On each supported OS where possible:

- relative path under root succeeds;
- absolute path under root succeeds;
- absolute external path denied without `--allow-path`;
- allowed external path succeeds;
- `../` escape denied;
- nested `a/../../` escape denied;
- symlink inside root to inside root behaves per policy;
- symlink inside root to outside root denied;
- reserved `.undo` access denied;
- script file outside root still operates against chosen root;
- most-specific allowed root mapping works;
- Windows drive/reserved-name cases.

## 7. Planner tests

- source missing;
- destination exists without overwrite;
- overwrite plan marks destructive and backup requirement;
- directory copied into descendant -> reject;
- source == destination -> reject;
- delete parent then use child -> reject;
- move parent then use old child -> reject;
- duplicate writers -> conservative reject;
- estimated counts/bytes accurate for fixtures;
- `plan` leaves target tree byte-for-byte/metadata unchanged where test can verify.

## 8. Operation integration tests

### mkdir

- create new;
- existing directory idempotent;
- existing file error;
- parent chains correctly journaled/inverted.

### copy file

- contents exact;
- empty file;
- large file;
- mode preservation where supported;
- overwrite backup/rollback;
- destination collision.

### copy directory

- nested files;
- empty dirs;
- symlink policy;
- large file count;
- no recursion outside source root.

### move

- file;
- directory;
- overwrite;
- rename failure;
- cross-device behavior when test environment can provide two filesystems; otherwise isolate fallback logic and clearly document untested platform path.

### write

- create;
- replace existing;
- newline/escape content;
- rollback restores previous bytes.

### replace

- one match;
- many matches;
- no match;
- old == new;
- overlapping source pattern;
- chunk-boundary match;
- huge file;
- replacement grows/shrinks file;
- rollback restores exact original SHA-256.

### delete

- file;
- empty dir;
- recursive directory tree;
- symlink itself;
- missing path;
- rollback restoration.

## 9. Condition tests

- exists/not_exists;
- file/dir distinction;
- contains chunk-boundary match;
- contains absent;
- SHA-256 correct/wrong;
- huge file hashing bounded memory;
- capability escape attempts.

## 10. Multi-transaction program tests

Required cases:

1. `check` accepts 1, 2, and many transactions and returns names in source order;
2. duplicate transaction name is rejected before mutation;
3. `run FILE --transaction B` executes only B while still requiring the entire source to parse/validate;
4. `run FILE` executes A then B then C in source order;
5. B precondition fails -> A remains committed, B makes zero mutations, C is skipped;
6. B real filesystem operation fails -> B rolls back, A remains committed, C is skipped;
7. B assertion fails -> B rolls back, A remains committed, C is skipped;
8. crash during B -> recovery concerns B only; A remains committed; C never started;
9. whole-program JSON reports started transaction IDs/states and `skipped` entries after failure;
10. `plan FILE --transaction B` is exact against current state;
11. multi-transaction `plan FILE` marks later state-sensitive checks deferred instead of falsely safe;
12. a later transaction can validly depend on state committed by an earlier transaction because `run` freshly plans it immediately before execution.

## 11. Transaction integration tests

Required full-flow cases:

1. all operations succeed -> commit;
2. first mutation fails -> no earlier mutation to roll back;
3. middle mutation fails -> prior mutations restored;
4. final mutation fails -> all prior mutations restored;
5. precondition fails -> zero mutation;
6. postcondition fails -> complete rollback;
7. rollback itself encounters controlled real filesystem obstacle -> status `RECOVERY_FAILED`, backups retained;
8. second transaction while active -> blocked;
9. stale unresolved lock -> recovery required;
10. successful finalization clears active lock.

## 12. Real crash tests

Do not ship a production `--fail-after` demo flag.

Recommended test approach:

- build a small test-only helper command or run the real CLI under a test harness;
- coordinate with a sentinel file/journal state so parent test knows an operation was applied;
- terminate child process with OS process kill;
- invoke `undo recover` as a fresh process;
- compare restored tree against pre-transaction snapshot/hash fixture.

Crash points to cover:

- after TX_BEGIN sync;
- after backup sync but before OP_PREPARED;
- after OP_PREPARED sync before mutation;
- after mutation before OP_APPLIED sync;
- after OP_APPLIED;
- during second/third operation;
- during VERIFYING;
- during rollback after one inverse;
- after final rollback record before lock cleanup.

Where exact kill coordination is platform-specific, use build-tagged test helpers while keeping production semantics identical.

## 13. Journal decoder tests

Construct frames with our own encoder, then mutate bytes for:

- torn header;
- torn payload;
- torn checksum;
- checksum mismatch;
- middle-frame corruption;
- sequence gap;
- unknown version;
- unknown type;
- extra garbage at tail;
- giant payload length attempting memory exhaustion (decoder must cap lengths).

Fuzz journal decoder; it must never panic or allocate unbounded memory based on untrusted length fields.

## 14. CLI black-box tests

Build `undo` and invoke as subprocess.

Verify:

- help/version;
- exit codes;
- stdout/stderr separation;
- `--json` parses as valid JSON;
- JSON error codes;
- no prompt in noninteractive JSON path;
- `run --json` without explicit approval fails safely if designed to require `--yes`;
- `NO_COLOR` / `--no-color`;
- any `.undo` path location works;
- root semantics independent of script directory.

## 15. Agent contract tests

Snapshot the *schema shape* semantically (not brittle pretty formatting):

- `capabilities --json` contains operations/conditions/version;
- `schema --json` describes all grammar constructs;
- error objects always contain `code` and `message`;
- selected/single-transaction plan JSON contains transaction-level `safe_to_execute`; multi-transaction ProgramPlan exposes `safe_to_start` and per-transaction readiness/deferred state, plus effects/root/capabilities;
- stable API version.

## 16. Scale tests

Keep default CI reasonable, with heavier tests opt-in if necessary.

Targets:

- 100k small files planner/walker test where environment permits;
- >=256 MiB file copy/hash/replace stress case (can be sparse/generated inside test without repository fixture);
- assert bounded allocations/memory indirectly with benchmarks and no `ReadFile` path in implementation;
- deeply nested paths near practical limits;
- long filenames within OS limits.

## 17. Cross-platform test matrix

Minimum manual/CI target:

| OS | amd64 | arm64 |
|---|---|---|
| Linux | required | build required, test when available |
| macOS | build/test when available | required target for releases |
| Windows | required behavior validation | optional release target if toolchain supports |

Do not claim a platform “supported” based solely on cross-compilation if crash/path behavior has never run there. Distinguish **build target** from **tested support** in docs.

## 18. Reproducible build test

Canonical script:

1. verify clean dependency state;
2. build output A with exact flags;
3. build output B with exact flags;
4. SHA-256 both using a stdlib helper or platform tool in script; preferable: a tiny Go stdlib command/script or `sha256sum` only as documented developer convenience;
5. assert byte-identical hashes;
6. publish outputs in `reproducible-build.txt`.

For maximum zero-dep purity, implement the hash comparison in a Go test/helper using `crypto/sha256` rather than requiring `sha256sum`.

## 19. Dependency proof test

Required evidence:

```bash
go list -m all
GOPROXY=off go test ./...
GOPROXY=off go build -trimpath -buildvcs=false ./cmd/undo
```

Expected `go list -m all`: only the main module.

Also grep imports/build metadata in review to ensure no external executable shell-outs are hidden.

## 20. Acceptance gate before marketing polish

Do not spend final hours polishing site before these pass:

- parser all tests;
- path escapes rejected;
- all six operations integration tested;
- known failure rollback tested;
- real kill/recovery tested;
- JSON API tested;
- network-disabled build/test passes;
- no external module in go.mod.
