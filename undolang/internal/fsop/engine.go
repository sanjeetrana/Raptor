package fsop

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"github.com/daniel-oluwadunsin/undolang/internal/lang/ast"
	"github.com/daniel-oluwadunsin/undolang/internal/pathcap"
	"github.com/daniel-oluwadunsin/undolang/internal/streamutil"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
)

type Engine struct {
	Capabilities *pathcap.Set
	backupDir    string
	backupRoot   *os.Root
}

func Open(capabilities *pathcap.Set, backupDir string) (*Engine, error) {
	if capabilities == nil {
		return nil, errors.New("capabilities are required")
	}
	absolute, err := filepath.Abs(backupDir)
	if err != nil {
		return nil, err
	}
	if err = os.MkdirAll(absolute, 0o700); err != nil {
		return nil, err
	}
	if err = os.Chmod(absolute, 0o700); err != nil {
		return nil, err
	}
	root, err := os.OpenRoot(absolute)
	if err != nil {
		return nil, err
	}
	return &Engine{Capabilities: capabilities, backupDir: absolute, backupRoot: root}, nil
}
func (e *Engine) Close() error {
	if e == nil || e.backupRoot == nil {
		return nil
	}
	err := e.backupRoot.Close()
	e.backupRoot = nil
	return err
}

func (e *Engine) Prepare(id string, op ast.Statement) (p Prepared, retErr error) {
	if id == "" || filepath.Base(id) != id || id == "." {
		return Prepared{}, &Error{Code: Conflict, Message: "invalid operation id", Path: id}
	}
	if err := e.backupRoot.MkdirAll(id, 0o700); err != nil {
		return Prepared{}, err
	}
	defer func() {
		if retErr != nil {
			_ = e.backupRoot.RemoveAll(id)
		}
	}()
	p = Prepared{OperationID: id, OperationHash: operationHash(op), Kind: op.Kind}
	var err error
	if op.Kind == ast.Copy || op.Kind == ast.Move {
		src, resolveErr := e.Capabilities.Resolve(op.Source)
		if resolveErr != nil {
			return p, resolveErr
		}
		dst, resolveErr := e.Capabilities.Resolve(op.Target)
		if resolveErr != nil {
			return p, resolveErr
		}
		p.Source, p.Target = &src, dst
		if src.Absolute == dst.Absolute {
			return p, &Error{Code: Conflict, Message: "source and destination are identical", Path: op.Source}
		}
		if err = e.ensureSource(src, op.Kind == ast.Copy); err != nil {
			return p, err
		}
		p.SourceDigest, _, _, p.SourceType, _, err = e.digest(src, op.Kind == ast.Copy)
		if err != nil {
			return p, err
		}
		if src.RootID == dst.RootID && (isDescendant(src.Relative, dst.Relative) || isDescendant(dst.Relative, src.Relative)) {
			return p, &Error{Code: Conflict, Message: "source and destination paths overlap", Path: op.Target}
		}
		p.PriorTarget, err = e.backup(dst, filepath.Join(id, "target"))
		if err != nil {
			return p, err
		}
		if p.PriorTarget.Present && !op.Overwrite {
			return p, &Error{Code: DestinationExists, Message: "destination exists without overwrite", Path: op.Target}
		}
		if err = e.ensureParent(dst); err != nil {
			return p, err
		}
		p.ExpectedDigest = p.SourceDigest
		p.Temporary, err = e.prepareTemporary(dst, id, p.OperationHash)
		if err != nil {
			return p, err
		}
		if op.Kind == ast.Move {
			p.SourceBackup, err = e.backup(src, filepath.Join(id, "source"))
			if err != nil {
				return p, err
			}
			if src.RootID == dst.RootID {
				p.Method = "rename"
			} else {
				p.Method = "copy-delete"
			}
		} else {
			p.Method = "copy"
		}
		return p, nil
	}
	target, resolveErr := e.Capabilities.Resolve(op.Path)
	if resolveErr != nil {
		return p, resolveErr
	}
	p.Target = target
	switch op.Kind {
	case ast.Mkdir:
		p.Created, err = e.missingDirectories(target)
	case ast.Write:
		if err = e.ensureParent(target); err == nil {
			p.PriorTarget, err = e.backup(target, filepath.Join(id, "target"))
		}
		if err == nil && p.PriorTarget.Present && p.PriorTarget.Type != Regular {
			err = &Error{Code: UnsupportedType, Message: "write target is not a regular file", Path: op.Path}
		}
		if err == nil {
			mode := fs.FileMode(0o644)
			if p.PriorTarget.Present {
				mode = p.PriorTarget.Mode
			}
			sum := sha256.Sum256([]byte(op.Content))
			p.ExpectedDigest = regularEntryDigest(hex.EncodeToString(sum[:]), mode)
			p.Temporary, err = e.prepareTemporary(target, id, p.OperationHash)
		}
	case ast.Replace:
		if err = e.ensureParent(target); err == nil {
			p.PriorTarget, err = e.backup(target, filepath.Join(id, "target"))
		}
		if err == nil && !p.PriorTarget.Present {
			err = &Error{Code: SourceMissing, Message: "replace target does not exist", Path: op.Path}
		}
		if err == nil && p.PriorTarget.Type != Regular {
			err = &Error{Code: UnsupportedType, Message: "replace target is not a regular file", Path: op.Path}
		}
		if err == nil {
			p.ExpectedDigest, p.MatchCount, err = e.expectedReplacement(target, []byte(op.Old), []byte(op.New), p.PriorTarget.Mode)
		}
		if err == nil {
			p.Temporary, err = e.prepareTemporary(target, id, p.OperationHash)
		}
	case ast.Delete:
		if target.Relative == "." {
			err = &Error{Code: Conflict, Message: "cannot delete capability root", Path: op.Path}
		} else {
			p.PriorTarget, err = e.backup(target, filepath.Join(id, "target"))
			if err == nil && !p.PriorTarget.Present {
				err = &Error{Code: SourceMissing, Message: "delete target does not exist", Path: op.Path}
			}
		}
	default:
		err = &Error{Code: Conflict, Message: "unsupported operation", Path: string(op.Kind)}
	}
	return p, err
}

