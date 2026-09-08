# Support Matrix

| Platform | Build status | Behavioral status |
|---|---|---|
| macOS arm64 | Built with Go 1.27, CGO disabled | Full tests, race detector, filesystem integration, and real crash/recovery matrix run locally |
| macOS amd64 | Cross-build target | Not behavior-tested in this environment |
| Linux amd64/arm64 | Cross-build target | Not behavior-tested in this environment |
| Windows amd64 | Cross-build target | Not behavior-tested in this environment; rename, open-handle, reparse-point, and directory-sync behavior require real Windows validation |

Cross-compilation proves buildability only. It does not establish filesystem durability or recovery behavior on that operating system.

All platforms share these v1 limits: no isolation/atomic visibility claim, one active transaction per primary root, no symlink copy or special-file mutation, and no preservation guarantee for ownership, ACLs, xattrs, sparse allocation, timestamps, resource forks, alternate streams, or hard-link identity.
