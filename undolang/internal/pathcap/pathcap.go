package pathcap

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

const (
	Invalid        = "E_PATH_INVALID"
	Escape         = "E_PATH_ESCAPE"
	AbsoluteDenied = "E_ABSOLUTE_DENIED"
	Reserved       = "E_RESERVED_PATH"
)

type Error struct {
	Code    string
	Message string
	Path    string
	Root    string
	Cause   error
}

func (e *Error) Error() string {
	if e.Root != "" {
		return fmt.Sprintf("%s: %s: %q (root %q)", e.Code, e.Message, e.Path, e.Root)
	}
	return fmt.Sprintf("%s: %s: %q", e.Code, e.Message, e.Path)
}
func (e *Error) Unwrap() error { return e.Cause }

type CapabilityRoot struct {
	ID      int
	Path    string
	Primary bool
	handle  *os.Root
}

type Set struct {
	roots []CapabilityRoot
}

type ResolvedPath struct {
	RootID   int    `json:"root_id"`
	Root     string `json:"root"`
	Relative string `json:"relative"`
	Absolute string `json:"absolute"`
	Original string `json:"original"`
}

func Open(primary string, allowed []string) (*Set, error) {
	if primary == "" {
		var err error
		primary, err = os.Getwd()
		if err != nil {
			return nil, &Error{Code: Invalid, Message: "determine current working directory", Cause: err}
		}
	}
	paths := append([]string{primary}, allowed...)
	seen := make(map[string]bool)
	set := &Set{}
	for i, path := range paths {
		absolute, err := filepath.Abs(path)
		if err != nil {
			set.Close()
			return nil, &Error{Code: Invalid, Message: "make capability root absolute", Path: path, Cause: err}
		}
		absolute = filepath.Clean(absolute)
		canonical, err := filepath.EvalSymlinks(absolute)
		if err != nil {
			set.Close()
			return nil, &Error{Code: Invalid, Message: "canonicalize capability root", Path: path, Cause: err}
		}
		absolute = filepath.Clean(canonical)
		if seen[absolute] {
			continue
		}
		info, err := os.Stat(absolute)
		if err != nil {
			set.Close()
			return nil, &Error{Code: Invalid, Message: "capability root is unavailable", Path: path, Cause: err}
		}
		if !info.IsDir() {
			set.Close()
			return nil, &Error{Code: Invalid, Message: "capability root is not a directory", Path: path}
		}
		handle, err := os.OpenRoot(absolute)
		if err != nil {
			set.Close()
			return nil, &Error{Code: Invalid, Message: "open capability root", Path: path, Cause: err}
		}
		set.roots = append(set.roots, CapabilityRoot{ID: len(set.roots), Path: absolute, Primary: i == 0, handle: handle})
		seen[absolute] = true
	}
	return set, nil
}

func (s *Set) Close() error {
	var errs []error
	for i := range s.roots {
		if s.roots[i].handle != nil {
			errs = append(errs, s.roots[i].handle.Close())
			s.roots[i].handle = nil
		}
	}
	return errors.Join(errs...)
}

func (s *Set) Roots() []CapabilityRoot {
	out := make([]CapabilityRoot, len(s.roots))
	copy(out, s.roots)
	for i := range out {
		out[i].handle = nil
	}
	return out
}

func (s *Set) Primary() string {
	if len(s.roots) == 0 {
		return ""
	}
	return s.roots[0].Path
}

