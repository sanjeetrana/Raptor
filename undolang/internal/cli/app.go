package cli

import (
	"crypto/sha256"
	"encoding/hex"
	json "encoding/json/v2"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"

	"github.com/daniel-oluwadunsin/undolang/internal/buildinfo"
	"github.com/daniel-oluwadunsin/undolang/internal/fsop"
	"github.com/daniel-oluwadunsin/undolang/internal/journal"
	"github.com/daniel-oluwadunsin/undolang/internal/lang/diag"
	"github.com/daniel-oluwadunsin/undolang/internal/lang/frontend"
	"github.com/daniel-oluwadunsin/undolang/internal/lang/validate"
	"github.com/daniel-oluwadunsin/undolang/internal/pathcap"
	"github.com/daniel-oluwadunsin/undolang/internal/plan"
	"github.com/daniel-oluwadunsin/undolang/internal/program"
	"github.com/daniel-oluwadunsin/undolang/internal/recovery"
	"github.com/daniel-oluwadunsin/undolang/internal/report"
	"github.com/daniel-oluwadunsin/undolang/internal/state"
	"github.com/daniel-oluwadunsin/undolang/internal/txn"
)

type App struct {
	Stdin          io.Reader
	Stdout, Stderr io.Writer
	IsTerminal     func() bool
	Checkpoint     func(string)
}

func (a App) Run(args []string) int {
	if a.Stdout == nil {
		a.Stdout = os.Stdout
	}
	if a.Stderr == nil {
		a.Stderr = os.Stderr
	}
	if a.Stdin == nil {
		a.Stdin = os.Stdin
	}
	if len(args) == 0 {
		fmt.Fprintln(a.Stderr, usage)
		return 1
	}
	switch args[0] {
	case "check":
		return a.check(args[1:])
	case "plan":
		return a.plan(args[1:])
	case "run":
		return a.run(args[1:])
	case "recover":
		return a.recover(args[1:])
	case "history":
		return a.history(args[1:])
	case "inspect":
		return a.inspect(args[1:])
	case "version":
		return a.version(args[1:])
	case "capabilities":
		return a.capabilities(args[1:])
	case "schema":
		return a.schema(args[1:])
	case "agent-guide":
		return a.agentGuide(args[1:])
	case "help", "--help", "-h":
		fmt.Fprintln(a.Stdout, usage)
		return 0
	default:
		return a.failure(false, &report.Error{Code: "E_USAGE", Message: "unknown command " + args[0]}, 1)
	}
}

const usage = `UndoLang — crash-safe filesystem transactions

usage: undo <command> [options]

commands:
  check FILE       validate a complete UndoLang program
  plan FILE        inspect current-state and deferred transaction effects
  run FILE         execute one or all transactions with durable rollback
  recover          recover the unresolved transaction for a root
  history          list local transaction history
  inspect TXID     inspect validated transaction metadata and journal
  capabilities     describe supported workflow features
  schema           describe the UndoLang language
  agent-guide      print the machine-agent workflow
  version          print deterministic version information

Use "undo <command> --help" for command-specific flags.`

const agentGuide = "Agent workflow: capabilities --json -> schema --json -> check FILE --json -> plan FILE --json -> obtain approval -> run FILE --yes --json. If run reports recovery_required, invoke recover --root ROOT --yes --json before starting new work."

type stringList []string

func (s *stringList) String() string     { return strings.Join(*s, ",") }
func (s *stringList) Set(v string) error { *s = append(*s, v); return nil }

type common struct {
	root, transaction  string
	allowed            stringList
	json, noColor, yes bool
	file               string
}

