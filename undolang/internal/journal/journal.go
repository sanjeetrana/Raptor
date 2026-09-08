package journal

import (
	"encoding/binary"
	json "encoding/json/v2"
	"errors"
	"fmt"
	"hash/crc32"
	"io"
	"os"
)

const (
	Version    uint16 = 1
	MaxPayload        = 1 << 20
	headerSize        = 20
)

var (
	magic      = [4]byte{'U', 'N', 'D', 'O'}
	castagnoli = crc32.MakeTable(crc32.Castagnoli)
	ErrCorrupt = errors.New("E_JOURNAL_CORRUPT")
)

type Type uint16

const (
	TXBegin Type = iota + 1
	TXState
	OPPrepared
	OPApplied
	AssertResult
	RollbackPrepared
	RollbackApplied
	TXCommit
	TXRollbackComplete
)

func validType(t Type) bool { return t >= TXBegin && t <= TXRollbackComplete }

type Payload struct {
	TransactionID string `json:"transaction_id"`
	OperationID   string `json:"operation_id,omitempty"`
	State         string `json:"state,omitempty"`
	Data          any    `json:"data,omitempty"`
}

type Record struct {
	Type     Type
	Sequence uint64
	Payload  []byte
}

type Appender struct {
	file *os.File
	next uint64
}

func Create(path string) (*Appender, error) {
	file, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return nil, err
	}
	return &Appender{file: file, next: 1}, nil
}

func OpenAppend(path string) (*Appender, error) {
	file, err := os.OpenFile(path, os.O_RDWR|os.O_APPEND, 0o600)
	if err != nil {
		return nil, err
	}
	if _, err = file.Seek(0, io.SeekStart); err != nil {
		file.Close()
		return nil, err
	}
	replay, err := Decode(file)
	if err != nil {
		file.Close()
		return nil, err
	}
	if replay.TornTail {
		file.Close()
		return nil, fmt.Errorf("%w: journal has torn tail", ErrCorrupt)
	}
	return &Appender{file: file, next: uint64(len(replay.Records) + 1)}, nil
}

func (a *Appender) Append(kind Type, payload Payload) (Record, error) {
	if a == nil || a.file == nil {
		return Record{}, errors.New("journal is closed")
	}
	if !validType(kind) {
		return Record{}, fmt.Errorf("%w: unknown record type %d", ErrCorrupt, kind)
	}
	data, err := json.Marshal(&payload)
	if err != nil {
		return Record{}, err
	}
	if len(data) > MaxPayload {
		return Record{}, fmt.Errorf("%w: payload exceeds %d bytes", ErrCorrupt, MaxPayload)
	}
	header := make([]byte, headerSize)
	copy(header[:4], magic[:])
	binary.BigEndian.PutUint16(header[4:6], Version)
	binary.BigEndian.PutUint16(header[6:8], uint16(kind))
	binary.BigEndian.PutUint64(header[8:16], a.next)
	binary.BigEndian.PutUint32(header[16:20], uint32(len(data)))
	checksum := crc32.New(castagnoli)
	_, _ = checksum.Write(header[4:])
	_, _ = checksum.Write(data)
	crc := make([]byte, 4)
	binary.BigEndian.PutUint32(crc, checksum.Sum32())
	if err = writeFull(a.file, header); err == nil {
		err = writeFull(a.file, data)
	}
	if err == nil {
		err = writeFull(a.file, crc)
	}
	if err == nil {
		err = a.file.Sync()
	}
	if err != nil {
		return Record{}, err
	}
	record := Record{Type: kind, Sequence: a.next, Payload: data}
	a.next++
	return record, nil
}
func writeFull(w io.Writer, p []byte) error {
	for len(p) > 0 {
		n, err := w.Write(p)
		if err != nil {
			return err
		}
		if n == 0 {
			return io.ErrShortWrite
		}
		p = p[n:]
	}
	return nil
}
func (a *Appender) Close() error {
	if a == nil || a.file == nil {
		return nil
	}
	err := a.file.Close()
	a.file = nil
	return err
}

type Replay struct {
	Records       []Record
	TornTail      bool
	TransactionID string
	ValidBytes    int64
	State         string
	Committed     bool
	RolledBack    bool
}

