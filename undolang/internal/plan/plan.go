package plan

import (
	"errors"
	"io/fs"
	"path/filepath"
	"sort"
	"strings"

	"github.com/daniel-oluwadunsin/undolang/internal/condition"
	"github.com/daniel-oluwadunsin/undolang/internal/lang/ast"
	"github.com/daniel-oluwadunsin/undolang/internal/lang/validate"
	"github.com/daniel-oluwadunsin/undolang/internal/pathcap"
)

type Effect string

const (
	EffectCreate    Effect = "create"
	EffectModify    Effect = "modify"
	EffectMove      Effect = "move"
	EffectDelete    Effect = "delete"
	EffectOverwrite Effect = "overwrite"
	EffectNoop      Effect = "no-op"
	EffectDeferred  Effect = "deferred"
)

type Readiness string

const (
	Ready    Readiness = "ready"
	Deferred Readiness = "deferred"
	Unsafe   Readiness = "unsafe"
)

type PlannedCondition struct {
	Kind     ast.ConditionKind    `json:"kind"`
	Path     pathcap.ResolvedPath `json:"path"`
	Expected string               `json:"expected,omitempty"`
	Result   *bool                `json:"result,omitempty"`
	Actual   string               `json:"actual,omitempty"`
}

type PlannedOperation struct {
	Index         int                   `json:"index"`
	Kind          ast.StatementKind     `json:"kind"`
	Source        *pathcap.ResolvedPath `json:"source,omitempty"`
	Target        pathcap.ResolvedPath  `json:"target"`
	Effect        Effect                `json:"effect"`
	Overwrite     bool                  `json:"overwrite,omitempty"`
	EntryCount    int64                 `json:"entry_count,omitempty"`
	Bytes         int64                 `json:"bytes,omitempty"`
	RollbackBytes int64                 `json:"rollback_bytes,omitempty"`
}

type Summary struct {
	Creates       int   `json:"creates"`
	Modifies      int   `json:"modifies"`
	Moves         int   `json:"moves"`
	Deletes       int   `json:"deletes"`
	Overwrites    int   `json:"overwrites"`
	Noops         int   `json:"no_ops"`
	RollbackBytes int64 `json:"rollback_bytes"`
}

type Plan struct {
	APIVersion    string             `json:"api_version"`
	Name          string             `json:"name"`
	ScriptPath    string             `json:"script_path"`
	ScriptSHA256  string             `json:"script_sha256"`
	Root          string             `json:"root"`
	AllowedRoots  []string           `json:"allowed_roots"`
	Preconditions []PlannedCondition `json:"preconditions"`
	Operations    []PlannedOperation `json:"operations"`
	Assertions    []PlannedCondition `json:"assertions"`
	Summary       Summary            `json:"summary"`
	Warnings      []string           `json:"warnings"`
	SafeToExecute bool               `json:"safe_to_execute"`
	Reasons       []string           `json:"reasons"`
}

type TransactionSummary struct {
	Name       string             `json:"name"`
	Readiness  Readiness          `json:"readiness"`
	Plan       *Plan              `json:"plan,omitempty"`
	Operations []PlannedOperation `json:"operations,omitempty"`
	Reasons    []string           `json:"reasons"`
}

type ProgramPlan struct {
	APIVersion   string               `json:"api_version"`
	ScriptPath   string               `json:"script_path"`
	ScriptSHA256 string               `json:"script_sha256"`
	Mode         string               `json:"mode"`
	SelectedName string               `json:"selected_name,omitempty"`
	Transactions []TransactionSummary `json:"transactions"`
	SafeToStart  bool                 `json:"safe_to_start"`
}

type Error struct{ Code, Message string }

func (e *Error) Error() string { return e.Code + ": " + e.Message }

const (
	SourceMissing          = "E_SOURCE_MISSING"
	DestinationExists      = "E_DESTINATION_EXISTS"
	Conflict               = "E_CONFLICT"
	UnsupportedFileType    = "E_UNSUPPORTED_FILE_TYPE"
	UnsupportedSymlinkCopy = "E_UNSUPPORTED_SYMLINK_COPY"
)

