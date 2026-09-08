package tests

import (
	"bytes"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"

	"replaynet/internal/proxy"
	"replaynet/internal/session"
)

func TestProxyLargePayload(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(r.Body)
		if err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/octet-stream")
		w.WriteHeader(http.StatusOK)
		w.Write(body)
	}))
	defer upstream.Close()

	dir := t.TempDir()
	sessionPath := dir + "/large.rnet"

	p, err := proxy.New(upstream.URL, sessionPath, nil)
	if err != nil {
		t.Fatalf("new proxy: %v", err)
	}
	defer p.Close()

	proxySrv := httptest.NewServer(p)
	defer proxySrv.Close()

	largePayload := bytes.Repeat([]byte("A"), 5*1024*1024)
	resp, err := http.Post(proxySrv.URL+"/upload", "application/octet-stream", bytes.NewReader(largePayload))
	if err != nil {
		t.Fatalf("post: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("read response: %v", err)
	}
	if !bytes.Equal(respBody, largePayload) {
		t.Errorf("echo payload mismatch: len got %d want %d", len(respBody), len(largePayload))
	}

	p.Close()

	sess, err := session.Load(sessionPath)
	if err != nil {
		t.Fatalf("load session: %v", err)
	}

	if len(sess.Events) != 2 {
		t.Fatalf("expected 2 events, got %d", len(sess.Events))
	}
	if !bytes.Equal(sess.Events[0].Body, largePayload) {
		t.Errorf("recorded request body mismatch")
	}
	if !bytes.Equal(sess.Events[1].Body, largePayload) {
		t.Errorf("recorded response body mismatch")
	}
}

func TestProxyBodyLimitExceeded(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer upstream.Close()

	dir := t.TempDir()
	sessionPath := dir + "/toolarge.rnet"

	p, err := proxy.New(upstream.URL, sessionPath, nil)
	if err != nil {
		t.Fatalf("new proxy: %v", err)
	}
	defer p.Close()

	proxySrv := httptest.NewServer(p)
	defer proxySrv.Close()

	overLimitPayload := bytes.Repeat([]byte("B"), 50*1024*1024+10)
	resp, err := http.Post(proxySrv.URL+"/large", "text/plain", bytes.NewReader(overLimitPayload))
	if err != nil {
		t.Fatalf("post: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusRequestEntityTooLarge {
		t.Errorf("expected 413, got %d", resp.StatusCode)
	}
}

func TestProxyUpstreamUnreachable(t *testing.T) {
	dir := t.TempDir()
	sessionPath := dir + "/unreachable.rnet"

	p, err := proxy.New("http://127.0.0.1:59999", sessionPath, nil)
	if err != nil {
		t.Fatalf("new proxy: %v", err)
	}
	defer p.Close()

	proxySrv := httptest.NewServer(p)
	defer proxySrv.Close()

	resp, err := http.Get(proxySrv.URL + "/down")
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusBadGateway {
		t.Errorf("expected 502 Bad Gateway, got %d", resp.StatusCode)
	}

	p.Close()

	sess, err := session.Load(sessionPath)
	if err != nil {
		t.Fatalf("load session: %v", err)
	}

	if len(sess.Events) != 2 {
		t.Fatalf("expected 2 recorded events, got %d", len(sess.Events))
	}
	if sess.Events[1].StatusCode != 0 {
		t.Errorf("expected synthetic event status 0, got %d", sess.Events[1].StatusCode)
	}
}
