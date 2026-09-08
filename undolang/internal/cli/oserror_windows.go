//go:build windows

package cli

import (
	"errors"
	"syscall"
)

func isNoSpace(err error) bool {
	return errors.Is(err, syscall.Errno(112)) // ERROR_DISK_FULL
}