type Options struct{ ScriptPath, ScriptSHA256, SelectedName string }

func Build(program validate.Program, caps *pathcap.Set, opts Options) (ProgramPlan, error) {
	result := ProgramPlan{APIVersion: "undo-cli/1", ScriptPath: opts.ScriptPath, ScriptSHA256: opts.ScriptSHA256, Mode: "all", SelectedName: opts.SelectedName}
	transactions := program.Transactions
	if opts.SelectedName != "" {
		result.Mode = "selected"
		found := false
		for _, tx := range transactions {
			if tx.Name == opts.SelectedName {
				transactions, found = []validate.Transaction{tx}, true
				break
			}
		}
		if !found {
			return ProgramPlan{}, &Error{Code: Conflict, Message: "unknown transaction " + opts.SelectedName}
		}
	}
	for i, tx := range transactions {
		if i == 0 || result.Mode == "selected" || len(transactions) == 1 {
			exact, err := buildExact(tx, caps, opts)
			if err != nil {
				return ProgramPlan{}, err
			}
			readiness := Ready
			if !exact.SafeToExecute {
				readiness = Unsafe
			}
			result.Transactions = append(result.Transactions, TransactionSummary{Name: tx.Name, Readiness: readiness, Plan: &exact, Reasons: exact.Reasons})
			result.SafeToStart = exact.SafeToExecute
			continue
		}
		ops, err := staticOperations(tx, caps)
		if err != nil {
			return ProgramPlan{}, err
		}
		result.Transactions = append(result.Transactions, TransactionSummary{Name: tx.Name, Readiness: Deferred, Operations: ops, Reasons: []string{"state-sensitive checks deferred until preceding transactions commit"}})
	}
	return result, nil
}

func ValidatePaths(program validate.Program, caps *pathcap.Set) error {
	for _, tx := range program.Transactions {
		if _, err := staticOperations(tx, caps); err != nil {
			return err
		}
		conditions := append(append([]ast.Condition{}, tx.Requires...), tx.Assertions...)
		for _, c := range conditions {
			if _, err := caps.Resolve(c.Path); err != nil {
				return err
			}
		}
	}
	return nil
}

func allowedRoots(caps *pathcap.Set) []string {
	var out []string
	for _, root := range caps.Roots() {
		if !root.Primary {
			out = append(out, root.Path)
		}
	}
	return out
}

func buildExact(tx validate.Transaction, caps *pathcap.Set, opts Options) (Plan, error) {
	p := Plan{APIVersion: "undo-cli/1", Name: tx.Name, ScriptPath: opts.ScriptPath, ScriptSHA256: opts.ScriptSHA256, Root: caps.Primary(), AllowedRoots: allowedRoots(caps), SafeToExecute: true}
	for _, c := range tx.Requires {
		planned, err := planCondition(c, caps, true)
		if err != nil {
			return Plan{}, err
		}
		p.Preconditions = append(p.Preconditions, planned)
		if planned.Result == nil || !*planned.Result {
			p.SafeToExecute = false
			p.Reasons = append(p.Reasons, "precondition failed: "+string(c.Kind)+" "+c.Path)
		}
	}
	state := newOverlay(caps)
	mutated := make(map[string]bool)
	for i, op := range tx.Operations {
		planned, err := exactOperation(i, op, state, mutated)
		if err != nil {
			return Plan{}, err
		}
		p.Operations = append(p.Operations, planned)
		p.Summary.RollbackBytes += planned.RollbackBytes
		switch planned.Effect {
		case EffectCreate:
			p.Summary.Creates++
		case EffectModify:
			p.Summary.Modifies++
		case EffectMove:
			p.Summary.Moves++
		case EffectDelete:
			p.Summary.Deletes++
		case EffectOverwrite:
			p.Summary.Overwrites++
		case EffectNoop:
			p.Summary.Noops++
		}
	}
	for _, c := range tx.Assertions {
		planned, err := planCondition(c, caps, false)
		if err != nil {
			return Plan{}, err
		}
		p.Assertions = append(p.Assertions, planned)
	}
	return p, nil
}

