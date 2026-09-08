//go:build !unix && !windows

package fsop

func isCrossDevice(error) bool { return false }
