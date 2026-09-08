package replay

import (
	"net/http"
	"sync"
	"time"

	"replaynet/internal/session"
)

type ReplayServer struct {
	sess      *session.Session
	index     map[string][]session.Event
	cursor    map[string]int
	faults    map[int]FaultRule
	startTime time.Time
	mu        sync.Mutex
	onEvent   func(session.Event)
}

func New(sess *session.Session, faults []FaultRule, onEvent func(session.Event)) *ReplayServer {
	r := &ReplayServer{
		sess:      sess,
		index:     map[string][]session.Event{},
		cursor:    map[string]int{},
		faults:    map[int]FaultRule{},
		startTime: time.Now(),
		onEvent:   onEvent,
	}

	for _, f := range faults {
		r.faults[f.AtEventIndex] = f
	}

	for i := 0; i < len(sess.Events)-1; i++ {
		req := sess.Events[i]
		if req.Type != session.EventRequest {
			continue
		}
		resp := sess.Events[i+1]
		if resp.Type != session.EventResponse {
			continue
		}
		key := req.Method + " " + req.Path
		r.index[key] = append(r.index[key], resp)
	}

	return r
}

func (r *ReplayServer) ServeHTTP(w http.ResponseWriter, req *http.Request) {
	key := req.Method + " " + req.URL.Path

	r.mu.Lock()
	events := r.index[key]
	idx := r.cursor[key]
	if idx >= len(events) {
		r.mu.Unlock()
		http.Error(w, "no more recorded responses for "+key, http.StatusNotFound)
		return
	}
	ev := events[idx]
	r.cursor[key] = idx + 1
	r.mu.Unlock()

	if fault, ok := r.faults[ev.Index]; ok {
		applyFault(w, ev, fault)
		r.push(ev)
		return
	}

	writeRecordedResponse(w, ev)
	r.push(ev)
}

func (r *ReplayServer) push(ev session.Event) {
	if r.onEvent != nil {
		r.onEvent(ev)
	}
}
