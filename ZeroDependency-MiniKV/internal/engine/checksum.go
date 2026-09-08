package engine

// This file exists as a small, explicit seam around the checksum logic
// used elsewhere in the engine (see record.go for the actual CRC-32 code).
// Keeping it isolated makes the corruption-detection contract easy to
// point a reviewer at: every record's integrity is verified here, and
// nowhere else, so there is exactly one place to audit.

// verifyChecksum re-decodes a raw record buffer and reports whether it
// passes header validation and checksum verification, without allocating
// a full record beyond what decodeFull already needs. It is used by
// recovery and by the standalone "minikv check" style tooling paths.
func verifyChecksum(buf []byte) error {
	_, err := decodeFull(buf)
	return err
}
