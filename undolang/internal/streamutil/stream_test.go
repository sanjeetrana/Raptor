package streamutil

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"testing"
)

func TestContainsAcrossBufferBoundary(t *testing.T) {
	data := append(bytes.Repeat([]byte{'a'}, BufferSize-2), []byte("needle")...)
	found, err := Contains(bytes.NewReader(data), []byte("needle"))
	if err != nil || !found {
		t.Fatalf("found=%v err=%v", found, err)
	}
	found, err = Contains(bytes.NewReader(data), []byte("absent"))
	if err != nil || found {
		t.Fatalf("found=%v err=%v", found, err)
	}
}

func TestSHA256(t *testing.T) {
	data := bytes.Repeat([]byte("0123456789"), 10000)
	want := sha256.Sum256(data)
	got, n, err := SHA256(bytes.NewReader(data))
	if err != nil || n != int64(len(data)) || got != hex.EncodeToString(want[:]) {
		t.Fatalf("digest=%s n=%d err=%v", got, n, err)
	}
}

func TestReplaceAllBoundariesAndOverlap(t *testing.T) {
	tests := []struct {
		name, input, old, replacement, want string
		count                               int64
	}{
		{"overlap", "aaa", "aa", "b", "ba", 1},
		{"grow", "x-x-x", "x", "long", "long-long-long", 3},
		{"shrink", "abcabc", "abc", "z", "zz", 2},
		{"absent", "abc", "z", "q", "abc", 0},
		{"same", "abcabc", "abc", "abc", "abcabc", 2},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var output bytes.Buffer
			count, written, err := ReplaceAll(&output, bytes.NewBufferString(tt.input), []byte(tt.old), []byte(tt.replacement))
			if err != nil || count != tt.count || output.String() != tt.want || written != int64(len(tt.want)) {
				t.Fatalf("output=%q count=%d written=%d err=%v", output.String(), count, written, err)
			}
		})
	}
	input := append(bytes.Repeat([]byte{'a'}, BufferSize-2), []byte("needle-tail")...)
	var output bytes.Buffer
	count, _, err := ReplaceAll(&output, bytes.NewReader(input), []byte("needle"), []byte("found"))
	if err != nil || count != 1 || !bytes.Contains(output.Bytes(), []byte("found-tail")) {
		t.Fatalf("boundary replacement failed: count=%d err=%v", count, err)
	}
}
