package session

import (
	"encoding/binary"
	"errors"
)

type bufWriter struct {
	buf []byte
}

func (b *bufWriter) putByte(v byte) {
	b.buf = append(b.buf, v)
}

func (b *bufWriter) putInt32(v int32) {
	tmp := make([]byte, 4)
	binary.BigEndian.PutUint32(tmp, uint32(v))
	b.buf = append(b.buf, tmp...)
}

func (b *bufWriter) putInt64(v int64) {
	tmp := make([]byte, 8)
	binary.BigEndian.PutUint64(tmp, uint64(v))
	b.buf = append(b.buf, tmp...)
}

func (b *bufWriter) putString(s string) {
	tmp := make([]byte, 2)
	binary.BigEndian.PutUint16(tmp, uint16(len(s)))
	b.buf = append(b.buf, tmp...)
	b.buf = append(b.buf, s...)
}

func (b *bufWriter) putBytes(v []byte) {
	tmp := make([]byte, 4)
	binary.BigEndian.PutUint32(tmp, uint32(len(v)))
	b.buf = append(b.buf, tmp...)
	b.buf = append(b.buf, v...)
}

func (b *bufWriter) putRaw(v []byte) {
	b.buf = append(b.buf, v...)
}

func (b *bufWriter) bytes() []byte {
	return b.buf
}

type bufReader struct {
	data []byte
	pos  int
	err  error
}

var errShortBuffer = errors.New("session: short buffer")

func (r *bufReader) remaining() int {
	return len(r.data) - r.pos
}

func (r *bufReader) need(n int) bool {
	if r.err != nil {
		return false
	}
	if r.remaining() < n {
		r.err = errShortBuffer
		return false
	}
	return true
}

func (r *bufReader) getByte() byte {
	if !r.need(1) {
		return 0
	}
	v := r.data[r.pos]
	r.pos++
	return v
}

func (r *bufReader) getInt32() int32 {
	if !r.need(4) {
		return 0
	}
	v := binary.BigEndian.Uint32(r.data[r.pos : r.pos+4])
	r.pos += 4
	return int32(v)
}

func (r *bufReader) getInt64() int64 {
	if !r.need(8) {
		return 0
	}
	v := binary.BigEndian.Uint64(r.data[r.pos : r.pos+8])
	r.pos += 8
	return int64(v)
}

func (r *bufReader) getString() string {
	if !r.need(2) {
		return ""
	}
	n := int(binary.BigEndian.Uint16(r.data[r.pos : r.pos+2]))
	r.pos += 2
	if !r.need(n) {
		return ""
	}
	s := string(r.data[r.pos : r.pos+n])
	r.pos += n
	return s
}

func (r *bufReader) getBytes() []byte {
	if !r.need(4) {
		return nil
	}
	n := int(binary.BigEndian.Uint32(r.data[r.pos : r.pos+4]))
	r.pos += 4
	if !r.need(n) {
		return nil
	}
	v := r.data[r.pos : r.pos+n]
	r.pos += n
	return v
}

func (r *bufReader) getRaw(n int) []byte {
	if !r.need(n) {
		return nil
	}
	v := r.data[r.pos : r.pos+n]
	r.pos += n
	return v
}
