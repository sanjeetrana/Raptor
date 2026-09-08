package tests

import (
	"io"
	"net/http"
	"net/http/httptest"
	"testing"

	"replaynet/internal/proxy"
	"replaynet/internal/replay"
	"replaynet/internal/session"
)

func TestRecordAndReplay(t *testing.T) {
	hits := 0
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits++
		if r.URL.Path == "/permissions" && hits <= 1 {
			w.WriteHeader(500)
			w.Write([]byte("denied"))
			return
		}
		w.Header().Set("X-Hit", "yes")
		w.WriteHeader(200)
		w.Write([]byte("path=" + r.URL.Path))
	}))
	defer upstream.Close()

	dir := t.TempDir()
	sessionPath := dir + "/session.rnet"

	p, err := proxy.New(upstream.URL, sessionPath, nil)
	if err != nil {
		t.Fatalf("new proxy: %v", err)
	}

	proxySrv := httptest.NewServer(p)
	defer proxySrv.Close()

	paths := []string{"/login", "/profile", "/permissions", "/permissions"}
	var gotStatuses []int
	for _, path := range paths {
		resp, err := http.Get(proxySrv.URL + path)
		if err != nil {
			t.Fatalf("get %s: %v", path, err)
		}
		gotStatuses = append(gotStatuses, resp.StatusCode)
		resp.Body.Close()
	}
	p.Close()

	upstream.Close()

	sess, err := session.Load(sessionPath)
	if err != nil {
		t.Fatalf("load session: %v", err)
	}

	replaySrv := httptest.NewServer(replay.New(sess, nil, nil))
	defer replaySrv.Close()

	for i, path := range paths {
		resp, err := http.Get(replaySrv.URL + path)
		if err != nil {
			t.Fatalf("replay get %s: %v", path, err)
		}
		body, _ := io.ReadAll(resp.Body)
		resp.Body.Close()

		if resp.StatusCode != gotStatuses[i] {
			t.Errorf("path %s (call %d): status mismatch: got %d want %d", path, i, resp.StatusCode, gotStatuses[i])
		}

		if resp.StatusCode == 200 && string(body) != "path="+path {
			t.Errorf("path %s: body mismatch: got %q", path, body)
		}
	}

	resp, err := http.Get(replaySrv.URL + "/nonexistent")
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if resp.StatusCode != http.StatusNotFound {
		t.Errorf("expected 404 for unrecorded path, got %d", resp.StatusCode)
	}
}
