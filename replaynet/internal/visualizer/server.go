package visualizer

import (
	"embed"
	"encoding/json"
	"fmt"
	"io/fs"
	"net/http"
	"sync"

	"replaynet/internal/session"
)

//go:embed static/*
var staticFiles embed.FS

type eventMsg struct {
	Index      int                 `json:"index"`
	OffsetMs   int64               `json:"offsetMs"`
	Type       string              `json:"type"`
	Method     string              `json:"method,omitempty"`
	Path       string              `json:"path,omitempty"`
	StatusCode int                 `json:"status,omitempty"`
	Headers    map[string][]string `json:"headers,omitempty"`
	Body       string              `json:"body,omitempty"`
	BodySize   int                 `json:"bodySize,omitempty"`
}

type Server struct {
	mu          sync.Mutex
	subscribers map[chan eventMsg]bool
}

func New() *Server {
	return &Server{
		subscribers: map[chan eventMsg]bool{},
	}
}

func (s *Server) Broadcast(e session.Event) {
	typ := "request"
	if e.Type == session.EventResponse {
		typ = "response"
	}

	var bodyStr string
	if len(e.Body) > 0 {
		if len(e.Body) <= 32*1024 {
			bodyStr = string(e.Body)
		} else {
			bodyStr = string(e.Body[:32*1024]) + " ... [truncated]"
		}
	}

	msg := eventMsg{
		Index:      e.Index,
		OffsetMs:   e.Offset.Milliseconds(),
		Type:       typ,
		Method:     e.Method,
		Path:       e.Path,
		StatusCode: e.StatusCode,
		Headers:    e.Headers,
		Body:       bodyStr,
		BodySize:   len(e.Body),
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	for ch := range s.subscribers {
		select {
		case ch <- msg:
		default:
		}
	}
}

func (s *Server) HandleEvents(w http.ResponseWriter, r *http.Request) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming unsupported", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	flusher.Flush()

	ch := make(chan eventMsg, 64)

	s.mu.Lock()
	s.subscribers[ch] = true
	s.mu.Unlock()

	defer func() {
		s.mu.Lock()
		delete(s.subscribers, ch)
		s.mu.Unlock()
		close(ch)
	}()

	for {
		select {
		case msg := <-ch:
			data, err := json.Marshal(msg)
			if err != nil {
				continue
			}
			fmt.Fprintf(w, "data: %s\n\n", data)
			flusher.Flush()
		case <-r.Context().Done():
			return
		}
	}
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/events", s.HandleEvents)

	sub, err := fs.Sub(staticFiles, "static")
	if err == nil {
		mux.Handle("/", http.FileServer(http.FS(sub)))
	}

	return mux
}
