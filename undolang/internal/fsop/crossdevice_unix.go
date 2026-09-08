//go:build unix

package fsop

import (
	"errors"
	"syscall"
)

func isCrossDevice(err error) bool { return errors.Is(err, syscall.EXDEV) }