func (e *Engine) Apply(p *Prepared, op ast.Statement) error {
	if err := matchPrepared(p, op); err != nil {
		return err
	}
	switch op.Kind {
	case ast.Mkdir:
		return e.applyMkdir(p)
	case ast.Copy:
		return e.applyCopy(p, false)
	case ast.Move:
		if p.Method == "rename" {
			return e.applyRenameMove(p)
		}
		return e.applyCopy(p, true)
	case ast.Write:
		return e.applyWrite(p, []byte(op.Content))
	case ast.Replace:
		return e.applyReplace(p, []byte(op.Old), []byte(op.New))
	case ast.Delete:
		return e.applyDelete(p)
	default:
		return &Error{Code: Conflict, Message: "unsupported operation", Path: string(op.Kind)}
	}
}

func (e *Engine) Verify(p *Prepared, op ast.Statement) error {
	if err := matchPrepared(p, op); err != nil {
		return err
	}
	if op.Kind == ast.Delete {
		_, err := e.Capabilities.Lstat(p.Target)
		if errors.Is(err, fs.ErrNotExist) {
			return nil
		}
		if err == nil {
			return &Error{Code: VerificationFailed, Message: "deleted path still exists", Path: p.Target.Original}
		}
		return err
	}
	if op.Kind == ast.Mkdir {
		info, err := e.Capabilities.Stat(p.Target)
		if err != nil {
			return err
		}
		if !info.IsDir() {
			return &Error{Code: VerificationFailed, Message: "mkdir target is not a directory", Path: p.Target.Original}
		}
		return nil
	}
	digest, _, _, _, _, err := e.digest(p.Target, false)
	if err != nil {
		return err
	}
	if digest != p.ExpectedDigest {
		return &Error{Code: VerificationFailed, Message: "operation result digest mismatch", Path: p.Target.Original}
	}
	return nil
}