func Decode(r io.Reader) (Replay, error) {
	var result Replay
	expected := uint64(1)
	prepared := map[string]bool{}
	applied := map[string]bool{}
	rollbackPrepared := map[string]bool{}
	rollbackApplied := map[string]bool{}
	state := ""
	for {
		header := make([]byte, headerSize)
		n, err := io.ReadFull(r, header)
		if errors.Is(err, io.EOF) && n == 0 {
			if len(result.Records) == 0 {
				return Replay{}, fmt.Errorf("%w: zero-byte journal", ErrCorrupt)
			}
			return result, nil
		}
		if errors.Is(err, io.ErrUnexpectedEOF) || errors.Is(err, io.EOF) {
			if len(result.Records) == 0 {
				return Replay{}, fmt.Errorf("%w: torn first frame", ErrCorrupt)
			}
			result.TornTail = true
			return result, nil
		}
		if err != nil {
			return Replay{}, err
		}
		if string(header[:4]) != string(magic[:]) {
			return Replay{}, fmt.Errorf("%w: bad magic", ErrCorrupt)
		}
		if binary.BigEndian.Uint16(header[4:6]) != Version {
			return Replay{}, fmt.Errorf("%w: unsupported version", ErrCorrupt)
		}
		kind := Type(binary.BigEndian.Uint16(header[6:8]))
		if !validType(kind) {
			return Replay{}, fmt.Errorf("%w: unknown record type", ErrCorrupt)
		}
		sequence := binary.BigEndian.Uint64(header[8:16])
		if sequence != expected {
			return Replay{}, fmt.Errorf("%w: sequence %d, expected %d", ErrCorrupt, sequence, expected)
		}
		length := binary.BigEndian.Uint32(header[16:20])
		if length > MaxPayload {
			return Replay{}, fmt.Errorf("%w: payload length exceeds cap", ErrCorrupt)
		}
		body := make([]byte, int(length)+4)
		n, err = io.ReadFull(r, body)
		if errors.Is(err, io.ErrUnexpectedEOF) || errors.Is(err, io.EOF) {
			if len(result.Records) == 0 {
				return Replay{}, fmt.Errorf("%w: torn first payload", ErrCorrupt)
			}
			result.TornTail = true
			return result, nil
		}
		if err != nil {
			return Replay{}, err
		}
		if n != len(body) {
			return Replay{}, io.ErrUnexpectedEOF
		}
		checksum := crc32.New(castagnoli)
		_, _ = checksum.Write(header[4:])
		_, _ = checksum.Write(body[:length])
		if binary.BigEndian.Uint32(body[length:]) != checksum.Sum32() {
			return Replay{}, fmt.Errorf("%w: checksum mismatch", ErrCorrupt)
		}
		var payload Payload
		if err = json.Unmarshal(body[:length], &payload); err != nil {
			return Replay{}, fmt.Errorf("%w: invalid payload: %v", ErrCorrupt, err)
		}
		if expected == 1 && kind != TXBegin {
			return Replay{}, fmt.Errorf("%w: first record is not TX_BEGIN", ErrCorrupt)
		}
		if result.TransactionID == "" {
			result.TransactionID = payload.TransactionID
		} else if payload.TransactionID != result.TransactionID {
			return Replay{}, fmt.Errorf("%w: transaction id mismatch", ErrCorrupt)
		}
		if err = validateReference(kind, payload.OperationID, prepared, applied, rollbackPrepared, rollbackApplied); err != nil {
			return Replay{}, err
		}
		if err = validateSemantics(kind, payload, &state, prepared, applied, rollbackApplied, &result); err != nil {
			return Replay{}, err
		}
		result.Records = append(result.Records, Record{Type: kind, Sequence: sequence, Payload: append([]byte(nil), body[:length]...)})
		result.ValidBytes += int64(headerSize + len(body))
		result.State = state
		expected++
	}
}

func validateReference(kind Type, id string, prepared, applied, rollbackPrepared, rollbackApplied map[string]bool) error {
	switch kind {
	case OPPrepared:
		if id == "" || prepared[id] || len(prepared) != len(applied) {
			return fmt.Errorf("%w: invalid or duplicate prepared operation", ErrCorrupt)
		}
		prepared[id] = true
	case OPApplied:
		if !prepared[id] || applied[id] {
			return fmt.Errorf("%w: applied operation lacks preparation", ErrCorrupt)
		}
		applied[id] = true
	case RollbackPrepared:
		if !prepared[id] || rollbackPrepared[id] {
			return fmt.Errorf("%w: rollback lacks prepared operation", ErrCorrupt)
		}
		rollbackPrepared[id] = true
	case RollbackApplied:
		if !rollbackPrepared[id] || rollbackApplied[id] {
			return fmt.Errorf("%w: rollback applied lacks preparation", ErrCorrupt)
		}
		rollbackApplied[id] = true
	}
	return nil
}

