package cli

import (
	"bufio"
	"io"
	"os"
	"strings"
	"time"

	"minikv/internal/engine"
)

// Version is the MiniKV CLI version string, reported by "minikv version".
const Version = "0.1.0"

const usage = `MiniKV — a tiny storage engine built from the ground up.

Usage:
  minikv [--db PATH] [--sync] <command> [args]

Commands:
  set <key> <value> [--ttl SECONDS]   Store a value, optionally with expiry
  get <key>                           Retrieve a value
  delete <key>                        Remove a key
  exists <key>                        Check whether a key is present
  list                                List all live keys
  stats                               Show database statistics
  backup <destination>                Copy the database log to a new file
  restore <backup>                    Restore the database from a backup
  compact                             Rewrite the log, dropping dead data
  shell                               Start an interactive MiniKV shell
  help                                Show this help text
  version                             Show the MiniKV version

Global flags:
  --db PATH     Path to the database file (default: minikv.db)
  --sync        Fsync after every write (see README.md "Durability")
`

// Run executes a MiniKV CLI invocation and returns a process exit code.
func Run(args []string, stdout, stderr io.Writer) int {
	args, globals, err := extractGlobalFlags(args)
	if err != nil {
		println(stderr, "error:", err)
		return ExitUsage
	}

	if len(args) == 0 {
		println(stdout, strings.TrimRight(usage, "\n"))
		return ExitUsage
	}

	cmd, rest := args[0], args[1:]

	switch cmd {
	case "help", "-h", "--help":
		println(stdout, strings.TrimRight(usage, "\n"))
		return ExitOK
	case "version", "-v", "--version":
		println(stdout, "minikv version", Version)
		return ExitOK
	case "backup":
		return runBackup(rest, globals, stdout, stderr)
	case "restore":
		return runRestore(rest, globals, stdout, stderr)
	}

	// Every other command needs an open database.
	db, err := engine.Open(globals.DBPath, engine.Options{Sync: globals.Sync})
	if err != nil {
		println(stderr, "error: could not open database:", err)
		return ExitError
	}
	defer db.Close()

	switch cmd {
	case "set":
		return runSet(rest, db, stdout, stderr)
	case "get":
		return runGet(rest, db, stdout, stderr)
	case "delete":
		return runDelete(rest, db, stdout, stderr)
	case "exists":
		return runExists(rest, db, stdout, stderr)
	case "list":
		return runList(rest, db, stdout, stderr)
	case "stats":
		return runStats(rest, db, stdout, stderr)
	case "compact":
		return runCompact(rest, db, stdout, stderr)
	case "shell":
		return runShell(db, stdout, stderr)
	default:
		println(stderr, "error: unknown command:", cmd)
		println(stderr, strings.TrimRight(usage, "\n"))
		return ExitUsage
	}
}

func runSet(args []string, db *engine.Database, stdout, stderr io.Writer) int {
	args, ttlSeconds, err := extractTTL(args)
	if err != nil {
		println(stderr, "error:", err)
		return ExitUsage
	}
	if len(args) != 2 {
		println(stderr, "usage: minikv set <key> <value> [--ttl SECONDS]")
		return ExitUsage
	}
	key, value := args[0], args[1]
	err = db.Set([]byte(key), []byte(value), time.Duration(ttlSeconds)*time.Second)
	if err != nil {
		println(stderr, "error:", err)
		return ExitError
	}
	println(stdout, "OK")
	return ExitOK
}

func runGet(args []string, db *engine.Database, stdout, stderr io.Writer) int {
	if len(args) != 1 {
		println(stderr, "usage: minikv get <key>")
		return ExitUsage
	}
	value, err := db.Get([]byte(args[0]))
	if err == engine.ErrNotFound {
		println(stderr, "not found (missing or expired)")
		return ExitNotFound
	}
	if err != nil {
		println(stderr, "error:", err)
		return ExitError
	}
	println(stdout, string(value))
	return ExitOK
}

func runDelete(args []string, db *engine.Database, stdout, stderr io.Writer) int {
	if len(args) != 1 {
		println(stderr, "usage: minikv delete <key>")
		return ExitUsage
	}
	err := db.Delete([]byte(args[0]))
	if err == engine.ErrNotFound {
		println(stderr, "not found (missing or expired)")
		return ExitNotFound
	}
	if err != nil {
		println(stderr, "error:", err)
		return ExitError
	}
	println(stdout, "OK")
	return ExitOK
}