func (e *Engine) Undo(p *Prepared) error {
	switch p.Kind {
	case ast.Mkdir:
		for i := len(p.Created) - 1; i >= 0; i-- {
			root, err := e.Capabilities.Handle(p.Created[i].RootID)
			if err != nil {
				return err
			}
			if err = root.Remove(p.Created[i].Relative); err != nil && !errors.Is(err, fs.ErrNotExist) {
				return err
			}
		}
		return nil
	case ast.Delete:
		if _, err := e.Capabilities.Lstat(p.Target); err == nil {
			return &Error{Code: Conflict, Message: "delete rollback target was recreated externally", Path: p.Target.Original}
		} else if !errors.Is(err, fs.ErrNotExist) {
			return err
		}
		return e.restore(p.PriorTarget, p.Target, p.OperationID+"-target")
	case ast.Move:
		if p.Method == "rename" {
			if err := e.verifyCurrent(p.Target, p.ExpectedDigest); err != nil {
				return err
			}
			root, err := e.Capabilities.Handle(p.Target.RootID)
			if err != nil {
				return err
			}
			if _, err = e.Capabilities.Lstat(*p.Source); err == nil {
				return &Error{Code: Conflict, Message: "move source was recreated externally", Path: p.Source.Original}
			} else if !errors.Is(err, fs.ErrNotExist) {
				return err
			}
			if err = root.Rename(p.Target.Relative, p.Source.Relative); err != nil {
				return err
			}
			return e.restore(p.PriorTarget, p.Target, p.OperationID+"-target")
		}
		if err := e.verifyCurrent(p.Target, p.ExpectedDigest); err != nil {
			return err
		}
		if err := e.remove(p.Target); err != nil {
			return err
		}
		if _, err := e.Capabilities.Lstat(*p.Source); err == nil {
			return &Error{Code: Conflict, Message: "move source was recreated externally", Path: p.Source.Original}
		} else if !errors.Is(err, fs.ErrNotExist) {
			return err
		}
		if err := e.restore(p.SourceBackup, *p.Source, p.OperationID+"-source"); err != nil {
			return err
		}
		return e.restore(p.PriorTarget, p.Target, p.OperationID+"-target")
	default:
		if err := e.verifyCurrent(p.Target, p.ExpectedDigest); err != nil {
			return err
		}
		if err := e.remove(p.Target); err != nil {
			return err
		}
		return e.restore(p.PriorTarget, p.Target, p.OperationID+"-target")
	}
}

func matchPrepared(p *Prepared, op ast.Statement) error {
	if p == nil || p.Kind != op.Kind || p.OperationHash != operationHash(op) {
		return &Error{Code: Conflict, Message: "prepared metadata does not match operation"}
	}
	return nil
}

func operationHash(op ast.Statement) string {
	h := sha256.New()
	for _, value := range []string{string(op.Kind), op.Path, op.Source, op.Target, op.Old, op.New, op.Content} {
		h.Write([]byte(value))
		h.Write([]byte{0})
	}
	if op.Overwrite {
		h.Write([]byte{1})
	} else {
		h.Write([]byte{0})
	}
	return hex.EncodeToString(h.Sum(nil))
}

func (e *Engine) ensureSource(path pathcap.ResolvedPath, rejectSymlink bool) error {
	info, err := e.Capabilities.Lstat(path)
	if errors.Is(err, fs.ErrNotExist) {
		return &Error{Code: SourceMissing, Message: "source does not exist", Path: path.Original}
	}
	if err != nil {
		return err
	}
	kind := classify(info.Mode())
	if kind == None {
		return &Error{Code: UnsupportedType, Message: "unsupported source type", Path: path.Original}
	}
	if rejectSymlink && kind == Symlink {
		return &Error{Code: UnsupportedSymlinkCopy, Message: "symlink copy is unsupported", Path: path.Original}
	}
	return nil
}
func (e *Engine) ensureParent(path pathcap.ResolvedPath) error {
	root, err := e.Capabilities.Handle(path.RootID)
	if err != nil {
		return err
	}
	return validateNoSymlinkParents(root, path.Relative)
}
func (e *Engine) digest(path pathcap.ResolvedPath, rejectSymlink bool) (string, int64, int64, EntryType, fs.FileMode, error) {
	root, err := e.Capabilities.Handle(path.RootID)
	if err != nil {
		return "", 0, 0, None, 0, err
	}
	return digestEntry(root, path.Relative, rejectSymlink)
}

