package report

type Error struct {
	Code          string `json:"code"`
	Message       string `json:"message"`
	Path          string `json:"path,omitempty"`
	Root          string `json:"root,omitempty"`
	Line          int    `json:"line,omitzero"`
	Column        int    `json:"column,omitzero"`
	TransactionID string `json:"transaction_id,omitempty"`
	Recovery      string `json:"recovery,omitempty"`
}

type Envelope struct {
	APIVersion string `json:"api_version"`
	OK         bool   `json:"ok"`
	Result     any    `json:"result,omitempty"`
	Error      *Error `json:"error,omitempty"`
}

type CheckResult struct {
	ScriptPath   string   `json:"script_path"`
	Transactions []string `json:"transactions"`
}
