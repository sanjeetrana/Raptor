# UndoLang Security, Threat Model, and Edge-Case Specification

UndoLang is a tool that intentionally mutates files. Safety requirements are therefore part of core correctness, not optional hardening.

---

## 1. Threat model

### Protect against

- accidental path traversal (`../`);
- symlink-based escape from a transaction root;
- malicious or untrusted `.undo` files attempting to touch undeclared filesystem locations;
- accidental overwrite/delete caused by ambiguous destinations;
- partial transactions caused by process crash, power loss, I/O error, permission failure, or disk exhaustion;
- torn/incomplete journal tail;
- corrupted journal content;
- concurrent UndoLang transaction on same root;
- agent-generated malformed/mis-scoped plans;
- secrets being echoed into logs/JSON;
- large files causing unbounded memory use;
- recursive directory cycles via symlinks;
- operations targeting UndoLang's own state/backup directory.

### Not fully protect against

- malicious kernel/filesystem;
- root/admin adversary modifying UndoLang state concurrently;
- arbitrary other processes intentionally racing target paths;
- hardware corruption beyond what checksums detect;
- full filesystem isolation or atomic visibility;
- ACL/xattr/ownership fidelity on all platforms;
- attackers who can replace the UndoLang executable itself.

---

## 1.1 Multi-transaction program safety boundary

A `.undo` program may contain several transactions, but only the **current transaction** is a rollback boundary. Whole-file execution is sequential and fail-fast.

- entire source syntax/semantics are validated before first mutation;
- every transaction receives fresh state-sensitive preflight immediately before it starts;
- a failed current transaction rolls back only itself;
- earlier committed transactions remain committed;
- later transactions are not started;
- script authors cannot supply arbitrary rollback commands; runtime-owned recovery derives from captured prior state and journal records.

This prevents a later failure from causing dangerous attempts to reverse already finalized earlier transactions after other processes may have observed or modified their results.

## 2. Filesystem capability policy

Use `os.Root` / `os.OpenRoot` for traversal-resistant operations within declared roots.

Never implement path security only with string-prefix checks.

Rules:

- relative path -> primary root;
- absolute path inside primary root -> map to primary root;
- absolute path outside primary root -> require explicit `--allow-path` root;
- select most-specific matching capability root;
- actual operation uses path relative to that `os.Root`;
- reject reserved `.undo` subtree;
- reject empty path where it would mean root itself;
- reject mutation of a capability-root directory itself unless explicitly designed; recommended v1: disallow deleting/moving the root itself.

---

## 3. Symlinks

### Required cases

- relative symlink that remains inside root;
- symlink pointing outside root;
- symlink chain;
- broken symlink;
- symlink introduced between planning and execution;
- parent directory replaced by symlink after plan;
- symlink to reserved `.undo` state;

### Policy

`os.Root` is the enforcement boundary for actual operations. Revalidate operation state immediately before mutation.

Recommended v1:

- `delete`: removes symlink entry, not target;
- `move`: moves link entry;
- `copy`: reject symlink source unless safe-preservation implementation is complete and tested;
- directory traversal never follows symlink directories implicitly;
- conditions must have documented `Stat`/`Lstat` behavior.

Do not use `filepath.EvalSymlinks` as the sole defense; it can create TOCTOU gaps between validation and mutation.

---

## 4. Race conditions / TOCTOU

Planning is advisory; execution must revalidate assumptions after lock acquisition.

Examples:

- destination appears after plan;
- source disappears;
- source hash changes;
- file becomes symlink;
- destination changes type;
- external process changes directory tree.

If current state no longer matches plan, fail before applying that operation and rollback already applied operations.

UndoLang does not claim isolation from arbitrary external processes.

---

## 5. Reserved state

State directory must be protected from DSL mutation.

Reject:

```text
copy "x" -> ".undo/..."
delete ".undo"
move ".undo" -> "..."
replace ".undo/..."
```

Also reject equivalent canonical/absolute paths.

State directory permissions:

- directories `0700` where supported;
- files `0600` where supported;
- Windows uses platform ACL inherited semantics; document that POSIX mode bits are not equivalent to Windows ACLs.

---

## 6. Secrets

UndoLang may transact private keys/config secrets.

Rules:

- never print file contents by default;
- `replace` output reports path and match count, not matched secret text unless input literal itself came from script and user explicitly asked to inspect source;
- journal stores paths/hashes/backup references, not duplicated content bodies;
- backups are protected and removed after safe finalization according to retention policy;
- crash/recovery failure retains backups for safety, and CLI tells user where sensitive backup data remains;
- marketing/demo examples must use fake/non-sensitive values.

---

## 7. Journal integrity cases

Test and handle:

- zero-byte journal;
- valid header + no records;
- incomplete header;
- incomplete payload;
- missing CRC;
- CRC mismatch at EOF;
- CRC mismatch in middle;
- duplicate sequence;
- sequence gap;
- unsupported format version;
- unknown record type;
- transaction ID mismatch between metadata and journal;
- operation ID referenced before definition;
- rollback record without prepared/applied operation.

Fail closed when recovery intent is ambiguous.

---

## 8. Filesystem object types

Required supported:

- regular files;
- directories;
- symlink delete/move policy as documented.

Reject unless explicitly implemented/tested:

- FIFO/named pipe;
- Unix socket;
- block device;
- character device;
- reparse-point variants with unsafe semantics;
- special Windows device names.

Use `io/fs.FileMode` type bits.

---

## 9. Hard links

V1 may copy file contents and lose hard-link identity.

Document this. Do not promise inode/link-count preservation.

