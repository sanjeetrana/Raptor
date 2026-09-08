package fsop

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/daniel-oluwadunsin/undolang/internal/streamutil"
)

func classify(mode fs.FileMode) EntryType {
	switch {
	case mode.IsRegular():
		return Regular
	case mode.IsDir():
		return Directory
	case mode&fs.ModeSymlink != 0:
		return Symlink
	default:
		return None
	}
}

func digestEntry(root *os.Root, rel string, rejectSymlink bool) (string, int64, int64, EntryType, fs.FileMode, error) {
	info, err := root.Lstat(rel)
	if err != nil {
		return "", 0, 0, None, 0, err
	}
	kind := classify(info.Mode())
	if kind == None {
		return "", 0, 0, None, 0, &Error{Code: UnsupportedType, Message: "unsupported filesystem object", Path: rel}
	}
	if kind == Symlink && rejectSymlink {
		return "", 0, 0, None, 0, &Error{Code: UnsupportedSymlinkCopy, Message: "symlink copy is unsupported", Path: rel}
	}
	h := sha256.New()
	type item struct{ path, name string }
	stack := []item{{rel, "."}}
	var bytes, count int64
	for len(stack) > 0 {
		current := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		entry, err := root.Lstat(current.path)
		if err != nil {
			return "", 0, 0, None, 0, err
		}
		entryKind := classify(entry.Mode())
		if entryKind == None {
			return "", 0, 0, None, 0, &Error{Code: UnsupportedType, Message: "tree contains unsupported object", Path: current.path}
		}
		if entryKind == Symlink && rejectSymlink {
			return "", 0, 0, None, 0, &Error{Code: UnsupportedSymlinkCopy, Message: "tree contains symlink", Path: current.path}
		}
		count++
		fmt.Fprintf(h, "%s\x00%s\x00%o\x00", current.name, entryKind, entry.Mode().Perm())
		switch entryKind {
		case Regular:
			file, err := root.Open(current.path)
			if err != nil {
				return "", 0, 0, None, 0, err
			}
			digest, n, hashErr := streamutil.SHA256(file)
			closeErr := file.Close()
			if hashErr != nil {
				return "", 0, 0, None, 0, hashErr
			}
			if closeErr != nil {
				return "", 0, 0, None, 0, closeErr
			}
			fmt.Fprint(h, digest)
			bytes += n
		case Symlink:
			target, err := root.Readlink(current.path)
			if err != nil {
				return "", 0, 0, None, 0, err
			}
			fmt.Fprint(h, target)
		case Directory:
			file, err := root.Open(current.path)
			if err != nil {
				return "", 0, 0, None, 0, err
			}
			entries, readErr := file.ReadDir(-1)
			closeErr := file.Close()
			if readErr != nil {
				return "", 0, 0, None, 0, readErr
			}
			if closeErr != nil {
				return "", 0, 0, None, 0, closeErr
			}
			sort.Slice(entries, func(i, j int) bool { return entries[i].Name() < entries[j].Name() })
			for i := len(entries) - 1; i >= 0; i-- {
				stack = append(stack, item{filepath.Join(current.path, entries[i].Name()), filepath.Join(current.name, entries[i].Name())})
			}
		}
	}
	return hex.EncodeToString(h.Sum(nil)), bytes, count, kind, info.Mode(), nil
}

func regularEntryDigest(contentDigest string, mode fs.FileMode) string {
	h := sha256.New()
	fmt.Fprintf(h, ".\x00%s\x00%o\x00%s", Regular, mode.Perm(), contentDigest)
	return hex.EncodeToString(h.Sum(nil))
}

