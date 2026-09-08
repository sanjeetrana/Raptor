package condition

import (
	"errors"
	"fmt"
	"io/fs"
	"strings"

	"github.com/daniel-oluwadunsin/undolang/internal/lang/ast"
	"github.com/daniel-oluwadunsin/undolang/internal/pathcap"
	"github.com/daniel-oluwadunsin/undolang/internal/streamutil"
)

type Result struct {
	Value  bool   `json:"value"`
	Actual string `json:"actual,omitempty"`
}

func Evaluate(c ast.Condition, capabilities *pathcap.Set) (Result, error) {
	path, err := capabilities.Resolve(c.Path)
	if err != nil {
		return Result{}, err
	}
	switch c.Kind {
	case ast.Exists, ast.NotExists:
		_, statErr := capabilities.Lstat(path)
		exists := statErr == nil
		if statErr != nil && !errors.Is(statErr, fs.ErrNotExist) {
			return Result{}, statErr
		}
		if c.Kind == ast.NotExists {
			exists = !exists
		}
		return Result{Value: exists}, nil
	case ast.IsFile, ast.IsDir:
		info, statErr := capabilities.Lstat(path)
		if errors.Is(statErr, fs.ErrNotExist) {
			return Result{Value: false}, nil
		}
		if statErr != nil {
			return Result{}, statErr
		}
		if info.Mode()&fs.ModeSymlink != 0 {
			return Result{Value: false}, nil
		}
		if c.Kind == ast.IsFile {
			return Result{Value: info.Mode().IsRegular()}, nil
		}
		return Result{Value: info.IsDir()}, nil
	case ast.Contains, ast.SHA256:
		info, statErr := capabilities.Stat(path)
		if statErr != nil {
			return Result{}, statErr
		}
		if !info.Mode().IsRegular() {
			return Result{}, fmt.Errorf("condition requires regular file: %s", c.Path)
		}
		file, openErr := capabilities.OpenFile(path)
		if openErr != nil {
			return Result{}, openErr
		}
		defer file.Close()
		if c.Kind == ast.Contains {
			found, searchErr := streamutil.Contains(file, []byte(c.Value))
			return Result{Value: found}, searchErr
		}
		digest, _, hashErr := streamutil.SHA256(file)
		return Result{Value: strings.EqualFold(digest, c.Value), Actual: digest}, hashErr
	default:
		return Result{}, fmt.Errorf("unsupported condition %q", c.Kind)
	}
}
