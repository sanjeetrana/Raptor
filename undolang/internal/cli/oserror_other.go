//go:build !unix && !windows

package cli

func isNoSpace(error) bool { return false }