func validateSemantics(kind Type, payload Payload, state *string, prepared, applied, rollbackApplied map[string]bool, result *Replay) error {
	if result.Committed || result.RolledBack {
		if kind != TXState {
			return fmt.Errorf("%w: record follows terminal marker", ErrCorrupt)
		}
	}
	switch kind {
	case TXBegin:
		if *state != "" || payload.State != "PLANNED" || payload.TransactionID == "" {
			return fmt.Errorf("%w: invalid transaction begin state", ErrCorrupt)
		}
		*state = payload.State
	case TXState:
		if payload.State == "VERIFYING" && len(prepared) != len(applied) {
			return fmt.Errorf("%w: verification begins with an unapplied operation", ErrCorrupt)
		}
		if !validTransition(*state, payload.State) {
			return fmt.Errorf("%w: invalid state transition %s -> %s", ErrCorrupt, *state, payload.State)
		}
		if result.Committed && payload.State != "COMMITTED" {
			return fmt.Errorf("%w: commit marker not followed by COMMITTED", ErrCorrupt)
		}
		if result.RolledBack && payload.State != "ROLLED_BACK" {
			return fmt.Errorf("%w: rollback marker not followed by ROLLED_BACK", ErrCorrupt)
		}
		*state = payload.State
	case OPPrepared, OPApplied:
		if *state != "RUNNING" {
			return fmt.Errorf("%w: operation record outside RUNNING", ErrCorrupt)
		}
	case AssertResult:
		if *state != "VERIFYING" {
			return fmt.Errorf("%w: assertion record outside VERIFYING", ErrCorrupt)
		}
	case RollbackPrepared, RollbackApplied:
		if *state != "ROLLING_BACK" {
			return fmt.Errorf("%w: rollback record outside ROLLING_BACK", ErrCorrupt)
		}
	case TXCommit:
		if *state != "COMMITTING" || result.Committed || len(prepared) != len(applied) {
			return fmt.Errorf("%w: invalid commit marker", ErrCorrupt)
		}
		result.Committed = true
	case TXRollbackComplete:
		if *state != "ROLLING_BACK" || result.RolledBack || len(prepared) != len(rollbackApplied) {
			return fmt.Errorf("%w: invalid rollback completion", ErrCorrupt)
		}
		result.RolledBack = true
	}
	return nil
}

func validTransition(from, to string) bool {
	allowed := map[string]map[string]bool{
		"PLANNED":           {"PREPARED": true, "ROLLING_BACK": true, "RECOVERY_REQUIRED": true},
		"PREPARED":          {"RUNNING": true, "ROLLING_BACK": true, "RECOVERY_REQUIRED": true},
		"RUNNING":           {"VERIFYING": true, "ROLLING_BACK": true, "RECOVERY_REQUIRED": true},
		"VERIFYING":         {"COMMITTING": true, "ROLLING_BACK": true, "RECOVERY_REQUIRED": true},
		"COMMITTING":        {"COMMITTED": true, "ROLLING_BACK": true, "RECOVERY_REQUIRED": true},
		"ROLLING_BACK":      {"ROLLED_BACK": true, "RECOVERY_FAILED": true},
		"RECOVERY_REQUIRED": {"ROLLING_BACK": true, "RECOVERY_FAILED": true},
		"RECOVERY_FAILED":   {"ROLLING_BACK": true},
	}
	return allowed[from][to]
}

// OpenAppendRecovery validates a journal and, only for an incomplete final
// frame, truncates it to the last verified byte before reopening for append.
func OpenAppendRecovery(path string) (*Appender, Replay, error) {
	file, err := os.OpenFile(path, os.O_RDWR, 0o600)
	if err != nil {
		return nil, Replay{}, err
	}
	replay, err := Decode(file)
	if err != nil {
		file.Close()
		return nil, Replay{}, err
	}
	if replay.TornTail {
		if err = file.Truncate(replay.ValidBytes); err == nil {
			err = file.Sync()
		}
		if err != nil {
			file.Close()
			return nil, Replay{}, err
		}
	}
	if _, err = file.Seek(0, io.SeekEnd); err != nil {
		file.Close()
		return nil, Replay{}, err
	}
	return &Appender{file: file, next: uint64(len(replay.Records) + 1)}, replay, nil
}
