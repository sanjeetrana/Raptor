package cli

import (
	"fmt"
	"strconv"
	"strings"
)

// GlobalOptions holds flags that apply regardless of which subcommand is
// being run. MiniKV intentionally does not use the standard "flag"
// package's default parsing here because subcommand-style CLIs (verb
// first, then flags mixed with positional args) don't map cleanly onto
// it without extra scaffolding; a ~40-line scanner is easier to read,
// test and audit than bending flag.FlagSet to the task. It is still pure
// standard-library Go (strconv, strings) — see STDLIB.md.
type GlobalOptions struct {
	DBPath string
	Sync   bool
}

const defaultDBPath = "minikv.db"

// extractGlobalFlags scans args for --db/-db and --sync/-sync anywhere in
// the argument list, removes them, and returns the remaining positional
// arguments alongside the parsed options.
func extractGlobalFlags(args []string) ([]string, GlobalOptions, error) {
	opts := GlobalOptions{DBPath: defaultDBPath}
	rest := make([]string, 0, len(args))

	for i := 0; i < len(args); i++ {
		a := args[i]
		switch {
		case a == "--db" || a == "-db":
			if i+1 >= len(args) {
				return nil, opts, fmt.Errorf("%s requires a value", a)
			}
			opts.DBPath = args[i+1]
			i++
		case strings.HasPrefix(a, "--db="):
			opts.DBPath = strings.TrimPrefix(a, "--db=")
		case a == "--sync" || a == "-sync":
			opts.Sync = true
		default:
			rest = append(rest, a)
		}
	}
	return rest, opts, nil
}

// extractTTL scans args for --ttl <seconds> (or --ttl=<seconds>) and
// returns the remaining args plus the parsed duration in seconds (0 if
// not present).
func extractTTL(args []string) ([]string, int64, error) {
	rest := make([]string, 0, len(args))
	var ttl int64

	for i := 0; i < len(args); i++ {
		a := args[i]
		switch {
		case a == "--ttl":
			if i+1 >= len(args) {
				return nil, 0, fmt.Errorf("--ttl requires a value in seconds")
			}
			v, err := strconv.ParseInt(args[i+1], 10, 64)
			if err != nil {
				return nil, 0, fmt.Errorf("--ttl must be an integer number of seconds: %w", err)
			}
			ttl = v
			i++
		case strings.HasPrefix(a, "--ttl="):
			v, err := strconv.ParseInt(strings.TrimPrefix(a, "--ttl="), 10, 64)
			if err != nil {
				return nil, 0, fmt.Errorf("--ttl must be an integer number of seconds: %w", err)
			}
			ttl = v
		default:
			rest = append(rest, a)
		}
	}
	return rest, ttl, nil
}
