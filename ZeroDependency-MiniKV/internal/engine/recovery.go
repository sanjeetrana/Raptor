package engine

import (
	"log/slog"
	"os"
)

// RecoveryReport summarizes what happened while replaying the log on open.
// It is surfaced through Database.Stats() / the CLI so a human can see that
// recovery ran and what, if anything, it had to discard.
type RecoveryReport struct {
	RecordsReplayed int
	TombstonesSeen  int
	TruncatedBytes  int64 // bytes discarded because they were incomplete/corrupt
	CorruptionFound bool
}

// recoverIndex sequentially scans the log file from the beginning,
// validating and replaying every well-formed record it finds. It stops at
// the first record that is either incomplete (a torn write, as would be
// left by a crash mid-append) or fails header/checksum validation
// (corruption). Everything up to that point is trusted; everything from
// that point on is treated as garbage and reported back so the caller can
// truncate it away.
//
// This is deliberately conservative: MiniKV never tries to "skip over" a
// bad record and resume scanning later, because once the length fields of
// one record are wrong there is no reliable way to know where the next
// record begins. Stopping at the first problem is what keeps recovery
// correct rather than merely optimistic.
func recoverIndex(f *os.File, logger *slog.Logger) (idx index, validSize int64, report RecoveryReport, err error) {
	info, err := f.Stat()
	if err != nil {
		return nil, 0, report, err
	}
	total := info.Size()
	idx = make(index)

	var pos int64
	for pos < total {
		remaining := total - pos
		if remaining < headerSize {
			// Not even a full header left: a torn/incomplete write.
			report.TruncatedBytes = remaining
			break
		}

		header := make([]byte, headerSize)
		if _, rerr := f.ReadAt(header, pos); rerr != nil {
			report.CorruptionFound = true
			report.TruncatedBytes = remaining
			break
		}

		op, keyLen, valLen, herr := decodeHeader(header)
		if herr != nil {
			report.CorruptionFound = true
			report.TruncatedBytes = remaining
			if logger != nil {
				logger.Warn("minikv: stopping recovery at invalid header",
					"offset", pos, "error", herr)
			}
			break
		}

		recordTotal := int64(headerSize) + int64(keyLen) + int64(valLen) + int64(checksumSize)
		if recordTotal > remaining {
			// The header looked valid but the record was cut off mid-write.
			report.TruncatedBytes = remaining
			break
		}

		full := make([]byte, recordTotal)
		if _, rerr := f.ReadAt(full, pos); rerr != nil {
			report.CorruptionFound = true
			report.TruncatedBytes = remaining
			break
		}

		rec, derr := decodeFull(full)
		if derr != nil {
			report.CorruptionFound = true
			report.TruncatedBytes = remaining
			if logger != nil {
				logger.Warn("minikv: stopping recovery at checksum failure",
					"offset", pos, "error", derr)
			}
			break
		}

		switch op {
		case opSet:
			idx[string(rec.Key)] = indexEntry{
				offset:    pos,
				keyLen:    keyLen,
				valueLen:  valLen,
				expiresAt: rec.ExpiresAt,
			}
		case opDelete:
			delete(idx, string(rec.Key))
			report.TombstonesSeen++
		}

		report.RecordsReplayed++
		pos += recordTotal
	}

	validSize = pos
	return idx, validSize, report, nil
}
