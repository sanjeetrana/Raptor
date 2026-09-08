# Security

## Scope and assumptions

MiniKV is a **local, single-process, embedded** storage engine. It is not
a network service (unless the optional dashboard is enabled, in which
case see the "Local dashboard" section below), and it assumes the process
running it is trusted — MiniKV performs no authentication or
authorization of its own. It relies entirely on the host OS's filesystem
permissions to control who can read or write its data files.

## Threat model

### Malicious or corrupted database files

MiniKV validates every record it reads: magic bytes, format version,
operation code, declared key/value lengths (capped at sane maxima — see
`maxKeyLen`/`maxValueLen` in `record.go`), and a CRC-32 checksum over the
whole record. A file that has been corrupted (by disk errors, a crash
mid-write, or hand-editing) is detected and the log is truncated at the
first bad record rather than trusted further. See
`internal/engine/recovery.go`.

**This is corruption detection, not tamper-proofing.** CRC-32 is
deliberately not a cryptographic checksum. An adversary who can write
arbitrary bytes to the database file *and* recompute a matching CRC-32 can
forge a record that will be accepted as valid. MiniKV does not claim
otherwise. If tamper-evidence against a malicious actor with file write
access is a requirement, that is out of scope for this project and would
need a keyed MAC (e.g. HMAC) added to the record format — a change that
was deliberately not made here, since it wasn't necessary for the
project's actual threat model (accidental corruption, not adversarial
tampering).

### Resource exhaustion

Declared key and value lengths in a record header are capped
(`maxKeyLen` = 1 MiB, `maxValueLen` = 256 MiB) specifically so that a
corrupted length field cannot cause the reader to attempt an
unreasonably large allocation during recovery. A record whose declared
length exceeds these caps is treated as invalid and recovery stops there,
the same as any other corruption.

There is currently no limit on total database file size or on the number
of keys held in memory (the index holds one entry per live key). A
process with an extremely large keyspace could exhaust memory; this is a
known limitation, not a hardened boundary.

### Filesystem permissions

MiniKV creates its database and backup files with mode `0600`
(owner read/write only). It does not change permissions on files it
didn't create, and it does not attempt to enforce any access control
beyond what the OS already provides via file permissions.

### Backup sensitivity

A MiniKV backup file is a byte-for-byte copy of the live database log,
including every value ever written (until compaction removes superseded
records). Anyone who can read a backup file can read everything currently
stored — MiniKV does not encrypt data at rest, in the live database or in
backups. If the data being stored is sensitive, encrypting the file at
the filesystem/disk level (or encrypting values before calling `Set`) is
the caller's responsibility.

### Restore safety

`minikv restore` validates a backup structurally before using it (see
`ValidateBackup` in `backup.go`) and preserves any existing database file
at the target path (renamed with a `.preRestore.<timestamp>` suffix)
rather than deleting it, so a bad or mistaken restore doesn't destroy
data irrecoverably.

### Local-machine assumptions

MiniKV assumes:

- A single OS process accesses a given database file at a time. Two
  processes opening the same file concurrently is not supported (their
  in-memory indexes would each be inconsistent with the other's writes)
  and will likely produce a corrupted-looking log for whichever process
  reads it second, even though each individual write is still a valid
  record.
- `os.Rename` (used for atomic compaction and restore) is atomic — true
  on the same local filesystem on Linux, macOS, and Windows, but not
  guaranteed across network filesystems (NFS, SMB, etc.).
- The underlying storage medium honors `fsync` — true for essentially
  all real disks and most virtualized/cloud block storage, but not
  guaranteed for every possible storage backend.

## Local dashboard (if implemented)

If the optional `net/http`-based dashboard is present, it binds to a
local address and serves read-only statistics. It performs no
authentication — anyone who can reach the bound address and port can view
the dashboard. It is intended for local development use, not for
exposure on an untrusted network.

## Not claimed

MiniKV does **not** claim: encryption at rest, tamper-proof integrity
(only corruption detection), multi-process safety, network-level access
control, or protection against a malicious actor with local filesystem
write access to its data files.
