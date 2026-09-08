package token

type Position struct {
	Offset int `json:"offset"`
	Line   int `json:"line"`
	Column int `json:"column"`
}

type Span struct {
	Start Position `json:"start"`
	End   Position `json:"end"`
}

type Kind uint8

const (
	Illegal Kind = iota
	EOF
	Identifier
	String
	LBrace
	RBrace
	Arrow
	Equal
	Transaction
	Require
	Assert
	Mkdir
	Copy
	Move
	Write
	Replace
	Delete
	Overwrite
	Exists
	NotExists
	IsFile
	IsDir
	Contains
	SHA256
)

var keywords = map[string]Kind{
	"transaction": Transaction,
	"require":     Require,
	"assert":      Assert,
	"mkdir":       Mkdir,
	"copy":        Copy,
	"move":        Move,
	"write":       Write,
	"replace":     Replace,
	"delete":      Delete,
	"overwrite":   Overwrite,
	"exists":      Exists,
	"not_exists":  NotExists,
	"is_file":     IsFile,
	"is_dir":      IsDir,
	"contains":    Contains,
	"sha256":      SHA256,
}

func Keyword(s string) Kind { return keywords[s] }

type Token struct {
	Kind   Kind
	Lexeme string
	Value  string
	Span   Span
}

func (k Kind) String() string {
	names := [...]string{"illegal", "EOF", "identifier", "string", "{", "}", "->", "=", "transaction", "require", "assert", "mkdir", "copy", "move", "write", "replace", "delete", "overwrite", "exists", "not_exists", "is_file", "is_dir", "contains", "sha256"}
	if int(k) < len(names) {
		return names[k]
	}
	return "unknown"
}
