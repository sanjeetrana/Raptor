package streamutil

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
)

const BufferSize = 64 * 1024

var ErrEmptyNeedle = errors.New("empty search needle")

func Contains(r io.Reader, needle []byte) (bool, error) {
	if len(needle) == 0 {
		return false, ErrEmptyNeedle
	}
	prefix := make([]int, len(needle))
	for i, j := 1, 0; i < len(needle); i++ {
		for j > 0 && needle[i] != needle[j] {
			j = prefix[j-1]
		}
		if needle[i] == needle[j] {
			j++
		}
		prefix[i] = j
	}
	buf := make([]byte, BufferSize)
	matched := 0
	for {
		n, err := r.Read(buf)
		for _, b := range buf[:n] {
			for matched > 0 && b != needle[matched] {
				matched = prefix[matched-1]
			}
			if b == needle[matched] {
				matched++
				if matched == len(needle) {
					return true, nil
				}
			}
		}
		if err != nil {
			if errors.Is(err, io.EOF) {
				return false, nil
			}
			return false, err
		}
		if n == 0 {
			return false, io.ErrNoProgress
		}
	}
}

func SHA256(r io.Reader) (string, int64, error) {
	h := sha256.New()
	n, err := io.CopyBuffer(h, r, make([]byte, BufferSize))
	if err != nil {
		return "", n, err
	}
	return hex.EncodeToString(h.Sum(nil)), n, nil
}

func CopyHash(dst io.Writer, src io.Reader) (string, int64, error) {
	h := sha256.New()
	n, err := io.CopyBuffer(io.MultiWriter(dst, h), src, make([]byte, BufferSize))
	if err != nil {
		return "", n, err
	}
	return hex.EncodeToString(h.Sum(nil)), n, nil
}

func ReplaceAll(dst io.Writer, src io.Reader, old, replacement []byte) (int64, int64, error) {
	if len(old) == 0 {
		return 0, 0, ErrEmptyNeedle
	}
	chunk := make([]byte, BufferSize)
	carry := make([]byte, 0, len(old)-1)
	var matches, written int64
	for {
		n, readErr := src.Read(chunk)
		data := make([]byte, 0, len(carry)+n)
		data = append(data, carry...)
		data = append(data, chunk[:n]...)
		for {
			index := bytes.Index(data, old)
			if index < 0 {
				break
			}
			count, err := writeParts(dst, data[:index], replacement)
			written += count
			if err != nil {
				return matches, written, err
			}
			matches++
			data = data[index+len(old):]
		}
		if errors.Is(readErr, io.EOF) {
			count, err := writeParts(dst, data)
			written += count
			return matches, written, err
		}
		if readErr != nil {
			return matches, written, readErr
		}
		keep := len(old) - 1
		if keep > len(data) {
			keep = len(data)
		}
		flush := len(data) - keep
		count, err := writeParts(dst, data[:flush])
		written += count
		if err != nil {
			return matches, written, err
		}
		carry = append(carry[:0], data[flush:]...)
		if n == 0 {
			return matches, written, io.ErrNoProgress
		}
	}
}

func writeParts(dst io.Writer, parts ...[]byte) (int64, error) {
	var total int64
	for _, part := range parts {
		for len(part) > 0 {
			n, err := dst.Write(part)
			total += int64(n)
			if err != nil {
				return total, err
			}
			if n == 0 {
				return total, io.ErrShortWrite
			}
			part = part[n:]
		}
	}
	return total, nil
}
