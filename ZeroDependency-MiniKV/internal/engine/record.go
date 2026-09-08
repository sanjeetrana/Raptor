package engine

import (
	"encoding/binary"
	"errors"
	"hash/crc32"
)

// ---------------------------------------------------------------------------
// MiniKV on-disk record format
//
// Every mutation appended to the log is encoded as a single self-describing
// record. The layout is intentionally simple and fixed-width in its header
// so that a reader can validate a record before trusting any of its bytes.
//
//   Offset  Size  Field
//   ------  ----  -----------------------------------------------------
//   0       4     Magic        ("MKV1", ASCII)
//   4       1     Version      (format version, currently 1)
//   5       1     Operation    (1 = SET, 2 = DELETE)
//   6       4     KeyLen       (uint32, big-endian)
//   10      4     ValueLen     (uint32, big-endian; 0 for DELETE)
//   14      8     ExpiresAt    (int64, big-endian, unix seconds; 0 = never)
//   22      N     Key          (KeyLen bytes)
//   22+N    M     Value        (ValueLen bytes)
//   22+N+M  4     Checksum     (uint32, big-endian, CRC-32C/IEEE of
//                               everything from offset 0 up to, but not
//                               including, the checksum field)
//
// The checksum covers the header, key and value so that any single-bit flip
// anywhere in the record is detected. Records are never rewritten in place;
// updates and deletes are new records appended to the tail of the log, and
// the in-memory index always points at the most recent one for a given key.
// ---------------------------------------------------------------------------

const (
	recordMagic   uint32 = 0x4D4B5631 // "MKV1"
	recordVersion byte   = 1

	opSet    byte = 1
	opDelete byte = 2

	headerSize   = 22 // magic(4)+version(1)+op(1)+keylen(4)+vallen(4)+expires(8)
	checksumSize = 4

	// MaxKeyLen / MaxValueLen guard against corrupted length fields being
	// interpreted as multi-gigabyte allocations during recovery.
	maxKeyLen   = 1 << 20 // 1 MiB
	maxValueLen = 1 << 28 // 256 MiB
)

var (
	errBadMagic       = errors.New("minikv: bad record magic")
	errBadVersion     = errors.New("minikv: unsupported record version")
	errBadOperation   = errors.New("minikv: unknown record operation")
	errChecksumFail   = errors.New("minikv: checksum mismatch")
	errRecordTooLarge = errors.New("minikv: record length exceeds limit")
	errShortRecord    = errors.New("minikv: incomplete record")
)

// record is the decoded, in-memory representation of a single log entry.
type record struct {
	Op        byte
	Key       []byte
	Value     []byte
	ExpiresAt int64 // unix seconds, 0 = no expiry
}

// encode serializes r into the on-disk record format described above,
// including the trailing checksum.
func (r *record) encode() []byte {
	total := headerSize + len(r.Key) + len(r.Value) + checksumSize
	buf := make([]byte, total)

	binary.BigEndian.PutUint32(buf[0:4], recordMagic)
	buf[4] = recordVersion
	buf[5] = r.Op
	binary.BigEndian.PutUint32(buf[6:10], uint32(len(r.Key)))
	binary.BigEndian.PutUint32(buf[10:14], uint32(len(r.Value)))
	binary.BigEndian.PutUint64(buf[14:22], uint64(r.ExpiresAt))

	copy(buf[headerSize:headerSize+len(r.Key)], r.Key)
	copy(buf[headerSize+len(r.Key):headerSize+len(r.Key)+len(r.Value)], r.Value)

	body := buf[:total-checksumSize]
	sum := crc32.ChecksumIEEE(body)
	binary.BigEndian.PutUint32(buf[total-checksumSize:], sum)

	return buf
}

// decodeHeader parses just the fixed header from buf (which must be at
// least headerSize bytes) and returns the operation, key length and value
// length so the caller knows exactly how many more bytes to read.
func decodeHeader(buf []byte) (op byte, keyLen, valLen uint32, err error) {
	if len(buf) < headerSize {
		return 0, 0, 0, errShortRecord
	}
	magic := binary.BigEndian.Uint32(buf[0:4])
	if magic != recordMagic {
		return 0, 0, 0, errBadMagic
	}
	version := buf[4]
	if version != recordVersion {
		return 0, 0, 0, errBadVersion
	}
	op = buf[5]
	if op != opSet && op != opDelete {
		return 0, 0, 0, errBadOperation
	}
	keyLen = binary.BigEndian.Uint32(buf[6:10])
	valLen = binary.BigEndian.Uint32(buf[10:14])
	if keyLen > maxKeyLen || valLen > maxValueLen {
		return 0, 0, 0, errRecordTooLarge
	}
	return op, keyLen, valLen, nil
}

// decodeFull parses a complete record (header + key + value + checksum)
// from buf and verifies its checksum. buf must be exactly the record's
// total length.
func decodeFull(buf []byte) (*record, error) {
	if len(buf) < headerSize+checksumSize {
		return nil, errShortRecord
	}
	op, keyLen, valLen, err := decodeHeader(buf)
	if err != nil {
		return nil, err
	}
	expected := headerSize + int(keyLen) + int(valLen) + checksumSize
	if len(buf) != expected {
		return nil, errShortRecord
	}

	expiresAt := int64(binary.BigEndian.Uint64(buf[14:22]))
	key := buf[headerSize : headerSize+int(keyLen)]
	value := buf[headerSize+int(keyLen) : headerSize+int(keyLen)+int(valLen)]

	body := buf[:expected-checksumSize]
	wantSum := binary.BigEndian.Uint32(buf[expected-checksumSize : expected])
	gotSum := crc32.ChecksumIEEE(body)
	if wantSum != gotSum {
		return nil, errChecksumFail
	}

	// Copy key/value out of the shared read buffer so the record owns its
	// own memory (the caller's buffer may be reused).
	keyCopy := make([]byte, len(key))
	copy(keyCopy, key)
	valCopy := make([]byte, len(value))
	copy(valCopy, value)

	return &record{Op: op, Key: keyCopy, Value: valCopy, ExpiresAt: expiresAt}, nil
}
