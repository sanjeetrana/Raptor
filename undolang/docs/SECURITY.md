# Security Model and Limitations

UndoLang grants filesystem capabilities explicitly. Relative paths bind to `--root` or the invocation working directory. Absolute paths outside that root require a repeatable `--allow-path` directory capability. The script location never changes the root.

Actual access uses Go 1.27 `os.OpenRoot`/`os.Root`; string-prefix checks are not the security boundary. Lexical `..` escapes, undeclared absolute paths, symlink parent traversal, root mutation, and the reserved `.undo` state tree are rejected.

The language has no shell execution, imports, plugins, package loading, networking, environment interpolation, or hidden service credentials. Diagnostic and JSON output report paths and hashes where useful but never print target file contents.

## Filesystem objects

Regular files and directories are supported. Moving and deleting a symlink operates on the link entry, including when its target is external or reserved; the target is never changed. Content/type conditions do not dereference symlinks. Symlink copying, FIFOs, sockets, devices, and unsafe platform-specific reparse objects are rejected.

Basic permission bits are preserved where supported. Ownership, ACLs, xattrs, SELinux labels, sparse allocation, resource forks, alternate streams, timestamps, and hard-link identity are outside the v1 guarantee.

## Concurrency

Only one active transaction is allowed per primary root. Separate roots with overlapping external `--allow-path` capabilities can still race; UndoLang does not claim a global lock or filesystem isolation. Important assumptions are revalidated after locking and before mutation, but unrelated applications can still change files concurrently. Ambiguous rollback state fails closed.

## Sensitive workloads

Backups live under the protected root in `.undo/transactions/<txid>/backup` with restrictive modes where supported. They are removed only after a verified commit or rollback and retained after corruption or recovery failure. Users requiring exact metadata or confidentiality guarantees beyond local filesystem permissions should use a platform-native snapshot/security facility instead.
