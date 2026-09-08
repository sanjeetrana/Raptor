//go:build unix

package cli

import (
	"syscall"
	"testing"
)

func TestNoSpaceClassification(t *testing.T) {
	result, exit := classifyError(syscall.ENOSPC)
	if result.Code != "E_NO_SPACE" || exit != 3 {
		t.Fatalf("result=%#v exit=%d", result, exit)
	}
}
