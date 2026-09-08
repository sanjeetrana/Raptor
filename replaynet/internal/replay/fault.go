package replay

import (
	"net/http"
	"time"

	"replaynet/internal/session"
)

type FaultType int

const (
	FaultLatency FaultType = iota
	FaultDrop
	FaultStatus
)

type FaultRule struct {
	AtEventIndex   int
	Type           FaultType
	LatencyMs      int
	StatusOverride int
}

func applyFault(w http.ResponseWriter, ev session.Event, f FaultRule) {
	switch f.Type {
	case FaultLatency:
		time.Sleep(time.Duration(f.LatencyMs) * time.Millisecond)
		writeRecordedResponse(w, ev)
	case FaultDrop:
		if hj, ok := w.(http.Hijacker); ok {
			conn, _, err := hj.Hijack()
			if err == nil {
				conn.Close()
				return
			}
		}
		w.WriteHeader(http.StatusServiceUnavailable)
	case FaultStatus:
		for k, vs := range ev.Headers {
			for _, v := range vs {
				w.Header().Add(k, v)
			}
		}
		w.WriteHeader(f.StatusOverride)
		w.Write(ev.Body)
	}
}

func writeRecordedResponse(w http.ResponseWriter, ev session.Event) {
	for k, vs := range ev.Headers {
		for _, v := range vs {
			w.Header().Add(k, v)
		}
	}
	w.WriteHeader(ev.StatusCode)
	w.Write(ev.Body)
}
