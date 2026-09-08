package main

import (
	"fmt"
	"net/http"
	"sync"
)

func main() {
	var mu sync.Mutex
	permCount := 0

	http.HandleFunc("/login", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"token": "demo_jwt_9921", "user": "charlie"}`))
	})

	http.HandleFunc("/profile", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"name": "Charlie Engineer", "role": "sre", "status": "active"}`))
	})

	http.HandleFunc("/permissions", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		permCount++
		current := permCount
		mu.Unlock()

		w.Header().Set("Content-Type", "application/json")
		if current == 1 {
			w.WriteHeader(http.StatusInternalServerError)
			w.Write([]byte(`{"error": "database connection pool exhausted"}`))
			return
		}
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"permissions": ["admin", "deploy", "audit"], "retried": true}`))
	})

	fmt.Println("Backend server listening on :8080")
	http.ListenAndServe(":8080", nil)
}