func planCondition(c ast.Condition, caps *pathcap.Set, evaluate bool) (PlannedCondition, error) {
	resolved, err := caps.Resolve(c.Path)
	if err != nil {
		return PlannedCondition{}, err
	}
	p := PlannedCondition{Kind: c.Kind, Path: resolved, Expected: c.Value}
	if evaluate {
		result, err := condition.Evaluate(c, caps)
		if err != nil {
			return PlannedCondition{}, err
		}
		value := result.Value
		p.Result, p.Actual = &value, result.Actual
	}
	return p, nil
}

func staticOperations(tx validate.Transaction, caps *pathcap.Set) ([]PlannedOperation, error) {
	result := make([]PlannedOperation, 0, len(tx.Operations))
	for i, op := range tx.Operations {
		p := PlannedOperation{Index: i, Kind: op.Kind, Effect: EffectDeferred, Overwrite: op.Overwrite}
		var err error
		if op.Kind == ast.Copy || op.Kind == ast.Move {
			src, e := caps.Resolve(op.Source)
			if e != nil {
				return nil, e
			}
			dst, e := caps.Resolve(op.Target)
			if e != nil {
				return nil, e
			}
			if src.Absolute == dst.Absolute {
				return nil, &Error{Code: Conflict, Message: "source and destination are identical"}
			}
			p.Source, p.Target = &src, dst
		} else {
			p.Target, err = caps.Resolve(op.Path)
			if err != nil {
				return nil, err
			}
		}
		result = append(result, p)
	}
	return result, nil
}

type node struct {
	exists, synthetic bool
	unstable          bool
	mode              fs.FileMode
	size, entries     int64
	bytes             int64
}
type overlay struct {
	caps   *pathcap.Set
	values map[string]node
}

func newOverlay(c *pathcap.Set) *overlay { return &overlay{caps: c, values: make(map[string]node)} }
func (o *overlay) get(p pathcap.ResolvedPath) (node, error) {
	if n, ok := o.values[p.Absolute]; ok {
		return n, nil
	}
	for parent := filepath.Dir(p.Absolute); parent != p.Absolute; parent = filepath.Dir(parent) {
		if n, ok := o.values[parent]; ok && n.synthetic {
			if !n.exists {
				return node{}, nil
			}
			if n.unstable {
				return node{}, &Error{Code: Conflict, Message: "path is beneath a directory changed earlier in the transaction"}
			}
			// A directory created earlier cannot contain an unrecorded disk entry.
			return node{}, nil
		}
		next := filepath.Dir(parent)
		if next == parent {
			break
		}
	}
	info, err := o.caps.Lstat(p)
	if errors.Is(err, fs.ErrNotExist) {
		o.values[p.Absolute] = node{}
		return node{}, nil
	}
	if err != nil {
		return node{}, err
	}
	n := node{exists: true, mode: info.Mode(), size: info.Size(), entries: 1, bytes: info.Size()}
	o.values[p.Absolute] = n
	return n, nil
}
func (o *overlay) set(p pathcap.ResolvedPath, n node) { o.values[p.Absolute] = n }

