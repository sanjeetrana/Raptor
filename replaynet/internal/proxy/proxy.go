package proxy

import (
	"bytes"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"sync"
	"time"

	"replaynet/internal/session"
)

const maxBodyBytes = 50 * 1024 * 1024

type RecordingProxy struct {
	upstream  *url.URL
	sessionW  *session.Writer
	startTime time.Time
	nextIndex int
	client    *http.Client
	mu        sync.Mutex
	onEvent   func(session.Event)
}

func New(upstream string, sessionPath string, onEvent func(session.Event)) (*RecordingProxy, error) {
	u, err := url.Parse(upstream)
	if err != nil {
		return nil, err
	}

	w, err := session.NewWriter(sessionPath)
	if err != nil {
		return nil, err
	}

	return &RecordingProxy{
		upstream:  u,
		sessionW:  w,
		startTime: time.Now(),
		client:    &http.Client{Timeout: 30 * time.Second},
		onEvent:   onEvent,
	}, nil
}

func (p *RecordingProxy) Close() error {
	return p.sessionW.Close()
}

func (p *RecordingProxy) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	reqBody, err := io.ReadAll(io.LimitReader(r.Body, maxBodyBytes+1))
	r.Body.Close()
	if err != nil {
		http.Error(w, "failed to read request body", http.StatusInternalServerError)
		return
	}
	if len(reqBody) > maxBodyBytes {
		http.Error(w, "request body too large", http.StatusRequestEntityTooLarge)
		return
	}

	reqEvent := session.Event{
		Type:    session.EventRequest,
		Method:  r.Method,
		Path:    r.URL.Path,
		Headers: r.Header.Clone(),
		Body:    reqBody,
	}
	p.recordAndPush(&reqEvent)

	outURL := *p.upstream
	outURL.Path = r.URL.Path
	outURL.RawQuery = r.URL.RawQuery

	outReq, err := http.NewRequest(r.Method, outURL.String(), bytes.NewReader(reqBody))
	if err != nil {
		http.Error(w, "failed to build upstream request", http.StatusInternalServerError)
		return
	}
	outReq.Header = r.Header.Clone()

	resp, err := p.client.Do(outReq)
	if err != nil {
		respEvent := session.Event{
			Type:       session.EventResponse,
			StatusCode: 0,
			Headers:    http.Header{},
			Body:       []byte(fmt.Sprintf("upstream error: %v", err)),
		}
		p.recordAndPush(&respEvent)
		http.Error(w, "upstream unreachable", http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(io.LimitReader(resp.Body, maxBodyBytes+1))
	if err != nil {
		http.Error(w, "failed to read upstream response", http.StatusInternalServerError)
		return
	}

	respEvent := session.Event{
		Type:       session.EventResponse,
		StatusCode: resp.StatusCode,
		Headers:    resp.Header.Clone(),
		Body:       respBody,
	}
	p.recordAndPush(&respEvent)

	for k, vs := range resp.Header {
		for _, v := range vs {
			w.Header().Add(k, v)
		}
	}
	w.WriteHeader(resp.StatusCode)
	w.Write(respBody)
}

func (p *RecordingProxy) recordAndPush(e *session.Event) {
	p.mu.Lock()
	e.Index = p.nextIndex
	p.nextIndex++
	e.Offset = time.Since(p.startTime)
	err := p.sessionW.Append(*e)
	p.mu.Unlock()

	if err != nil {
		return
	}

	if p.onEvent != nil {
		p.onEvent(*e)
	}
}
