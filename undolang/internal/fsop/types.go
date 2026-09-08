package fsop

import (
	"fmt"
	"io/fs"

	"github.com/daniel-oluwadunsin/undolang/internal/lang/ast"
	"github.com/daniel-oluwadunsin/undolang/internal/pathcap"
)

const (
	UnsupportedType        = "E_UNSUPPORTED_FILE_TYPE"
	UnsupportedSymlinkCopy = "E_UNSUPPORTED_SYMLINK_COPY"
	DestinationExists      = "E_DESTINATION_EXISTS"
	SourceMissing          = "E_SOURCE_MISSING"
	Conflict               = "E_CONFLICT"
	ReplacePatternNotFound = "E_REPLACE_PATTERN_NOT_FOUND"
	VerificationFailed     = "E_HASH_MISMATCH"
)

type Error struct {
	Code, Message string
	Path          string
	Cause         error
}

func (e *Error) Error() string { return fmt.Sprintf("%s: %s: %s", e.Code, e.Message, e.Path) }
func (e *Error) Unwrap() error { return e.Cause }

type EntryType string

const (
	None      EntryType = "none"
	Regular   EntryType = "regular"
	Directory EntryType = "directory"
	Symlink   EntryType = "symlink"
)

type Backup struct {
	Present  bool        `json:"present"`
	Relative string      `json:"relative,omitempty"`
	Type     EntryType   `json:"type,omitempty"`
	Mode     fs.FileMode `json:"mode,omitempty"`
	Digest   string      `json:"digest,omitempty"`
	Bytes    int64       `json:"bytes,omitempty"`
	Entries  int64       `json:"entries,omitempty"`
}

type Prepared struct {
	OperationID    string                 `json:"operation_id"`
	OperationHash  string                 `json:"operation_hash"`
	Kind           ast.StatementKind      `json:"kind"`
	Source         *pathcap.ResolvedPath  `json:"source,omitempty"`
	Target         pathcap.ResolvedPath   `json:"target"`
	Created        []pathcap.ResolvedPath `json:"created,omitempty"`
	PriorTarget    Backup                 `json:"prior_target"`
	SourceBackup   Backup                 `json:"source_backup"`
	SourceDigest   string                 `json:"source_digest,omitempty"`
	SourceType     EntryType              `json:"source_type,omitempty"`
	Method         string                 `json:"method,omitempty"`
	ExpectedDigest string                 `json:"expected_digest,omitempty"`
	MatchCount     int64                  `json:"match_count,omitempty"`
	Temporary      string                 `json:"temporary,omitempty"`
}

type Disposition string

const (
	Before    Disposition = "before"
	After     Disposition = "after"
	Ambiguous Disposition = "ambiguous"
)