func runExists(args []string, db *engine.Database, stdout, stderr io.Writer) int {
	if len(args) != 1 {
		println(stderr, "usage: minikv exists <key>")
		return ExitUsage
	}
	ok, err := db.Exists([]byte(args[0]))
	if err != nil {
		println(stderr, "error:", err)
		return ExitError
	}
	if ok {
		println(stdout, "true")
		return ExitOK
	}
	println(stdout, "false")
	return ExitNotFound
}

func runList(args []string, db *engine.Database, stdout, stderr io.Writer) int {
	if len(args) != 0 {
		println(stderr, "usage: minikv list")
		return ExitUsage
	}
	for _, k := range db.List() {
		println(stdout, k)
	}
	return ExitOK
}

func runStats(args []string, db *engine.Database, stdout, stderr io.Writer) int {
	if len(args) != 0 {
		println(stderr, "usage: minikv stats")
		return ExitUsage
	}
	s := db.Stats()
	printf(stdout, "path:              %s\n", s.Path)
	printf(stdout, "live keys:         %d\n", s.LiveKeys)
	printf(stdout, "expired keys:      %d\n", s.ExpiredKeys)
	printf(stdout, "log size (bytes):  %d\n", s.LogSizeBytes)
	printf(stdout, "sync mode:         %v\n", s.SyncMode)
	printf(stdout, "records replayed:  %d\n", s.RecordsReplayed)
	printf(stdout, "tombstones seen:   %d\n", s.TombstonesSeen)
	printf(stdout, "truncated bytes:   %d\n", s.TruncatedBytes)
	printf(stdout, "corruption found:  %v\n", s.CorruptionFound)
	return ExitOK
}

func runCompact(args []string, db *engine.Database, stdout, stderr io.Writer) int {
	if len(args) != 0 {
		println(stderr, "usage: minikv compact")
		return ExitUsage
	}
	result, err := db.Compact()
	if err != nil {
		println(stderr, "error:", err)
		return ExitError
	}
	printf(stdout, "compacted: kept %d live keys, %d -> %d bytes, pruned %d tombstones\n",
		result.LiveKeysKept, result.BytesBefore, result.BytesAfter, result.TombstonesPruned)
	return ExitOK
}

func runBackup(args []string, globals GlobalOptions, stdout, stderr io.Writer) int {
	if len(args) != 1 {
		println(stderr, "usage: minikv backup <destination>")
		return ExitUsage
	}
	db, err := engine.Open(globals.DBPath, engine.Options{Sync: globals.Sync})
	if err != nil {
		println(stderr, "error: could not open database:", err)
		return ExitError
	}
	defer db.Close()

	if err := db.Backup(args[0]); err != nil {
		println(stderr, "error:", err)
		return ExitError
	}
	println(stdout, "backup written to", args[0])
	return ExitOK
}

func runRestore(args []string, globals GlobalOptions, stdout, stderr io.Writer) int {
	if len(args) != 1 {
		println(stderr, "usage: minikv restore <backup>")
		return ExitUsage
	}
	if err := engine.Restore(args[0], globals.DBPath); err != nil {
		println(stderr, "error:", err)
		return ExitError
	}
	println(stdout, "restored", globals.DBPath, "from", args[0])
	return ExitOK
}

func runShell(db *engine.Database, stdout, stderr io.Writer) int {
	println(stdout, "MiniKV shell — type 'help' for commands, 'exit' to quit.")
	return runShellLoop(db, os.Stdin, stdout, stderr)
}

// runShellLoop implements the "minikv shell" REPL. It re-uses the exact
// same command handlers as the non-interactive CLI, so shell behavior can
// never drift from one-shot command behavior — there is only one
// implementation of "set", not two.
func runShellLoop(db *engine.Database, in io.Reader, stdout, stderr io.Writer) int {
	scanner := bufio.NewScanner(in)
	for {
		printf(stdout, "> ")
		if !scanner.Scan() {
			break
		}
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		fields := strings.Fields(line)
		switch fields[0] {
		case "exit", "quit":
			return ExitOK
		case "help":
			println(stdout, strings.TrimRight(usage, "\n"))
			continue
		case "version":
			println(stdout, "minikv version", Version)
			continue
		}

		switch fields[0] {
		case "set":
			runSet(fields[1:], db, stdout, stderr)
		case "get":
			runGet(fields[1:], db, stdout, stderr)
		case "delete":
			runDelete(fields[1:], db, stdout, stderr)
		case "exists":
			runExists(fields[1:], db, stdout, stderr)
		case "list":
			runList(fields[1:], db, stdout, stderr)
		case "stats":
			runStats(fields[1:], db, stdout, stderr)
		case "compact":
			runCompact(fields[1:], db, stdout, stderr)
		default:
			println(stderr, "unknown shell command:", fields[0])
		}
	}
	return ExitOK
}
