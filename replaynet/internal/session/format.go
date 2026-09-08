package session

import (
	"bufio"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"io"
	"net/http"
	"time"
)

type EventType uint8

const (
	EventRequest EventType = iota
	EventResponse
)

type Event struct {
	Index      int
	Offset     time.Duration
	Type       EventType
	Method     string
	Path       string
	StatusCode int
	Headers    http.Header
	Body       []byte
	BodyHash   [32]byte
}

var ErrCleanEOF = errors.New("session: clean eof")

func WriteEvent(w io.Writer, e Event) error {
	buf := new(bufWriter)

	buf.putInt64(int64(e.Offset))
	buf.putByte(byte(e.Type))
	buf.putString(e.Method)
	buf.putString(e.Path)
	buf.putInt32(int32(e.StatusCode))

	headerBlock := encodeHeaders(e.Headers)
	buf.putBytes(headerBlock)

	hash := sha256.Sum256(e.Body)
	buf.putBytes(e.Body)
	buf.putRaw(hash[:])

	body := buf.bytes()

	lenPrefix := make([]byte, 4)
	binary.BigEndian.PutUint32(lenPrefix, uint32(len(body)))

	if _, err := w.Write(lenPrefix); err != nil {
		return err
	}
	_, err := w.Write(body)
	return err
}

func ReadEvent(r *bufio.Reader) (Event, error) {
	var lenPrefix [4]byte
	if _, err := io.ReadFull(r, lenPrefix[:]); err != nil {
		if err == io.EOF {
			return Event{}, ErrCleanEOF
		}
		return Event{}, err
	}
	recordLen := binary.BigEndian.Uint32(lenPrefix[:])

	record := make([]byte, recordLen)
	if _, err := io.ReadFull(r, record); err != nil {
		return Event{}, err
	}

	br := &bufReader{data: record}

	offsetNanos := br.getInt64()
	typ := br.getByte()
	method := br.getString()
	path := br.getString()
	status := br.getInt32()
	headerBlock := br.getBytes()
	body := br.getBytes()
	hash := br.getRaw(32)

	if br.err != nil {
		return Event{}, br.err
	}

	var hashArr [32]byte
	copy(hashArr[:], hash)

	return Event{
		Offset:     time.Duration(offsetNanos),
		Type:       EventType(typ),
		Method:     method,
		Path:       path,
		StatusCode: int(status),
		Headers:    decodeHeaders(headerBlock),
		Body:       body,
		BodyHash:   hashArr,
	}, nil
}

func encodeHeaders(h http.Header) []byte {
	buf := new(bufWriter)
	for k, vs := range h {
		for _, v := range vs {
			buf.putString(k)
			buf.putString(v)
		}
	}
	return buf.bytes()
}

func decodeHeaders(data []byte) http.Header {
	h := http.Header{}
	br := &bufReader{data: data}
	for br.remaining() > 0 && br.err == nil {
		k := br.getString()
		v := br.getString()
		if br.err != nil {
			break
		}
		h.Add(k, v)
	}
	return h
}