func exactOperation(index int, op ast.Statement, state *overlay, mutated map[string]bool) (PlannedOperation, error) {
	p := PlannedOperation{Index: index, Kind: op.Kind, Overwrite: op.Overwrite}
	if op.Kind == ast.Copy || op.Kind == ast.Move {
		return exactTransfer(p, op, state, mutated)
	}
	target, err := state.caps.Resolve(op.Path)
	if err != nil {
		return p, err
	}
	p.Target = target
	if mutated[target.Absolute] {
		return p, &Error{Code: Conflict, Message: "multiple mutations target " + target.Original}
	}
	current, err := state.get(target)
	if err != nil {
		return p, err
	}
	switch op.Kind {
	case ast.Mkdir:
		if current.exists {
			if !current.mode.IsDir() {
				return p, &Error{Code: Conflict, Message: "mkdir target exists and is not a directory"}
			}
			p.Effect = EffectNoop
			return p, nil
		}
		p.Effect = EffectCreate
		markDirectoryChain(state, target)
		mutated[target.Absolute] = true
	case ast.Write:
		if err := requireParent(state, target); err != nil {
			return p, err
		}
		if current.exists {
			if !current.mode.IsRegular() {
				return p, &Error{Code: UnsupportedFileType, Message: "write target is not a regular file"}
			}
			p.Effect, p.RollbackBytes = EffectModify, current.size
		} else {
			p.Effect = EffectCreate
		}
		state.set(target, node{exists: true, synthetic: true, mode: 0o600, size: int64(len(op.Content)), entries: 1, bytes: int64(len(op.Content))})
		mutated[target.Absolute] = true
	case ast.Replace:
		if !current.exists {
			return p, &Error{Code: SourceMissing, Message: "replace target does not exist"}
		}
		if !current.mode.IsRegular() {
			return p, &Error{Code: UnsupportedFileType, Message: "replace target is not regular"}
		}
		if current.synthetic {
			return p, &Error{Code: Conflict, Message: "state-sensitive replace after a prior write is conservatively rejected"}
		}
		found, err := condition.Evaluate(ast.Condition{Kind: ast.Contains, Path: op.Path, Value: op.Old}, state.caps)
		if err != nil {
			return p, err
		}
		if !found.Value {
			return p, &Error{Code: "E_REPLACE_PATTERN_NOT_FOUND", Message: "replace pattern not found"}
		}
		if op.Old == op.New {
			p.Effect = EffectNoop
			return p, nil
		}
		p.Effect, p.RollbackBytes = EffectModify, current.size
		mutated[target.Absolute] = true
	case ast.Delete:
		if !current.exists {
			return p, &Error{Code: SourceMissing, Message: "delete target does not exist"}
		}
		if target.Relative == "." {
			return p, &Error{Code: Conflict, Message: "cannot delete capability root"}
		}
		if state.hasChangedDescendant(target.Absolute) {
			return p, &Error{Code: Conflict, Message: "delete overlaps a path changed earlier in the transaction"}
		}
		if !supported(current.mode, true) {
			return p, &Error{Code: UnsupportedFileType, Message: "unsupported delete target"}
		}
		p.Effect, p.RollbackBytes = EffectDelete, current.size
		if current.mode.IsDir() {
			p.EntryCount, p.RollbackBytes, err = inspectTree(state.caps, target, false)
			if err != nil {
				return p, err
			}
		}
		state.set(target, node{synthetic: true})
		mutated[target.Absolute] = true
	}
	return p, nil
}

func markDirectoryChain(state *overlay, target pathcap.ResolvedPath) {
	current := target.Absolute
	for {
		resolved, err := state.caps.Resolve(current)
		if err != nil {
			return
		}
		if existing, err := state.get(resolved); err == nil && existing.exists {
			return
		}
		state.set(resolved, node{exists: true, synthetic: true, mode: fs.ModeDir, entries: 1})
		parent := filepath.Dir(current)
		if parent == current {
			return
		}
		current = parent
	}
}