func parseCommon(name string, args []string, transaction, mutation bool) (common, error) {
	var c common
	flags := flag.NewFlagSet(name, flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	flags.StringVar(&c.root, "root", "", "transaction root")
	flags.Var(&c.allowed, "allow-path", "additional capability root")
	if transaction {
		flags.StringVar(&c.transaction, "transaction", "", "transaction name")
	}
	flags.BoolVar(&c.json, "json", false, "machine JSON")
	flags.BoolVar(&c.noColor, "no-color", false, "disable color")
	if mutation {
		flags.BoolVar(&c.yes, "yes", false, "approve mutation without a prompt")
	}
	reordered, err := reorder(args, map[string]bool{"root": true, "allow-path": true, "transaction": transaction, "json": false, "no-color": false, "yes": false})
	if err != nil {
		return c, err
	}
	if err = flags.Parse(reordered); err != nil {
		return c, err
	}
	if flags.NArg() != 1 {
		return c, fmt.Errorf("exactly one FILE is required")
	}
	c.file = flags.Arg(0)
	return c, nil
}

func reorder(args []string, values map[string]bool) ([]string, error) {
	var flags, positional []string
	for i := 0; i < len(args); i++ {
		arg := args[i]
		if arg == "--" {
			positional = append(positional, args[i+1:]...)
			break
		}
		if !strings.HasPrefix(arg, "-") || arg == "-" {
			positional = append(positional, arg)
			continue
		}
		name := strings.TrimLeft(strings.SplitN(arg, "=", 2)[0], "-")
		takesValue, known := values[name]
		if !known {
			flags = append(flags, arg)
			continue
		}
		flags = append(flags, arg)
		if takesValue && !strings.Contains(arg, "=") {
			if i+1 >= len(args) {
				return nil, fmt.Errorf("flag --%s requires a value", name)
			}
			i++
			flags = append(flags, args[i])
		}
	}
	return append(flags, positional...), nil
}

func load(c common) (validate.Program, []byte, string, *pathcap.Set, error) {
	src, err := os.ReadFile(c.file)
	if err != nil {
		return validate.Program{}, nil, "", nil, err
	}
	program, diagnostic := frontend.Parse(src)
	if diagnostic != nil {
		return validate.Program{}, nil, "", nil, diagnostic
	}
	abs, err := filepath.Abs(c.file)
	if err != nil {
		return validate.Program{}, nil, "", nil, err
	}
	caps, err := pathcap.Open(c.root, c.allowed)
	if err != nil {
		return validate.Program{}, nil, "", nil, err
	}
	return program, src, abs, caps, nil
}

func (a App) check(args []string) int {
	if hasHelp(args) {
		fmt.Fprintln(a.Stdout, "usage: undo check FILE [--root DIR] [--allow-path DIR]... [--json]")
		return 0
	}
	c, err := parseCommon("check", args, false, false)
	if err != nil {
		return a.err(jsonRequested(args), err)
	}
	program, _, path, caps, err := load(c)
	if err != nil {
		return a.err(c.json, err)
	}
	defer caps.Close()
	if err = plan.ValidatePaths(program, caps); err != nil {
		return a.err(c.json, err)
	}
	result := report.CheckResult{ScriptPath: path, Transactions: validate.Names(program)}
	if c.json {
		return a.success(result)
	}
	fmt.Fprintf(a.Stdout, "valid UndoLang program: %s\n", path)
	for _, name := range result.Transactions {
		fmt.Fprintf(a.Stdout, "transaction: %s\n", name)
	}
	return 0
}

func (a App) plan(args []string) int {
	if hasHelp(args) {
		fmt.Fprintln(a.Stdout, "usage: undo plan FILE [--transaction NAME] [--root DIR] [--allow-path DIR]... [--json]")
		return 0
	}
	c, err := parseCommon("plan", args, true, false)
	if err != nil {
		return a.err(jsonRequested(args), err)
	}
	program, src, path, caps, err := load(c)
	if err != nil {
		return a.err(c.json, err)
	}
	defer caps.Close()
	sum := sha256.Sum256(src)
	result, err := plan.Build(program, caps, plan.Options{ScriptPath: path, ScriptSHA256: hex.EncodeToString(sum[:]), SelectedName: c.transaction})
	if err != nil {
		return a.err(c.json, err)
	}
	if c.json {
		a.success(result)
		if !result.SafeToStart {
			return 2
		}
		return 0
	}
	fmt.Fprintf(a.Stdout, "program: %s\nroot: %s\nmode: %s\nsafe to start: %t\n", path, caps.Primary(), result.Mode, result.SafeToStart)
	for _, tx := range result.Transactions {
		fmt.Fprintf(a.Stdout, "transaction %s: %s\n", tx.Name, tx.Readiness)
		if tx.Plan != nil {
			for _, op := range tx.Plan.Operations {
				fmt.Fprintf(a.Stdout, "  %d. %s %s (%s)\n", op.Index+1, op.Kind, op.Target.Original, op.Effect)
			}
		}
	}
	if !result.SafeToStart {
		return 2
	}
	return 0
}

func (a App) run(args []string) int {
	if hasHelp(args) {
		fmt.Fprintln(a.Stdout, "usage: undo run FILE [--transaction NAME] [--root DIR] [--allow-path DIR]... [--yes] [--json]")
		return 0
	}
	c, err := parseCommon("run", args, true, true)
	if err != nil {
		return a.err(jsonRequested(args), err)
	}
	validated, source, scriptPath, caps, err := load(c)
	if err != nil {
		return a.err(c.json, err)
	}
	defer caps.Close()
	sum := sha256.Sum256(source)
	scriptHash := hex.EncodeToString(sum[:])
	preview, err := plan.Build(validated, caps, plan.Options{ScriptPath: scriptPath, ScriptSHA256: scriptHash, SelectedName: c.transaction})
	if err != nil {
		return a.err(c.json, err)
	}
	if !preview.SafeToStart {
		return a.failure(c.json, &report.Error{Code: txn.PreconditionFailed, Message: "program is not safe to start"}, 2)
	}
	if !c.yes {
		if c.json || !a.interactive() {
			return a.failure(c.json, &report.Error{Code: "E_APPROVAL_REQUIRED", Message: "noninteractive mutation requires --yes"}, 1)
		}
		fmt.Fprintf(a.Stdout, "program: %s\nroot: %s\ntransactions: %d\n", scriptPath, caps.Primary(), len(preview.Transactions))
		for _, root := range caps.Roots() {
			kind := "allowed"
			if root.Primary {
				kind = "primary"
			}
			fmt.Fprintf(a.Stdout, "capability (%s): %s\n", kind, root.Path)
		}
		for _, transaction := range preview.Transactions {
			fmt.Fprintf(a.Stdout, "  %s: %s\n", transaction.Name, transaction.Readiness)
			if transaction.Plan != nil {
				fmt.Fprintf(a.Stdout, "    rollback estimate: %d bytes\n", transaction.Plan.Summary.RollbackBytes)
				for _, operation := range transaction.Plan.Operations {
					fmt.Fprintf(a.Stdout, "    %s %s (%s)\n", operation.Kind, operation.Target.Original, operation.Effect)
				}
			} else {
				for _, operation := range transaction.Operations {
					fmt.Fprintf(a.Stdout, "    %s %s (deferred)\n", operation.Kind, operation.Target.Original)
				}
			}
		}
		fmt.Fprint(a.Stdout, "Execute this program? [y/N] ")
		var answer string
		if _, err = fmt.Fscanln(a.Stdin, &answer); err != nil && !errors.Is(err, io.EOF) {
			return a.err(false, err)
		}
		if !strings.EqualFold(answer, "y") && !strings.EqualFold(answer, "yes") {
			return a.failure(false, &report.Error{Code: "E_CANCELLED", Message: "execution cancelled"}, 1)
		}
	}
	result, runErr := program.Run(validated, caps, program.Options{ScriptPath: scriptPath, ScriptSHA256: scriptHash, SelectedName: c.transaction, Checkpoint: a.Checkpoint})
	if runErr != nil {
		structured, exit := classifyError(runErr)
		return a.failureResult(c.json, result, structured, exit)
	}
	if c.json {
		return a.success(result)
	}
	for _, transaction := range result.Transactions {
		fmt.Fprintf(a.Stdout, "%s: %s", transaction.Name, transaction.Status)
		if transaction.TransactionID != "" {
			fmt.Fprintf(a.Stdout, " (%s)", transaction.TransactionID)
		}
		fmt.Fprintln(a.Stdout)
	}
	return 0
}

type rootFlags struct {
	root        string
	json, yes   bool
	positionals []string
}

func parseRootFlags(name string, args []string, mutation bool) (rootFlags, error) {
	var result rootFlags
	var noColor bool
	flags := flag.NewFlagSet(name, flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	flags.StringVar(&result.root, "root", "", "transaction root")
	flags.BoolVar(&result.json, "json", false, "machine JSON")
	flags.BoolVar(&noColor, "no-color", false, "disable color")
	if mutation {
		flags.BoolVar(&result.yes, "yes", false, "approve mutation without a prompt")
	}
	reordered, err := reorder(args, map[string]bool{"root": true, "json": false, "yes": false, "no-color": false})
	if err != nil {
		return result, err
	}
	if err = flags.Parse(reordered); err != nil {
		return result, err
	}
	result.positionals = flags.Args()
	return result, nil
}

func (a App) recover(args []string) int {
	if hasHelp(args) {
		fmt.Fprintln(a.Stdout, "usage: undo recover [--root DIR] [--yes] [--json]")
		return 0
	}
	flags, err := parseRootFlags("recover", args, true)
	if err != nil || len(flags.positionals) != 0 {
		if err == nil {
			err = errors.New("recover accepts no positional arguments")
		}
		return a.err(jsonRequested(args), err)
	}
	if !flags.yes {
		if flags.json || !a.interactive() {
			return a.failure(flags.json, &report.Error{Code: "E_APPROVAL_REQUIRED", Message: "noninteractive recovery requires --yes"}, 1)
		}
		fmt.Fprint(a.Stdout, "Recover the unresolved transaction for this root? [y/N] ")
		var answer string
		_, _ = fmt.Fscanln(a.Stdin, &answer)
		if !strings.EqualFold(answer, "y") && !strings.EqualFold(answer, "yes") {
			return a.failure(false, &report.Error{Code: "E_CANCELLED", Message: "recovery cancelled"}, 1)
		}
	}
	result, err := recovery.RecoverRoot(flags.root, recovery.Options{Checkpoint: a.Checkpoint})
	if err != nil {
		return a.err(flags.json, err)
	}
	if flags.json {
		return a.success(result)
	}
	if result.TransactionID == "" {
		fmt.Fprintln(a.Stdout, "no recovery required")
	} else {
		fmt.Fprintf(a.Stdout, "transaction %s: %s\n", result.TransactionID, result.Status)
	}
	return 0
}

func (a App) history(args []string) int {
	if hasHelp(args) {
		fmt.Fprintln(a.Stdout, "usage: undo history [--root DIR] [--json]")
		return 0
	}
	flags, err := parseRootFlags("history", args, false)
	if err != nil || len(flags.positionals) != 0 {
		if err == nil {
			err = errors.New("history accepts no positional arguments")
		}
		return a.err(jsonRequested(args), err)
	}
	store, err := state.Open(flags.root)
	if err != nil {
		return a.err(flags.json, err)
	}
	entries, err := store.History()
	if err != nil {
		return a.err(flags.json, err)
	}
	for left, right := 0, len(entries)-1; left < right; left, right = left+1, right-1 {
		entries[left], entries[right] = entries[right], entries[left]
	}
	if flags.json {
		return a.success(entries)
	}
	for _, entry := range entries {
		fmt.Fprintf(a.Stdout, "%s  %s  %s  %s\n", entry.ID, entry.Status, entry.StartedAt.Format("2006-01-02T15:04:05Z"), entry.Name)
	}
	return 0
}

func (a App) inspect(args []string) int {
	if hasHelp(args) {
		fmt.Fprintln(a.Stdout, "usage: undo inspect TXID [--root DIR] [--json]")
		return 0
	}
	flags, err := parseRootFlags("inspect", args, false)
	if err != nil || len(flags.positionals) != 1 {
		if err == nil {
			err = errors.New("inspect requires exactly one TXID")
		}
		return a.err(jsonRequested(args), err)
	}
	store, err := state.Open(flags.root)
	if err != nil {
		return a.err(flags.json, err)
	}
	meta, err := store.Inspect(flags.positionals[0])
	if err != nil {
		return a.err(flags.json, err)
	}
	journalPath := filepath.Join(meta.Root, ".undo", "transactions", meta.ID, "journal.bin")
	file, err := os.Open(journalPath)
	if err != nil {
		return a.err(flags.json, err)
	}
	replay, decodeErr := journal.Decode(file)
	closeErr := file.Close()
	if decodeErr != nil {
		return a.err(flags.json, decodeErr)
	}
	if closeErr != nil {
		return a.err(flags.json, closeErr)
	}
	type inspectedOperation struct {
		ID   string `json:"id"`
		Kind string `json:"kind"`
	}
	var operations []inspectedOperation
	for _, record := range replay.Records {
		if record.Type != journal.OPPrepared {
			continue
		}
		var payload struct {
			OperationID string        `json:"operation_id"`
			Data        fsop.Prepared `json:"data"`
		}
		if err = json.Unmarshal(record.Payload, &payload); err != nil {
			return a.err(flags.json, err)
		}
		operations = append(operations, inspectedOperation{ID: payload.OperationID, Kind: string(payload.Data.Kind)})
	}
	result := struct {
		Metadata        state.Metadata       `json:"metadata"`
		JournalRecords  int                  `json:"journal_records"`
		JournalState    string               `json:"journal_state"`
		TornTail        bool                 `json:"torn_tail"`
		BackupsRetained bool                 `json:"backups_retained"`
		Operations      []inspectedOperation `json:"operations"`
		Warnings        []string             `json:"warnings"`
	}{Metadata: meta, JournalRecords: len(replay.Records), JournalState: replay.State, TornTail: replay.TornTail, BackupsRetained: !meta.BackupCleaned, Operations: operations, Warnings: []string{"history is audit metadata; post-commit undo is not supported"}}
	if flags.json {
		return a.success(result)
	}
	fmt.Fprintf(a.Stdout, "transaction: %s\nname: %s\nstatus: %s\njournal records: %d\nbackups retained: %t\n", meta.ID, meta.Name, meta.Status, len(replay.Records), !meta.BackupCleaned)
	return 0
}

func hasHelp(args []string) bool {
	for _, arg := range args {
		if arg == "--help" || arg == "-h" {
			return true
		}
	}
	return false
}

func (a App) interactive() bool {
	if a.IsTerminal != nil {
		return a.IsTerminal()
	}
	input, inputOK := a.Stdin.(*os.File)
	output, outputOK := a.Stdout.(*os.File)
	if !inputOK || !outputOK {
		return false
	}
	inInfo, inErr := input.Stat()
	outInfo, outErr := output.Stat()
	return inErr == nil && outErr == nil && inInfo.Mode()&os.ModeCharDevice != 0 && outInfo.Mode()&os.ModeCharDevice != 0
}

func jsonRequested(args []string) bool {
	for _, arg := range args {
		if arg == "--json" || arg == "-json" || arg == "--json=true" || arg == "-json=true" {
			return true
		}
	}
	return false
}

func (a App) agentGuide(args []string) int {
	if hasHelp(args) {
		fmt.Fprintln(a.Stdout, "usage: undo agent-guide [--json]")
		return 0
	}
	j, err := boolFlag(args)
	if err != nil {
		return a.err(jsonRequested(args), err)
	}
	if j {
		return a.success(map[string]any{
			"workflow": []string{"capabilities --json", "schema --json", "check FILE --json", "plan FILE --json", "run FILE --yes --json"},
			"recovery": "on recovery_required, stop and run recover --root ROOT --yes --json",
			"approval": "--json never grants mutation approval; pass --yes only after plan approval",
		})
	}
	fmt.Fprintln(a.Stdout, agentGuide)
	return 0
}

func boolFlag(args []string) (bool, error) {
	flags := flag.NewFlagSet("output", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	value := flags.Bool("json", false, "machine JSON")
	if err := flags.Parse(args); err != nil {
		return false, err
	}
	if flags.NArg() != 0 {
		return false, fmt.Errorf("unexpected arguments")
	}
	return *value, nil
}

func (a App) version(args []string) int {
	if hasHelp(args) {
		fmt.Fprintln(a.Stdout, "usage: undo version [--json]")
		return 0
	}
	j, err := boolFlag(args)
	if err != nil {
		return a.err(false, err)
	}
	result := map[string]string{"version": buildinfo.Version, "dsl_version": buildinfo.DSLVersion, "api_version": buildinfo.APIVersion, "go_version": runtime.Version()}
	if j {
		return a.success(result)
	}
	fmt.Fprintf(a.Stdout, "UndoLang %s\ndsl %s\napi %s\ngo %s\n", buildinfo.Version, buildinfo.DSLVersion, buildinfo.APIVersion, runtime.Version())
	return 0
}

func (a App) capabilities(args []string) int {
	if hasHelp(args) {
		fmt.Fprintln(a.Stdout, "usage: undo capabilities [--json]")
		return 0
	}
	j, err := boolFlag(args)
	if err != nil {
		return a.err(false, err)
	}
	result := map[string]any{"cli_version": buildinfo.Version, "dsl_version": buildinfo.DSLVersion, "api_version": buildinfo.APIVersion, "operations": []string{"mkdir", "copy", "move", "write", "replace", "delete"}, "operation_contracts": map[string]any{"mkdir": operationSchema("mkdir PATH", true, false, `mkdir "cache/data"`), "copy": operationSchema("copy SOURCE -> TARGET [overwrite]", true, true, `copy "a" -> "b" overwrite`), "move": operationSchema("move SOURCE -> TARGET [overwrite]", true, true, `move "a" -> "b"`), "write": operationSchema("write PATH = STRING", true, true, `write "VERSION" = "2"`), "replace": operationSchema("replace PATH OLD -> NEW", true, true, `replace "config" "v1" -> "v2"`), "delete": operationSchema("delete PATH", true, true, `delete "obsolete"`)}, "conditions": []string{"exists", "not_exists", "is_file", "is_dir", "contains", "sha256"}, "commands": []string{"check", "plan", "run", "recover", "history", "inspect", "version", "capabilities", "schema", "agent-guide"}, "path_model": "relative paths bind to --root/cwd; external absolute paths require --allow-path", "approval": "noninteractive or JSON mutation requires --yes", "recovery_classifications": []string{"committed", "rolled_back", "recovery_required", "recovery_failed", "journal_corrupt"}, "transaction_model": "source-order, fail-fast, one recoverable transaction boundary per named transaction"}
	if j {
		return a.success(result)
	}
	fmt.Fprintln(a.Stdout, "UndoLang capabilities: plan, journaled run/recover, history/inspect, six filesystem operations, and six conditions")
	return 0
}

func (a App) schema(args []string) int {
	if hasHelp(args) {
		fmt.Fprintln(a.Stdout, "usage: undo schema [--json]")
		return 0
	}
	j, err := boolFlag(args)
	if err != nil {
		return a.err(false, err)
	}
	result := map[string]any{"version": buildinfo.Version, "dsl_version": buildinfo.DSLVersion, "api_version": buildinfo.APIVersion, "transaction": map[string]any{"syntax": "transaction STRING { require* mutation* assert* }", "rollback_boundary": true, "program_execution": "source order and fail fast; earlier commits remain committed"}, "operations": map[string]any{"mkdir": operationSchema("mkdir PATH", true, false, `mkdir "cache/data"`), "copy": operationSchema("copy SOURCE -> TARGET [overwrite]", true, true, `copy "config.new" -> "config" overwrite`), "move": operationSchema("move SOURCE -> TARGET [overwrite]", true, true, `move "old" -> "new"`), "write": operationSchema("write PATH = STRING", true, true, `write "VERSION" = "2"`), "replace": operationSchema("replace PATH OLD -> NEW", true, true, `replace "app.conf" "v1" -> "v2"`), "delete": operationSchema("delete PATH", true, true, `delete "obsolete"`)}, "conditions": map[string]any{"exists": conditionSchema("exists PATH"), "not_exists": conditionSchema("not_exists PATH"), "is_file": conditionSchema("is_file PATH"), "is_dir": conditionSchema("is_dir PATH"), "contains": conditionSchema("contains PATH TEXT"), "sha256": conditionSchema("sha256 PATH = HEX")}, "workflow": []string{"capabilities --json", "schema --json", "check FILE --json", "plan FILE --json", "run FILE --yes --json", "recover --root ROOT --yes --json"}, "approval": map[string]any{"mutating_commands": []string{"run", "recover"}, "noninteractive_flag": "--yes", "json_grants_approval": false}, "result_statuses": []string{"committed", "rolled_back", "failed_preflight", "recovery_required", "recovery_failed", "skipped"}, "exit_codes": map[string]int{"success": 0, "usage_language_approval": 1, "unsafe_plan": 2, "path_conflict_io": 3, "rolled_back": 4, "recovery_required": 5, "recovery_or_journal_failure": 6, "internal": 7}}
	if j {
		return a.success(result)
	}
	fmt.Fprintln(a.Stdout, "UndoLang schema undo-dsl/1; use --json for the complete machine schema")
	return 0
}

func operationSchema(syntax string, reversible, destructive bool, example string) map[string]any {
	return map[string]any{"syntax": syntax, "reversible": reversible, "destructive": destructive, "example": example}
}

func conditionSchema(syntax string) map[string]any {
	return map[string]any{"syntax": syntax, "result": "boolean", "reads_filesystem": true}
}

func (a App) success(result any) int {
	data, err := json.Marshal(&report.Envelope{APIVersion: buildinfo.APIVersion, OK: true, Result: result})
	if err != nil {
		fmt.Fprintln(a.Stderr, err)
		return 7
	}
	fmt.Fprintln(a.Stdout, string(data))
	return 0
}

func (a App) err(jsonMode bool, err error) int {
	r, code := classifyError(err)
	return a.failure(jsonMode, r, code)
}

func classifyError(err error) (*report.Error, int) {
	r := &report.Error{Code: "E_IO", Message: err.Error()}
	code := 3
	var diagnostic *diag.Error
	var pathError *pathcap.Error
	var planError *plan.Error
	var programError *program.Error
	var transactionError *txn.Error
	var recoveryError *recovery.Error
	switch {
	case errors.As(err, &diagnostic):
		r.Code, r.Message, r.Line, r.Column, code = diagnostic.Code, diagnostic.Message, diagnostic.Span.Start.Line, diagnostic.Span.Start.Column, 1
	case errors.As(err, &pathError):
		r.Code, r.Message, r.Path, r.Root, code = pathError.Code, pathError.Message, pathError.Path, pathError.Root, 3
	case errors.As(err, &planError):
		r.Code, r.Message, code = planError.Code, planError.Message, 2
	case errors.As(err, &transactionError):
		r.Code, r.Message, r.TransactionID = transactionError.Code, transactionError.Message, transactionError.TransactionID
		if errors.Is(transactionError.Cause, os.ErrPermission) {
			r.Code = "E_PERMISSION"
		} else if isNoSpace(transactionError.Cause) {
			r.Code = "E_NO_SPACE"
		}
		if transactionError.RolledBack {
			code = 4
		} else {
			code = 5
		}
	case errors.As(err, &recoveryError):
		r.Code, r.Message, r.TransactionID = recoveryError.Code, recoveryError.Message, recoveryError.TransactionID
		r.Recovery = "inspect retained state and run undo recover --root ROOT --yes"
		if recoveryError.Code == recovery.Required {
			code = 5
		} else {
			code = 6
		}
	case errors.As(err, &programError):
		r.Code, r.Message = programError.Code, programError.Message
		nested, nestedCode := classifyError(programError.Cause)
		if r.Code == "E_IO" || r.Code == "E_PERMISSION" || r.Code == "E_NO_SPACE" {
			r.Code = nested.Code
		}
		code = nestedCode
	case errors.Is(err, journal.ErrCorrupt):
		r.Code, code = recovery.Corrupt, 6
	case errors.Is(err, os.ErrPermission):
		r.Code = "E_PERMISSION"
	case isNoSpace(err):
		r.Code = "E_NO_SPACE"
	}
	return r, code
}

func (a App) failure(jsonMode bool, result *report.Error, code int) int {
	if jsonMode {
		data, err := json.Marshal(&report.Envelope{APIVersion: buildinfo.APIVersion, OK: false, Error: result})
		if err == nil {
			fmt.Fprintln(a.Stdout, string(data))
			return code
		}
	}
	fmt.Fprintf(a.Stderr, "%s: %s\n", result.Code, result.Message)
	return code
}

func (a App) failureResult(jsonMode bool, result any, structured *report.Error, code int) int {
	if jsonMode {
		data, err := json.Marshal(&report.Envelope{APIVersion: buildinfo.APIVersion, OK: false, Result: result, Error: structured})
		if err == nil {
			fmt.Fprintln(a.Stdout, string(data))
			return code
		}
	}
	fmt.Fprintf(a.Stderr, "%s: %s\n", structured.Code, structured.Message)
	return code
}
