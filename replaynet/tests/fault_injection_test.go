package tests

import (
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"replaynet/internal/replay"
	"replaynet/internal/session"
)

func TestFaultStatusOverride(t *testing.T) {
	sess := &session.Session{
		Events: []session.Event{
			{Index: 0, Type: session.EventRequest, Method: "GET", Path: "/api/user"},
			{Index: 1, Type: session.EventResponse, StatusCode: 200, Body: []byte(`{"user":"bob"}`)},
		},
	}

	faults := []replay.FaultRule{
		{
			AtEventIndex:   1,
			Type:           replay.FaultStatus,
			StatusOverride: http.StatusServiceUnavailable,
		},
	}

	srv := httptest.NewServer(replay.New(sess, faults, nil))
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/api/user")
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusServiceUnavailable {
		t.Errorf("status mismatch: got %d want %d", resp.StatusCode, http.StatusServiceUnavailable)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("read body: %v", err)
	}
	if string(body) != `{"user":"bob"}` {
		t.Errorf("body mismatch: got %q", body)
	}
}

func TestFaultLatencyInjection(t *testing.T) {
	sess := &session.Session{
		Events: []session.Event{
			{Index: 0, Type: session.EventRequest, Method: "GET", Path: "/slow"},
			{Index: 1, Type: session.EventResponse, StatusCode: 200, Body: []byte("ok")},
		},
	}

	faults := []replay.FaultRule{
		{
			AtEventIndex: 1,
			Type:         replay.FaultLatency,
			LatencyMs:    150,
		},
	}

	srv := httptest.NewServer(replay.New(sess, faults, nil))
	defer srv.Close()

	start := time.Now()
	resp, err := http.Get(srv.URL + "/slow")
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	elapsed := time.Since(start)
	resp.Body.Close()

	if elapsed < 130*time.Millisecond {
		t.Errorf("latency too short: %v", elapsed)
	}
	if resp.StatusCode != http.StatusOK {
		t.Errorf("status mismatch: got %d want 200", resp.StatusCode)
	}
}

func TestFaultDropConnectionHijack(t *testing.T) {
	sess := &session.Session{
		Events: []session.Event{
			{Index: 0, Type: session.EventRequest, Method: "GET", Path: "/drop"},
			{Index: 1, Type: session.EventResponse, StatusCode: 200, Body: []byte("won't be received")},
		},
	}

	faults := []replay.FaultRule{
		{
			AtEventIndex: 1,
			Type:         replay.FaultDrop,
		},
	}

	srv := httptest.NewServer(replay.New(sess, faults, nil))
	defer srv.Close()

	client := &http.Client{Timeout: 2 * time.Second}
	resp, err := client.Get(srv.URL + "/drop")
	if err == nil {
		defer resp.Body.Close()
		_, readErr := io.ReadAll(resp.Body)
		if readErr == nil && resp.StatusCode == http.StatusOK {
			t.Errorf("expected drop error or connection reset, got status %d", resp.StatusCode)
		}
	}
}

func TestFaultTargetingSpecificIndex(t *testing.T) {
	sess := &session.Session{
		Events: []session.Event{
			{Index: 0, Type: session.EventRequest, Method: "GET", Path: "/step"},
			{Index: 1, Type: session.EventResponse, StatusCode: 200, Body: []byte("first")},
			{Index: 2, Type: session.EventRequest, Method: "GET", Path: "/step"},
			{Index: 3, Type: session.EventResponse, StatusCode: 200, Body: []byte("second")},
		},
	}

	faults := []replay.FaultRule{
		{
			AtEventIndex:   3,
			Type:           replay.FaultStatus,
			StatusOverride: http.StatusInternalServerError,
		},
	}

	srv := httptest.NewServer(replay.New(sess, faults, nil))
	defer srv.Close()

	resp1, err := http.Get(srv.URL + "/step")
	if err != nil {
		t.Fatalf("first get: %v", err)
	}
	body1, _ := io.ReadAll(resp1.Body)
	resp1.Body.Close()

	if resp1.StatusCode != http.StatusOK || string(body1) != "first" {
		t.Errorf("step 1 unexpected: %d %s", resp1.StatusCode, body1)
	}

	resp2, err := http.Get(srv.URL + "/step")
	if err != nil {
		t.Fatalf("second get: %v", err)
	}
	body2, _ := io.ReadAll(resp2.Body)
	resp2.Body.Close()

	if resp2.StatusCode != http.StatusInternalServerError || string(body2) != "second" {
		t.Errorf("step 2 unexpected: %d %s", resp2.StatusCode, body2)
	}
}
