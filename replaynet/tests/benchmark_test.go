package tests

import (
	"bufio"
	"bytes"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"replaynet/internal/proxy"
	"replaynet/internal/replay"
	"replaynet/internal/session"
)

func BenchmarkSessionWriteRead(b *testing.B) {
	ev := session.Event{
		Index:      1,
		Offset:     150 * time.Millisecond,
		Type:       session.EventRequest,
		Method:     "POST",
		Path:       "/api/v1/orders",
		StatusCode: 200,
		Headers: http.Header{
			"Content-Type":  []string{"application/json"},
			"Authorization": []string{"Bearer token-12345"},
		},
		Body: []byte(`{"order_id": 98765, "item": "widget", "qty": 42, "amount": 199.99}`),
	}

	b.ReportAllocs()
	b.ResetTimer()

	for i := 0; i < b.N; i++ {
		var buf bytes.Buffer
		if err := session.WriteEvent(&buf, ev); err != nil {
			b.Fatal(err)
		}
		reader := bytes.NewReader(buf.Bytes())
		bufReader := bufio.NewReader(reader)
		_, err := session.ReadEvent(bufReader)
		if err != nil {
			b.Fatal(err)
		}
	}
}

func BenchmarkProxyThroughput(b *testing.B) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"status":"ok"}`))
	}))
	defer upstream.Close()

	sessionPath := b.TempDir() + "/bench_proxy.rnet"
	p, err := proxy.New(upstream.URL, sessionPath, nil)
	if err != nil {
		b.Fatal(err)
	}
	defer p.Close()

	ts := httptest.NewServer(p)
	defer ts.Close()

	client := ts.Client()

	b.ReportAllocs()
	b.ResetTimer()

	for i := 0; i < b.N; i++ {
		resp, err := client.Get(ts.URL + "/bench")
		if err != nil {
			b.Fatal(err)
		}
		io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
	}
}

func BenchmarkReplayThroughput(b *testing.B) {
	sess := &session.Session{
		ID:        "bench-session",
		StartTime: time.Now(),
		Events: []session.Event{
			{
				Index:  0,
				Offset: 0,
				Type:   session.EventRequest,
				Method: "GET",
				Path:   "/bench",
			},
			{
				Index:      1,
				Offset:     10 * time.Millisecond,
				Type:       session.EventResponse,
				StatusCode: 200,
				Headers:    http.Header{"Content-Type": []string{"application/json"}},
				Body:       []byte(`{"replayed":true}`),
			},
		},
	}

	srv := replay.New(sess, nil, nil)
	ts := httptest.NewServer(srv)
	defer ts.Close()

	client := ts.Client()

	b.ReportAllocs()
	b.ResetTimer()

	for i := 0; i < b.N; i++ {
		resp, err := client.Get(ts.URL + "/bench")
		if err != nil {
			b.Fatal(err)
		}
		io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
	}
}
