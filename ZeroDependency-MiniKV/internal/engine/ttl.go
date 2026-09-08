package engine

import "time"

// expiresAtFromTTL converts a duration into an absolute unix-second
// expiration timestamp. A zero or negative ttl means "no expiration",
// represented on disk and in the index as 0.
func expiresAtFromTTL(ttl time.Duration) int64 {
	if ttl <= 0 {
		return 0
	}
	return time.Now().Add(ttl).Unix()
}

// isExpired reports whether an entry with the given absolute expiration
// timestamp (0 = never expires) should be treated as gone as of now.
func isExpired(expiresAt int64, now time.Time) bool {
	if expiresAt == 0 {
		return false
	}
	return now.Unix() >= expiresAt
}