func (s *Set) Resolve(path string) (ResolvedPath, error) {
	if len(s.roots) == 0 {
		return ResolvedPath{}, &Error{Code: Invalid, Message: "no capability roots are open", Path: path}
	}
	if path == "" {
		return ResolvedPath{}, &Error{Code: Invalid, Message: "path must not be empty", Path: path}
	}
	if !filepath.IsAbs(path) {
		clean := filepath.Clean(path)
		if escapes(clean) {
			return ResolvedPath{}, &Error{Code: Escape, Message: "relative path escapes transaction root", Path: path, Root: s.roots[0].Path}
		}
		if reserved(clean) {
			return ResolvedPath{}, &Error{Code: Reserved, Message: "runtime state path is reserved", Path: path, Root: s.roots[0].Path}
		}
		mapped, err := canonicalizeParent(filepath.Join(s.roots[0].Path, clean))
		if err != nil {
			return ResolvedPath{}, &Error{Code: Invalid, Message: "canonicalize path parent", Path: path, Cause: err}
		}
		if !within(mapped, s.roots[0].Path) {
			return ResolvedPath{}, &Error{Code: Escape, Message: "path parent escapes transaction root through a symlink", Path: path, Root: s.roots[0].Path}
		}
		if within(mapped, filepath.Join(s.roots[0].Path, ".undo")) {
			return ResolvedPath{}, &Error{Code: Reserved, Message: "runtime state path is reserved", Path: path, Root: s.roots[0].Path}
		}
		resolved := s.resolved(s.roots[0], clean, path)
		resolved.Absolute = mapped
		return resolved, nil
	}
	absolute, err := canonicalizeParent(filepath.Clean(path))
	if err != nil {
		return ResolvedPath{}, &Error{Code: Invalid, Message: "canonicalize absolute path", Path: path, Cause: err}
	}
	if within(absolute, filepath.Join(s.roots[0].Path, ".undo")) {
		return ResolvedPath{}, &Error{Code: Reserved, Message: "runtime state path is reserved", Path: path, Root: s.roots[0].Path}
	}
	candidates := make([]CapabilityRoot, 0, len(s.roots))
	for _, root := range s.roots {
		if within(absolute, root.Path) {
			candidates = append(candidates, root)
		}
	}
	if len(candidates) == 0 {
		return ResolvedPath{}, &Error{Code: AbsoluteDenied, Message: "absolute path is outside declared capability roots", Path: path, Root: s.roots[0].Path}
	}
	sort.Slice(candidates, func(i, j int) bool { return len(candidates[i].Path) > len(candidates[j].Path) })
	root := candidates[0]
	rel, err := filepath.Rel(root.Path, absolute)
	if err != nil || escapes(rel) {
		return ResolvedPath{}, &Error{Code: Escape, Message: "cannot map path beneath capability root", Path: path, Root: root.Path, Cause: err}
	}
	if root.Primary && reserved(rel) {
		return ResolvedPath{}, &Error{Code: Reserved, Message: "runtime state path is reserved", Path: path, Root: root.Path}
	}
	return s.resolved(root, rel, path), nil
}

func canonicalizeParent(path string) (string, error) {
	parent, err := canonicalizeForMapping(filepath.Dir(path))
	if err != nil {
		return "", err
	}
	return filepath.Join(parent, filepath.Base(path)), nil
}

// canonicalizeForMapping resolves symlinks in the deepest existing ancestor,
// then appends any not-yet-created suffix. Actual access remains enforced by
// os.Root; this normalization is only capability selection.
func canonicalizeForMapping(path string) (string, error) {
	current := filepath.Clean(path)
	var suffix []string
	for {
		canonical, err := filepath.EvalSymlinks(current)
		if err == nil {
			for index := len(suffix) - 1; index >= 0; index-- {
				canonical = filepath.Join(canonical, suffix[index])
			}
			return filepath.Clean(canonical), nil
		}
		if !errors.Is(err, fs.ErrNotExist) {
			return "", err
		}
		parent := filepath.Dir(current)
		if parent == current {
			return "", err
		}
		suffix = append(suffix, filepath.Base(current))
		current = parent
	}
}

func (s *Set) resolved(root CapabilityRoot, rel, original string) ResolvedPath {
	return ResolvedPath{RootID: root.ID, Root: root.Path, Relative: rel, Absolute: filepath.Join(root.Path, rel), Original: original}
}

func within(path, root string) bool {
	rel, err := filepath.Rel(root, path)
	return err == nil && !escapes(rel)
}
func escapes(path string) bool {
	return path == ".." || strings.HasPrefix(path, ".."+string(filepath.Separator)) || filepath.IsAbs(path)
}
func reserved(path string) bool {
	clean := filepath.Clean(path)
	return clean == ".undo" || strings.HasPrefix(clean, ".undo"+string(filepath.Separator))
}

func (s *Set) Handle(id int) (*os.Root, error) {
	if id < 0 || id >= len(s.roots) || s.roots[id].handle == nil {
		return nil, &Error{Code: Invalid, Message: "unknown or closed capability root"}
	}
	return s.roots[id].handle, nil
}

func (s *Set) Lstat(path ResolvedPath) (fs.FileInfo, error) {
	root, err := s.Handle(path.RootID)
	if err != nil {
		return nil, err
	}
	return root.Lstat(path.Relative)
}
func (s *Set) Stat(path ResolvedPath) (fs.FileInfo, error) {
	root, err := s.Handle(path.RootID)
	if err != nil {
		return nil, err
	}
	info, err := root.Lstat(path.Relative)
	if err != nil {
		return nil, err
	}
	if info.Mode()&fs.ModeSymlink != 0 {
		return nil, &Error{Code: Invalid, Message: "refusing to follow a symlink for target inspection", Path: path.Original, Root: path.Root}
	}
	return root.Stat(path.Relative)
}
func (s *Set) OpenFile(path ResolvedPath) (*os.File, error) {
	root, err := s.Handle(path.RootID)
	if err != nil {
		return nil, err
	}
	info, err := root.Lstat(path.Relative)
	if err != nil {
		return nil, err
	}
	if info.Mode()&fs.ModeSymlink != 0 {
		return nil, &Error{Code: Invalid, Message: "refusing to open a symlink target", Path: path.Original, Root: path.Root}
	}
	return root.Open(path.Relative)
}
