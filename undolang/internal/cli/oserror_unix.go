//go:build unix

package cli

import (
	"errors"
	"syscall"
)

func isNoSpace(err error) bool {
	return errors.Is(err, syscall.ENOSPC)
}
