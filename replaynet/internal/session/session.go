package session

import (
	"bufio"
	"io"
	"os"
	"time"
)

type Session struct {
	ID        string
	StartTime time.Time
	Events    []Event
}

type Writer struct {
	f   *os.File
	buf *bufio.Writer
}

func NewWriter(path string) (*Writer, error) {
	f, err := os.Create(path)
	if err != nil {
		return nil, err
	}
	return &Writer{f: f, buf: bufio.NewWriter(f)}, nil
}

func (w *Writer) Append(e Event) error {
	if err := WriteEvent(w.buf, e); err != nil {
		return err
	}
	return w.buf.Flush()
}

func (w *Writer) Close() error {
	if err := w.buf.Flush(); err != nil {
		w.f.Close()
		return err
	}
	return w.f.Close()
}

func Load(path string) (*Session, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	r := bufio.NewReader(f)
	sess := &Session{}

	idx := 0
	for {
		e, err := ReadEvent(r)
		if err == ErrCleanEOF {
			break
		}
		if (err == io.ErrUnexpectedEOF || err == io.EOF) && len(sess.Events) > 0 {
			break
		}
		if err != nil {
			return nil, err
		}
		e.Index = idx
		idx++
		sess.Events = append(sess.Events, e)
	}

	return sess, nil
}