func (e *Engine) backup(path pathcap.ResolvedPath, backupRel string) (Backup, error) {
	info, err := e.Capabilities.Lstat(path)
	if errors.Is(err, fs.ErrNotExist) {
		return Backup{}, nil
	}
	if err != nil {
		return Backup{}, err
	}
	kind := classify(info.Mode())
	if kind == None {
		return Backup{}, &Error{Code: UnsupportedType, Message: "unsupported target type", Path: path.Original}
	}
	digest, bytes, count, _, mode, err := e.digest(path, false)
	if err != nil {
		return Backup{}, err
	}
	root, err := e.Capabilities.Handle(path.RootID)
	if err != nil {
		return Backup{}, err
	}
	if err = e.backupRoot.MkdirAll(filepath.Dir(backupRel), 0o700); err != nil {
		return Backup{}, err
	}
	if err = copyEntry(root, path.Relative, e.backupRoot, backupRel, true); err != nil {
		return Backup{}, err
	}
	backupDigest, _, _, _, _, err := digestEntry(e.backupRoot, backupRel, false)
	if err != nil {
		return Backup{}, err
	}
	if backupDigest != digest {
		return Backup{}, &Error{Code: VerificationFailed, Message: "backup verification failed", Path: path.Original}
	}
	return Backup{Present: true, Relative: backupRel, Type: kind, Mode: mode, Digest: digest, Bytes: bytes, Entries: count}, nil
}

func (e *Engine) missingDirectories(target pathcap.ResolvedPath) ([]pathcap.ResolvedPath, error) {
	if target.Relative == "." {
		return nil, &Error{Code: Conflict, Message: "cannot create capability root", Path: target.Original}
	}
	root, err := e.Capabilities.Handle(target.RootID)
	if err != nil {
		return nil, err
	}
	parts := strings.Split(filepath.Clean(target.Relative), string(filepath.Separator))
	current := ""
	var missing []pathcap.ResolvedPath
	for _, part := range parts {
		current = filepath.Join(current, part)
		info, statErr := root.Lstat(current)
		if errors.Is(statErr, fs.ErrNotExist) {
			resolved, resolveErr := e.Capabilities.Resolve(filepath.Join(target.Root, current))
			if resolveErr != nil {
				return nil, resolveErr
			}
			missing = append(missing, resolved)
			continue
		}
		if statErr != nil {
			return nil, statErr
		}
		if info.Mode()&fs.ModeSymlink != 0 || !info.IsDir() {
			return nil, &Error{Code: Conflict, Message: "mkdir path component is not a directory", Path: current}
		}
	}
	return missing, nil
}

func (e *Engine) applyMkdir(p *Prepared) error {
	for _, path := range p.Created {
		root, err := e.Capabilities.Handle(path.RootID)
		if err != nil {
			return err
		}
		if err = root.Mkdir(path.Relative, 0o755); err != nil {
			return err
		}
	}
	return syncDirectory(filepath.Dir(p.Target.Absolute))
}

func (e *Engine) applyCopy(p *Prepared, removeSource bool) error {
	if err := e.validatePrior(p.Target, p.PriorTarget); err != nil {
		return err
	}
	if p.Source == nil {
		return &Error{Code: Conflict, Message: "missing source metadata"}
	}
	digest, _, _, _, _, err := e.digest(*p.Source, p.Kind == ast.Copy)
	if err != nil {
		return err
	}
	if digest != p.SourceDigest {
		return &Error{Code: VerificationFailed, Message: "source changed after preparation", Path: p.Source.Original}
	}
	srcRoot, err := e.Capabilities.Handle(p.Source.RootID)
	if err != nil {
		return err
	}
	dstRoot, err := e.Capabilities.Handle(p.Target.RootID)
	if err != nil {
		return err
	}
	temp := p.Temporary
	if temp == "" {
		return &Error{Code: Conflict, Message: "missing prepared temporary path", Path: p.Target.Original}
	}
	defer dstRoot.RemoveAll(temp)
	if err = copyEntry(srcRoot, p.Source.Relative, dstRoot, temp, p.Kind == ast.Move); err != nil {
		return err
	}
	if err = e.install(dstRoot, temp, p.Target); err != nil {
		return err
	}
	if removeSource {
		if err = e.remove(*p.Source); err != nil {
			return err
		}
	}
	return nil
}

func (e *Engine) applyRenameMove(p *Prepared) error {
	if err := e.validatePrior(p.Target, p.PriorTarget); err != nil {
		return err
	}
	if p.Source == nil {
		return &Error{Code: Conflict, Message: "missing source metadata"}
	}
	digest, _, _, _, _, err := e.digest(*p.Source, false)
	if err != nil {
		return err
	}
	if digest != p.SourceDigest {
		return &Error{Code: VerificationFailed, Message: "source changed after preparation", Path: p.Source.Original}
	}
	root, err := e.Capabilities.Handle(p.Target.RootID)
	if err != nil {
		return err
	}
	if p.PriorTarget.Present {
		if err = e.remove(p.Target); err != nil {
			return err
		}
	}
	if err = root.Rename(p.Source.Relative, p.Target.Relative); err != nil {
		if p.PriorTarget.Present {
			if restoreErr := e.restore(p.PriorTarget, p.Target, p.OperationID+"-target"); restoreErr != nil {
				return errors.Join(err, restoreErr)
			}
		}
		if isCrossDevice(err) {
			p.Method = "copy-delete"
			return e.applyCopy(p, true)
		}
		return err
	}
	p.ExpectedDigest = p.SourceDigest
	return syncDirectory(filepath.Dir(p.Target.Absolute))
}