Rollback of an overwritten hard-linked file can alter link topology if implemented naively; safest hackathon policy is to detect `Nlink` where portably available only via platform-specific `Sys()` (not portable) or document that hard-link identity is outside guarantee. If tests reveal dangerous behavior, reject known hard-link cases on supported Unix via build-tagged checks rather than silently corrupt topology.

---

## 10. Permissions and metadata

Preserve basic mode bits for ordinary files/directories where supported.

Do not claim universal preservation of:

- owner/group;
- ACLs;
- xattrs;
- SELinux labels;
- macOS resource forks;
- Windows alternate data streams;
- sparse-file allocation;
- birth time.

If these are material to a use case, README must warn that v1 is not appropriate.

---

## 11. Case-insensitive filesystems

Potential collision:

```text
move "Foo" -> "foo"
```

Behavior differs by filesystem/OS. Detect obvious same-path-after-clean cases; platform-specific case behavior must be tested and documented.

Do not implement custom Unicode case-fold assumptions for filesystem identity.

---

## 12. Windows path cases

Test:

- drive absolute paths;
- UNC paths if supported;
- reserved names (`CON`, `NUL`, `COM1` etc.);
- path separator mixtures;
- destination file open by another process;
- rename/replacement failure;
- read-only files;
- long paths depending on OS settings.

Use raw strings in DSL examples for Windows paths.

---

## 13. Cross-device operations

`move` may fail across filesystems/volumes.

Do not advertise atomic cross-device move.

Allowed implementation:

- detect rename failure representing cross-device/unsupported move;
- if fallback is confidently identified and safe: copy destination fully + sync + verify, then delete source with durable journal transitions;
- otherwise return an actionable error and rollback.

Never respond to an arbitrary rename error by blindly performing copy+delete; permission/conflict errors are not equivalent to EXDEV.

---

## 14. Disk-full / ENOSPC

Critical test cases:

- backup creation runs out of space;
- temp replacement runs out of space;
- journal write runs out of space;
- journal sync fails;
- rollback itself encounters space issue.

Rule: no destructive mutation may start if required backup preparation has not completed. If journal durability cannot be established, stop.

Portable free-space preflight is limited in stdlib; estimate backup bytes and handle real I/O errors safely rather than inventing universal free-space logic.

---

## 15. Read-only / permission cases

Test:

- read-only source;
- unwritable destination parent;
- unreadable source required for backup;
- state directory cannot be created;
- state journal cannot sync;
- permission changes during transaction.

Errors must distinguish path policy from OS permission failure where possible.

---

## 16. Very large files

No `os.ReadFile` for file-copy/hash/contains/replace paths that may be large.

Use streaming.

Tests should assert memory does not scale linearly with file size for core streaming operations.

---

## 17. Very large directories

Avoid recursive function depth tied directly to adversarial tree depth where practical. `WalkDir` or explicit stack preferred.

Do not follow symlink loops.

Plan may enumerate filesystem entries; document memory cost. Stress test at least tens of thousands of files and target 100k.

---

## 18. Self-referential operations

Reject:

- `copy dir -> dir/subdir`;
- `move dir -> dir/subdir`;
- source == destination;
- operations that use a path after an earlier operation makes it unavailable unless planner can transform references unambiguously (recommended v1: reject conflicting plan);
- moving a parent while later referencing a child via old path;
- deleting parent then writing child.

---

## 19. Duplicate mutations

Recommended conservative v1 planner policy:

- reject multiple destructive mutations targeting same canonical path unless a clearly defined sequence is explicitly supported;
- reject destination overlap that makes rollback ambiguous;
- allow postconditions to read mutated paths.

Less permissive but easier to guarantee correctly.

---

## 20. Replace edge cases

Test:

- empty old pattern -> reject;
- old == new;
- pattern absent -> fail;
- overlapping pattern (`aaa` replace `aa`);
- pattern crosses chunk boundary;
- replacement longer than source pattern;
- replacement shorter;
- binary/non-UTF8 target content (operation is literal bytes; source DSL strings encode UTF-8 bytes);
- huge file;
- zero-byte file.

Define non-overlapping left-to-right semantics exactly.

---

## 21. Parser adversarial cases

Test:

- invalid UTF-8;
- unterminated string;
- unknown escape;
- unterminated raw string;
- extra top-level transaction;
- missing brace;
- unknown keyword;
- misspelled operation;
- require after mutation;
- mutation after assert;
- comments after strings;
- `#` inside string;
- arrow split by whitespace if grammar does/does not allow it;
- extremely long token;
- deeply malicious input without causing panic.

Parser must never panic on user input.

---

## 22. Agent safety

`--json` does not mean auto-approve.

For `run` in noninteractive/JSON automation:

- require `--yes` or explicit documented approval flag;
- output plan summary in result;
- never silently grant absolute-path access;
- agent cannot request undeclared external root from inside `.undo` source; capabilities come from operator CLI invocation.

This separation prevents a downloaded `.undo` file from self-authorizing access to `/etc`, home directories, etc.

---

## 23. Recovery safety

Recovery must be idempotent.

If interrupted during rollback:

- journal rollback prepared/applied states;
- next recovery resumes from valid durable records;
- never reapply an inverse blindly if its prior completion can be determined;
- verify filesystem state before continuing.

If uncertainty remains, stop and preserve backups.

---

## 24. Platform guarantee language

README should say something like:

> UndoLang provides a durable journal, protected backup/staging state, verification, rollback on known failures, and explicit crash recovery for supported filesystem objects. It does not make arbitrary multi-file changes atomically invisible to other processes. Filesystem durability and rename semantics vary by operating system/filesystem; the documented support matrix describes tested guarantees.

Do not use the phrase “full ACID filesystem transactions” for v1.
