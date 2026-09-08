package journal

import (
	"bytes"
	"encoding/binary"
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func journalBytes(t *testing.T, records ...struct {
	kind    Type
	payload Payload
}) []byte {
	t.Helper()
	path := filepath.Join(t.TempDir(), "journal.bin")
	appender, err := Create(path)
	if err != nil {
		t.Fatal(err)
	}
	for _, record := range records {
		if _, err := appender.Append(record.kind, record.payload); err != nil {
			t.Fatal(err)
		}
	}
	if err := appender.Close(); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func basicRecords() []struct {
	kind    Type
	payload Payload
} {
	return []struct {
		kind    Type
		payload Payload
	}{
		{TXBegin, Payload{TransactionID: "tx", State: "PLANNED"}},
		{TXState, Payload{TransactionID: "tx", State: "PREPARED"}},
		{TXState, Payload{TransactionID: "tx", State: "RUNNING"}},
		{OPPrepared, Payload{TransactionID: "tx", OperationID: "1"}},
		{OPApplied, Payload{TransactionID: "tx", OperationID: "1"}},
	}
}

func frameOffset(data []byte, index int) int {
	offset := 0
	for range index {
		length := int(binary.BigEndian.Uint32(data[offset+16 : offset+20]))
		offset += headerSize + length + 4
	}
	return offset
}

func TestRoundTripAndOpenAppend(t *testing.T) {
	path := filepath.Join(t.TempDir(), "journal.bin")
	appender, err := Create(path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = appender.Append(TXBegin, Payload{TransactionID: "tx", State: "PLANNED"}); err != nil {
		t.Fatal(err)
	}
	if err = appender.Close(); err != nil {
		t.Fatal(err)
	}
	appender, err = OpenAppend(path)
	if err != nil {
		t.Fatal(err)
	}
	record, err := appender.Append(TXState, Payload{TransactionID: "tx", State: "PREPARED"})
	if err != nil {
		t.Fatal(err)
	}
	if record.Sequence != 2 {
		t.Fatalf("sequence=%d", record.Sequence)
	}
	appender.Close()
	file, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	replay, err := Decode(file)
	if err != nil {
		t.Fatal(err)
	}
	if len(replay.Records) != 2 || replay.TransactionID != "tx" || replay.TornTail {
		t.Fatalf("replay=%#v", replay)
	}
}

func TestCorruptionAndTornTailPolicy(t *testing.T) {
	valid := journalBytes(t, basicRecords()...)
	tests := []struct {
		name   string
		mutate func([]byte) []byte
		torn   bool
	}{
		{"zero", func([]byte) []byte { return nil }, false},
		{"torn first", func([]byte) []byte { return append([]byte(nil), valid[:3]...) }, false},
		{"torn tail header", func(b []byte) []byte { return append(append([]byte(nil), b...), 1, 2, 3) }, true},
		{"torn final payload", func(b []byte) []byte { return append([]byte(nil), b[:len(b)-2]...) }, true},
		{"bad magic", func(b []byte) []byte { b = append([]byte(nil), b...); b[0] = 'X'; return b }, false},
		{"bad version", func(b []byte) []byte { b = append([]byte(nil), b...); binary.BigEndian.PutUint16(b[4:6], 99); return b }, false},
		{"bad type", func(b []byte) []byte { b = append([]byte(nil), b...); binary.BigEndian.PutUint16(b[6:8], 99); return b }, false},
		{"bad checksum", func(b []byte) []byte { b = append([]byte(nil), b...); b[len(b)-1] ^= 0xff; return b }, false},
		{"sequence gap", func(b []byte) []byte {
			b = append([]byte(nil), b...)
			off := frameOffset(b, 1)
			binary.BigEndian.PutUint64(b[off+8:off+16], 9)
			return b
		}, false},
		{"giant payload", func(b []byte) []byte {
			b = append([]byte(nil), b...)
			binary.BigEndian.PutUint32(b[16:20], MaxPayload+1)
			return b
		}, false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			replay, err := Decode(bytes.NewReader(tt.mutate(valid)))
			if tt.torn {
				if err != nil || !replay.TornTail {
					t.Fatalf("replay=%#v err=%v", replay, err)
				}
				return
			}
			if !errors.Is(err, ErrCorrupt) {
				t.Fatalf("error=%v", err)
			}
		})
	}
}

func TestSemanticReplayValidation(t *testing.T) {
	tests := [][]struct {
		kind    Type
		payload Payload
	}{
		{{TXBegin, Payload{TransactionID: "tx"}}, {OPApplied, Payload{TransactionID: "tx", OperationID: "1"}}},
		{{TXBegin, Payload{TransactionID: "tx"}}, {OPPrepared, Payload{TransactionID: "other", OperationID: "1"}}},
		{{TXBegin, Payload{TransactionID: "tx"}}, {RollbackPrepared, Payload{TransactionID: "tx", OperationID: "1"}}},
	}
	for _, records := range tests {
		data := journalBytes(t, records...)
		if _, err := Decode(bytes.NewReader(data)); !errors.Is(err, ErrCorrupt) {
			t.Fatalf("error=%v", err)
		}
	}
}

func TestSemanticReplayRejectsUnappliedOperationAtVerificationAndCommit(t *testing.T) {
	records := []struct {
		kind    Type
		payload Payload
	}{
		{TXBegin, Payload{TransactionID: "tx", State: "PLANNED"}},
		{TXState, Payload{TransactionID: "tx", State: "PREPARED"}},
		{TXState, Payload{TransactionID: "tx", State: "RUNNING"}},
		{OPPrepared, Payload{TransactionID: "tx", OperationID: "1"}},
		{TXState, Payload{TransactionID: "tx", State: "VERIFYING"}},
	}
	if _, err := Decode(bytes.NewReader(journalBytes(t, records...))); !errors.Is(err, ErrCorrupt) {
		t.Fatalf("error=%v", err)
	}
}

func TestSemanticReplayRejectsIncompleteRollbackMarker(t *testing.T) {
	records := []struct {
		kind    Type
		payload Payload
	}{
		{TXBegin, Payload{TransactionID: "tx", State: "PLANNED"}},
		{TXState, Payload{TransactionID: "tx", State: "PREPARED"}},
		{TXState, Payload{TransactionID: "tx", State: "RUNNING"}},
		{OPPrepared, Payload{TransactionID: "tx", OperationID: "1"}},
		{TXState, Payload{TransactionID: "tx", State: "ROLLING_BACK"}},
		{TXRollbackComplete, Payload{TransactionID: "tx"}},
	}
	if _, err := Decode(bytes.NewReader(journalBytes(t, records...))); !errors.Is(err, ErrCorrupt) {
		t.Fatalf("error=%v", err)
	}
}

func FuzzDecodeNeverPanics(f *testing.F) {
	f.Add([]byte{})
	f.Add([]byte("UNDO"))
	f.Fuzz(func(t *testing.T, data []byte) { _, _ = Decode(bytes.NewReader(data)) })
}