func (e *Engine) applyWrite(p *Prepared, content []byte) error {
	if err := e.validatePrior(p.Target, p.PriorTarget); err != nil {
		return err
	}
	root, err := e.Capabilities.Handle(p.Target.RootID)
	if err != nil {
		return err
	}
	temp, err := createTemporaryFile(root, p.Temporary)
	if err != nil {
		return err
	}
	defer root.RemoveAll(temp)
	file, err := root.OpenFile(temp, os.O_WRONLY, 0)
	if err != nil {
		return err
	}
	_, writeErr := io.Copy(file, bytes.NewReader(content))
	if writeErr == nil {
		writeErr = file.Sync()
	}
	mode := fs.FileMode(0o644)
	if p.PriorTarget.Present {
		mode = p.PriorTarget.Mode.Perm()
	}
	if writeErr == nil {
		writeErr = file.Chmod(mode)
	}
	closeErr := file.Close()
	if writeErr != nil {
		return writeErr
	}
	if closeErr != nil {
		return closeErr
	}
	if err = e.install(root, temp, p.Target); err != nil {
		return err
	}
	return e.verifyCurrent(p.Target, p.ExpectedDigest)
}

func isDescendant(parent, child string) bool {
	rel, err := filepath.Rel(filepath.Clean(parent), filepath.Clean(child))
	return err == nil && rel != "." && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator))
}

func (e *Engine) applyReplace(p *Prepared, old, replacement []byte) error {
	if err := e.validatePrior(p.Target, p.PriorTarget); err != nil {
		return err
	}
	root, err := e.Capabilities.Handle(p.Target.RootID)
	if err != nil {
		return err
	}
	source, err := root.Open(p.Target.Relative)
	if err != nil {
		return err
	}
	if bytes.Equal(old, replacement) {
		matches, _, replaceErr := streamutil.ReplaceAll(io.Discard, source, old, replacement)
		closeErr := source.Close()
		if replaceErr != nil {
			return replaceErr
		}
		if closeErr != nil {
			return closeErr
		}
		if matches == 0 {
			return &Error{Code: ReplacePatternNotFound, Message: "replace pattern not found", Path: p.Target.Original}
		}
		if matches != p.MatchCount {
			return &Error{Code: VerificationFailed, Message: "replace source changed after preparation", Path: p.Target.Original}
		}
		return nil
	}
	temp, err := createTemporaryFile(root, p.Temporary)
	if err != nil {
		source.Close()
		return err
	}
	defer root.RemoveAll(temp)
	target, err := root.OpenFile(temp, os.O_WRONLY, 0)
	if err != nil {
		source.Close()
		return err
	}
	matches, _, replaceErr := streamutil.ReplaceAll(target, source, old, replacement)
	sourceClose := source.Close()
	if replaceErr == nil {
		replaceErr = sourceClose
	}
	if replaceErr == nil && matches == 0 {
		replaceErr = &Error{Code: ReplacePatternNotFound, Message: "replace pattern not found", Path: p.Target.Original}
	}
	if replaceErr == nil {
		replaceErr = target.Sync()
	}
	if replaceErr == nil {
		replaceErr = target.Chmod(p.PriorTarget.Mode.Perm())
	}
	targetClose := target.Close()
	if replaceErr == nil {
		replaceErr = targetClose
	}
	if replaceErr != nil {
		return replaceErr
	}
	if err = e.install(root, temp, p.Target); err != nil {
		return err
	}
	if matches != p.MatchCount {
		return &Error{Code: VerificationFailed, Message: "replace source changed after preparation", Path: p.Target.Original}
	}
	return e.verifyCurrent(p.Target, p.ExpectedDigest)
}

func (e *Engine) applyDelete(p *Prepared) error {
	if err := e.validatePrior(p.Target, p.PriorTarget); err != nil {
		return err
	}
	return e.remove(p.Target)
}

