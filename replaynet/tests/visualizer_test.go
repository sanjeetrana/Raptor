package tests

import (
	"bufio"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"replaynet/internal/session"
	"replaynet/internal/visualizer"
)

func TestVisualizerStaticFiles(t *testing.T) {
	srv := visualizer.New()
	ts := httptest.NewServer(srv.Handler())
	defer ts.Close()

	paths := []string{"/", "/app.js", "/style.css"}
	for _, p := range paths {
		resp, err := http.Get(ts.URL + p)
		if err != nil {
			t.Fatalf("get %s: %v", p, err)
		}
		if resp.StatusCode != http.StatusOK {
			t.Errorf("path %s returned status %d", p, resp.StatusCode)
		}
		resp.Body.Close()
	}
}

func TestVisualizerSSEBroadcast(t *testing.T) {
	srv := visualizer.New()
	ts := httptest.NewServer(srv.Handler())
	defer ts.Close()

	resp, err := http.Get(ts.URL + "/events")
	if err != nil {
		t.Fatalf("sse connect: %v", err)
	}
	defer resp.Body.Close()

	if ct := resp.Header.Get("Content-Type"); !strings.HasPrefix(ct, "text/event-stream") {
		t.Fatalf("unexpected content type: %s", ct)
	}

	time.Sleep(50 * time.Millisecond)

	ev := session.Event{
		Index:      1,
		Offset:     120 * time.Millisecond,
		Type:       session.EventRequest,
		Method:     "GET",
		Path:       "/api/health",
		StatusCode: 0,
	}
	srv.Broadcast(ev)

	reader := bufio.NewReader(resp.Body)
	lineChan := make(chan string, 1)
	go func() {
		for {
			line, err := reader.ReadString('\n')
			if err != nil {
				return
			}
			if strings.HasPrefix(line, "data: ") {
				lineChan <- strings.TrimPrefix(line, "data: ")
				return
			}
		}
	}()

	select {
	case data := <-lineChan:
		var msg map[string]interface{}
		if err := json.Unmarshal([]byte(data), &msg); err != nil {
			t.Fatalf("unmarshal json: %v", err)
		}
		if msg["type"] != "request" {
			t.Errorf("type mismatch: got %v", msg["type"])
		}
		if msg["method"] != "GET" {
			t.Errorf("method mismatch: got %v", msg["method"])
		}
		if msg["path"] != "/api/health" {
			t.Errorf("path mismatch: got %v", msg["path"])
		}
		if int(msg["index"].(float64)) != 1 {
			t.Errorf("index mismatch: got %v", msg["index"])
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for SSE message")
	}
}

func TestVisualizerDropOnFullBuffer(t *testing.T) {
	srv := visualizer.New()
	ts := httptest.NewServer(srv.Handler())
	defer ts.Close()

	resp, err := http.Get(ts.URL + "/events")
	if err != nil {
		t.Fatalf("sse connect: %v", err)
	}
	defer resp.Body.Close()

	time.Sleep(50 * time.Millisecond)

	done := make(chan struct{})
	go func() {
		for i := 0; i < 200; i++ {
			srv.Broadcast(session.Event{
				Index:      i,
				Offset:     time.Duration(i) * time.Millisecond,
				Type:       session.EventRequest,
				Method:     "GET",
				Path:       "/ping",
				StatusCode: 0,
			})
		}
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(500 * time.Millisecond):
		t.Fatal("Broadcast blocked on full subscriber channel")
	}
}

func TestVisualizerConcurrentSubscribers(t *testing.T) {
	srv := visualizer.New()
	ts := httptest.NewServer(srv.Handler())
	defer ts.Close()

	var wg sync.WaitGroup
	for i := 0; i < 5; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			resp, err := http.Get(ts.URL + "/events")
			if err != nil {
				return
			}
			defer resp.Body.Close()
			reader := bufio.NewReader(resp.Body)
			_, _ = reader.ReadString('\n')
		}()
	}

	time.Sleep(50 * time.Millisecond)
	srv.Broadcast(session.Event{
		Index:      0,
		Offset:     10 * time.Millisecond,
		Type:       session.EventResponse,
		StatusCode: 200,
	})

	srv.Broadcast(session.Event{
		Index:      1,
		Offset:     20 * time.Millisecond,
		Type:       session.EventResponse,
		StatusCode: 500,
	})
}
