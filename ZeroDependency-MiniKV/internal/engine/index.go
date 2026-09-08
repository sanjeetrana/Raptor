package engine

// indexEntry describes where the *current* version of a key's record lives
// on disk. The index only ever holds one entry per live key; deletes remove
// the entry entirely rather than marking it in place, so a simple map
// lookup answers both "does this key exist" and "where is its value".
type indexEntry struct {
	offset    int64 // byte offset of the record's header in the log file
	keyLen    uint32
	valueLen  uint32
	expiresAt int64 // unix seconds, 0 = never
}

// valueOffset returns the byte offset at which the value payload begins.
func (e indexEntry) valueOffset() int64 {
	return e.offset + int64(headerSize) + int64(e.keyLen)
}

// index is a plain map, not a separate type with its own lock: it is always
// accessed while the owning Database holds db.mu, so a dedicated lock here
// would be redundant and would invite lock-ordering bugs.
type index map[string]indexEntry
