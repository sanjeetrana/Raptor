//go:build windows

package fsop

import (
	"errors"
	"syscall"
)

func isCrossDevice(err error) bool {
	var errno syscall.Errno
	return errors.As(err, &errno) && errno == 17 // ERROR_NOT_SAME_DEVICE
}