func exactTransfer(p PlannedOperation, op ast.Statement, state *overlay, mutated map[string]bool) (PlannedOperation, error) {
	src, err := state.caps.Resolve(op.Source)
	if err != nil {
		return p, err
	}
	dst, err := state.caps.Resolve(op.Target)
	if err != nil {
		return p, err
	}
	p.Source, p.Target = &src, dst
	if src.Absolute == dst.Absolute {
		return p, &Error{Code: Conflict, Message: "source and destination are identical"}
	}
	if descendant(dst.Absolute, src.Absolute) || descendant(src.Absolute, dst.Absolute) {
		return p, &Error{Code: Conflict, Message: "cannot copy or move a directory into itself"}
	}
	if state.hasChangedDescendant(src.Absolute) || state.hasChangedDescendant(dst.Absolute) {
		return p, &Error{Code: Conflict, Message: "transfer overlaps a path changed earlier in the transaction"}
	}
	if mutated[dst.Absolute] {
		return p, &Error{Code: Conflict, Message: "multiple mutations target " + dst.Original}
	}
	source, err := state.get(src)
	if err != nil {
		return p, err
	}
	if !source.exists {
		return p, &Error{Code: SourceMissing, Message: "source does not exist: " + src.Original}
	}
	if op.Kind == ast.Copy && source.mode&fs.ModeSymlink != 0 {
		return p, &Error{Code: UnsupportedSymlinkCopy, Message: "copying symlinks is not supported"}
	}
	if !supported(source.mode, op.Kind == ast.Move) {
		return p, &Error{Code: UnsupportedFileType, Message: "unsupported source file type"}
	}
	if source.mode.IsDir() {
		entries, bytes, err := inspectTree(state.caps, src, op.Kind == ast.Copy)
		if err != nil {
			return p, err
		}
		source.entries, source.bytes = entries, bytes
	}
	dest, err := state.get(dst)
	if err != nil {
		return p, err
	}
	if dest.exists && !op.Overwrite {
		return p, &Error{Code: DestinationExists, Message: "destination exists without overwrite: " + dst.Original}
	}
	if err := requireParent(state, dst); err != nil {
		return p, err
	}
	p.EntryCount, p.Bytes = source.entries, source.bytes
	if dest.exists {
		p.Effect, p.RollbackBytes = EffectOverwrite, dest.bytes
		if dest.mode.IsDir() {
			_, p.RollbackBytes, err = inspectTree(state.caps, dst, false)
			if err != nil {
				return p, err
			}
		}
	} else if op.Kind == ast.Move {
		p.Effect = EffectMove
	} else {
		p.Effect = EffectCreate
	}
	source.synthetic = true
	source.unstable = source.mode.IsDir()
	state.set(dst, source)
	mutated[dst.Absolute] = true
	if op.Kind == ast.Move {
		state.set(src, node{synthetic: true})
		mutated[src.Absolute] = true
	}
	return p, nil
}

func requireParent(state *overlay, path pathcap.ResolvedPath) error {
	parent, err := state.caps.Resolve(filepath.Dir(path.Absolute))
	if err != nil {
		return err
	}
	n, err := state.get(parent)
	if err != nil {
		return err
	}
	if !n.exists || !n.mode.IsDir() {
		return &Error{Code: SourceMissing, Message: "destination parent does not exist or is not a directory"}
	}
	if n.unstable {
		return &Error{Code: Conflict, Message: "destination parent was changed earlier in the transaction"}
	}
	return nil
}

func (o *overlay) hasChangedDescendant(path string) bool {
	for candidate, n := range o.values {
		if n.synthetic && descendant(candidate, path) {
			return true
		}
	}
	return false
}

func descendant(path, parent string) bool {
	rel, err := filepath.Rel(parent, path)
	return err == nil && rel != "." && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator))
}
func supported(mode fs.FileMode, symlink bool) bool {
	return mode.IsRegular() || mode.IsDir() || symlink && mode&fs.ModeSymlink != 0
}

func inspectTree(caps *pathcap.Set, rootPath pathcap.ResolvedPath, rejectSymlink bool) (int64, int64, error) {
	root, err := caps.Handle(rootPath.RootID)
	if err != nil {
		return 0, 0, err
	}
	stack := []string{rootPath.Relative}
	var count, bytes int64
	for len(stack) > 0 {
		current := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		info, err := root.Lstat(current)
		if err != nil {
			return 0, 0, err
		}
		count++
		if info.Mode().IsRegular() {
			bytes += info.Size()
			continue
		}
		if info.Mode()&fs.ModeSymlink != 0 {
			if rejectSymlink {
				return 0, 0, &Error{Code: UnsupportedSymlinkCopy, Message: "directory contains symlink"}
			}
			continue
		}
		if !info.IsDir() {
			return 0, 0, &Error{Code: UnsupportedFileType, Message: "directory contains unsupported file type"}
		}
		f, err := root.Open(current)
		if err != nil {
			return 0, 0, err
		}
		entries, readErr := f.ReadDir(-1)
		closeErr := f.Close()
		if readErr != nil {
			return 0, 0, readErr
		}
		if closeErr != nil {
			return 0, 0, closeErr
		}
		sort.Slice(entries, func(i, j int) bool { return entries[i].Name() < entries[j].Name() })
		for i := len(entries) - 1; i >= 0; i-- {
			stack = append(stack, filepath.Join(current, entries[i].Name()))
		}
	}
	return count, bytes, nil
}