func createTemporaryFile(root *os.Root, rel string) (string, error) {
	if rel == "" {
		return "", &Error{Code: Conflict, Message: "missing prepared temporary path"}
	}
	file, err := root.OpenFile(rel, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return "", err
	}
	if err = file.Close(); err != nil {
		root.Remove(rel)
		return "", err
	}
	return rel, nil
}

func (e *Engine) prepareTemporary(target pathcap.ResolvedPath, id, hash string) (string, error) {
	root, err := e.Capabilities.Handle(target.RootID)
	if err != nil {
		return "", err
	}
	rel := filepath.Join(filepath.Dir(target.Relative), ".undo-tmp-"+id+"-"+hash[:12])
	if _, err = root.Lstat(rel); err == nil {
		return "", &Error{Code: Conflict, Message: "prepared temporary path already exists", Path: rel}
	} else if !errors.Is(err, fs.ErrNotExist) {
		return "", err
	}
	return rel, nil
}

func (e *Engine) expectedReplacement(path pathcap.ResolvedPath, old, replacement []byte, mode fs.FileMode) (string, int64, error) {
	root, err := e.Capabilities.Handle(path.RootID)
	if err != nil {
		return "", 0, err
	}
	source, err := root.Open(path.Relative)
	if err != nil {
		return "", 0, err
	}
	h := sha256.New()
	matches, _, replaceErr := streamutil.ReplaceAll(h, source, old, replacement)
	closeErr := source.Close()
	if replaceErr != nil {
		return "", 0, replaceErr
	}
	if closeErr != nil {
		return "", 0, closeErr
	}
	if matches == 0 {
		return "", 0, &Error{Code: ReplacePatternNotFound, Message: "replace pattern not found", Path: path.Original}
	}
	return regularEntryDigest(hex.EncodeToString(h.Sum(nil)), mode), matches, nil
}
func (e *Engine) install(root *os.Root, temp string, target pathcap.ResolvedPath) error {
	if err := e.removeIfExists(target); err != nil {
		return err
	}
	if err := root.Rename(temp, target.Relative); err != nil {
		return err
	}
	return syncDirectory(filepath.Dir(target.Absolute))
}
func (e *Engine) removeIfExists(path pathcap.ResolvedPath) error {
	_, err := e.Capabilities.Lstat(path)
	if errors.Is(err, fs.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	return e.remove(path)
}
func (e *Engine) remove(path pathcap.ResolvedPath) error {
	if path.Relative == "." {
		return &Error{Code: Conflict, Message: "refusing to remove capability root", Path: path.Original}
	}
	root, err := e.Capabilities.Handle(path.RootID)
	if err != nil {
		return err
	}
	if err = root.RemoveAll(path.Relative); err != nil {
		return err
	}
	return syncDirectory(filepath.Dir(path.Absolute))
}

func (e *Engine) validatePrior(path pathcap.ResolvedPath, backup Backup) error {
	if !backup.Present {
		_, err := e.Capabilities.Lstat(path)
		if errors.Is(err, fs.ErrNotExist) {
			return nil
		}
		if err == nil {
			return &Error{Code: Conflict, Message: "destination appeared after preparation", Path: path.Original}
		}
		return err
	}
	digest, _, _, _, _, err := e.digest(path, false)
	if err != nil {
		return err
	}
	if digest != backup.Digest {
		return &Error{Code: VerificationFailed, Message: "target changed after backup", Path: path.Original}
	}
	return nil
}
func (e *Engine) verifyCurrent(path pathcap.ResolvedPath, want string) error {
	if want == "" {
		return nil
	}
	digest, _, _, _, _, err := e.digest(path, false)
	if err != nil {
		return err
	}
	if digest != want {
		return &Error{Code: VerificationFailed, Message: "current target differs from applied result", Path: path.Original}
	}
	return nil
}

func (e *Engine) restore(backup Backup, target pathcap.ResolvedPath, seed string) error {
	if !backup.Present {
		return nil
	}
	root, err := e.Capabilities.Handle(target.RootID)
	if err != nil {
		return err
	}
	temp := recoveryTemporary(target.Relative, seed)
	if _, err = root.Lstat(temp); err == nil {
		return &Error{Code: Conflict, Message: "rollback temporary path already exists", Path: temp}
	} else if !errors.Is(err, fs.ErrNotExist) {
		return err
	}
	defer root.RemoveAll(temp)
	if err = copyEntry(e.backupRoot, backup.Relative, root, temp, true); err != nil {
		return err
	}
	digest, _, _, _, _, err := digestEntry(root, temp, false)
	if err != nil {
		return err
	}
	if digest != backup.Digest {
		return &Error{Code: VerificationFailed, Message: "restored backup digest mismatch", Path: target.Original}
	}
	return e.install(root, temp, target)
}

func recoveryTemporary(target, seed string) string {
	sum := sha256.Sum256([]byte(seed + "\x00" + target))
	return filepath.Join(filepath.Dir(target), ".undo-restore-"+hex.EncodeToString(sum[:6]))
}

// Classify compares the current filesystem against the durable before and
// expected-after descriptors captured by Prepare.
func (e *Engine) Classify(p Prepared) (Disposition, error) {
	beforeTarget, err := e.matchesBackup(p.Target, p.PriorTarget)
	if err != nil {
		return Ambiguous, err
	}
	if p.Kind == ast.Mkdir {
		created := false
		for _, path := range p.Created {
			info, statErr := e.Capabilities.Lstat(path)
			if errors.Is(statErr, fs.ErrNotExist) {
				continue
			}
			if statErr != nil || !info.IsDir() {
				return Ambiguous, statErr
			}
			created = true
		}
		if created {
			return After, nil
		}
		return Before, nil
	}
	if p.Kind == ast.Move {
		if p.Source == nil {
			return Ambiguous, &Error{Code: Conflict, Message: "missing move source metadata"}
		}
		sourceBefore, sourceErr := e.matchesDigest(*p.Source, p.SourceDigest)
		if sourceErr != nil {
			return Ambiguous, sourceErr
		}
		sourceAbsent, sourceErr := e.isAbsent(*p.Source)
		if sourceErr != nil {
			return Ambiguous, sourceErr
		}
		targetAfter, targetErr := e.matchesDigest(p.Target, p.ExpectedDigest)
		if targetErr != nil {
			return Ambiguous, targetErr
		}
		if sourceBefore && beforeTarget {
			return Before, nil
		}
		if sourceAbsent && targetAfter {
			return After, nil
		}
		return Ambiguous, nil
	}
	if p.Kind == ast.Delete {
		absent, absentErr := e.isAbsent(p.Target)
		if absentErr != nil {
			return Ambiguous, absentErr
		}
		if beforeTarget {
			return Before, nil
		}
		if absent {
			return After, nil
		}
		return Ambiguous, nil
	}
	afterTarget, err := e.matchesDigest(p.Target, p.ExpectedDigest)
	if err != nil {
		return Ambiguous, err
	}
	if beforeTarget {
		return Before, nil
	}
	if afterTarget {
		return After, nil
	}
	return Ambiguous, nil
}

func (e *Engine) matchesBackup(path pathcap.ResolvedPath, backup Backup) (bool, error) {
	if !backup.Present {
		return e.isAbsent(path)
	}
	return e.matchesDigest(path, backup.Digest)
}

func (e *Engine) matchesDigest(path pathcap.ResolvedPath, want string) (bool, error) {
	if want == "" {
		return false, nil
	}
	digest, _, _, _, _, err := e.digest(path, false)
	if errors.Is(err, fs.ErrNotExist) {
		return false, nil
	}
	return digest == want, err
}

func (e *Engine) isAbsent(path pathcap.ResolvedPath) (bool, error) {
	_, err := e.Capabilities.Lstat(path)
	if errors.Is(err, fs.ErrNotExist) {
		return true, nil
	}
	return false, err
}

// CleanupTemporaries removes only deterministic names recorded or derived for
// this operation. It never scans or removes arbitrary similarly named files.
func (e *Engine) CleanupTemporaries(p Prepared) error {
	var errs []error
	remove := func(path pathcap.ResolvedPath, rel string) {
		if rel == "" {
			return
		}
		root, err := e.Capabilities.Handle(path.RootID)
		if err == nil {
			err = root.RemoveAll(rel)
		}
		if err != nil && !errors.Is(err, fs.ErrNotExist) {
			errs = append(errs, err)
		}
	}
	remove(p.Target, p.Temporary)
	remove(p.Target, recoveryTemporary(p.Target.Relative, p.OperationID+"-target"))
	if p.Source != nil {
		remove(*p.Source, recoveryTemporary(p.Source.Relative, p.OperationID+"-source"))
	}
	return errors.Join(errs...)
}