func copyEntry(src *os.Root, srcRel string, dst *os.Root, dstRel string, allowSymlink bool) error {
	info, err := src.Lstat(srcRel)
	if err != nil {
		return err
	}
	kind := classify(info.Mode())
	if kind == None {
		return &Error{Code: UnsupportedType, Message: "unsupported filesystem object", Path: srcRel}
	}
	if kind == Symlink && !allowSymlink {
		return &Error{Code: UnsupportedSymlinkCopy, Message: "symlink copy is unsupported", Path: srcRel}
	}
	switch kind {
	case Regular:
		return copyRegular(src, srcRel, dst, dstRel, info.Mode())
	case Symlink:
		target, err := src.Readlink(srcRel)
		if err != nil {
			return err
		}
		return dst.Symlink(target, dstRel)
	case Directory:
	}
	if err = dst.Mkdir(dstRel, 0o700); err != nil {
		return err
	}
	type pair struct {
		src, dst string
		mode     fs.FileMode
	}
	stack := []pair{{srcRel, dstRel, info.Mode()}}
	var dirs []pair
	for len(stack) > 0 {
		current := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		dirs = append(dirs, current)
		file, err := src.Open(current.src)
		if err != nil {
			return err
		}
		entries, readErr := file.ReadDir(-1)
		closeErr := file.Close()
		if readErr != nil {
			return readErr
		}
		if closeErr != nil {
			return closeErr
		}
		sort.Slice(entries, func(i, j int) bool { return entries[i].Name() < entries[j].Name() })
		for _, entry := range entries {
			srel, drel := filepath.Join(current.src, entry.Name()), filepath.Join(current.dst, entry.Name())
			child, err := src.Lstat(srel)
			if err != nil {
				return err
			}
			switch classify(child.Mode()) {
			case Regular:
				if err = copyRegular(src, srel, dst, drel, child.Mode()); err != nil {
					return err
				}
			case Directory:
				if err = dst.Mkdir(drel, 0o700); err != nil {
					return err
				}
				stack = append(stack, pair{srel, drel, child.Mode()})
			case Symlink:
				if !allowSymlink {
					return &Error{Code: UnsupportedSymlinkCopy, Message: "tree contains symlink", Path: srel}
				}
				target, err := src.Readlink(srel)
				if err != nil {
					return err
				}
				if err = dst.Symlink(target, drel); err != nil {
					return err
				}
			default:
				return &Error{Code: UnsupportedType, Message: "tree contains unsupported object", Path: srel}
			}
		}
	}
	for i := len(dirs) - 1; i >= 0; i-- {
		if err = dst.Chmod(dirs[i].dst, dirs[i].mode.Perm()); err != nil {
			return err
		}
	}
	return nil
}

func copyRegular(src *os.Root, srcRel string, dst *os.Root, dstRel string, mode fs.FileMode) error {
	source, err := src.Open(srcRel)
	if err != nil {
		return err
	}
	defer source.Close()
	target, err := dst.OpenFile(dstRel, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	_, _, copyErr := streamutil.CopyHash(target, source)
	if copyErr == nil {
		copyErr = target.Sync()
	}
	if copyErr == nil {
		copyErr = target.Chmod(mode.Perm())
	}
	closeErr := target.Close()
	if copyErr != nil {
		return copyErr
	}
	return closeErr
}

func validateNoSymlinkParents(root *os.Root, rel string) error {
	parent := filepath.Dir(filepath.Clean(rel))
	if parent == "." {
		return nil
	}
	parts := strings.Split(parent, string(filepath.Separator))
	current := ""
	for _, part := range parts {
		if part == "" || part == "." {
			continue
		}
		current = filepath.Join(current, part)
		info, err := root.Lstat(current)
		if err != nil {
			return err
		}
		if info.Mode()&fs.ModeSymlink != 0 {
			return &Error{Code: Conflict, Message: "mutation parent is a symlink", Path: current}
		}
		if !info.IsDir() {
			return &Error{Code: Conflict, Message: "mutation parent is not a directory", Path: current}
		}
	}
	return nil
}

func syncDirectory(path string) error {
	dir, err := os.Open(path)
	if err != nil {
		return err
	}
	defer dir.Close()
	return dir.Sync()
}
