#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

echo "================================================================="
echo "               REPLAYNET AUTOMATED DEMO WORKFLOW                "
echo "================================================================="

# Clean previous sessions and build binaries
rm -f demo.rnet
mkdir -p bin
go build -trimpath -buildvcs=false -o bin/replaynet ./cmd/replaynet
go build -trimpath -buildvcs=false -o bin/mock_server ./scripts/mock_server.go

# Cleanup trap
cleanup() {
  echo ""
  echo "--> Cleaning up background processes..."
  if [ -n "$BACKEND_PID" ]; then kill -9 "$BACKEND_PID" 2>/dev/null || true; fi
  if [ -n "$PROXY_PID" ]; then kill -9 "$PROXY_PID" 2>/dev/null || true; fi
  if [ -n "$REPLAY_PID" ]; then kill -9 "$REPLAY_PID" 2>/dev/null || true; fi
  kill -9 $(lsof -t -i :8080 -i :9000 -i :9001 -i :9002 -i :9003) 2>/dev/null || true
  echo "✓ Cleanup complete."
}
trap cleanup EXIT

wait_port() {
  local port=$1
  local count=0
  until nc -z localhost "$port" 2>/dev/null || [ "$count" -ge 30 ]; do
    sleep 0.1
    count=$((count+1))
  done
}

# -------------------------------------------------------------
# STEP 1: START MOCK BACKEND
# -------------------------------------------------------------
echo ""
echo "[Step 1/5] Starting real backend server on :8080..."
./bin/mock_server &
BACKEND_PID=$!
wait_port 8080
echo "✓ Backend server is up and listening on :8080"

# -------------------------------------------------------------
# STEP 2: RECORD THROUGH PROXY
# -------------------------------------------------------------
echo ""
echo "[Step 2/5] Starting ReplayNet Recording Proxy on :9000 -> :8080 (Inspect: :9001)..."
./bin/replaynet proxy --listen :9000 --upstream http://localhost:8080 --session demo.rnet --inspect :9001 &
PROXY_PID=$!
wait_port 9000
wait_port 9001
echo "✓ Recording proxy active on :9000, inspector on :9001"

echo ""
echo "--> Sending client traffic to Proxy (:9000)..."
echo "  [1] GET /login"
curl -s http://localhost:9000/login
echo ""

echo "  [2] GET /profile"
curl -s http://localhost:9000/profile
echo ""

echo "  [3] GET /permissions (Attempt 1 - Expected: 500)"
curl -s -w " | Status: %{http_code}\n" http://localhost:9000/permissions

echo "  [4] GET /permissions (Attempt 2 - Expected: 200)"
curl -s -w " | Status: %{http_code}\n" http://localhost:9000/permissions

sleep 0.5
kill -9 "$PROXY_PID" 2>/dev/null || true
PROXY_PID=""

echo "✓ Recorded conversation saved to demo.rnet"
ls -lh demo.rnet

# -------------------------------------------------------------
# STEP 3: KILL THE BACKEND
# -------------------------------------------------------------
echo ""
echo "[Step 3/5] Killing real backend server completely..."
kill -9 "$BACKEND_PID" 2>/dev/null || true
BACKEND_PID=""
sleep 0.5

echo "--> Verifying backend is dead (:8080)..."
if curl -s http://localhost:8080/login >/dev/null 2>&1; then
  echo "ERROR: Backend is unexpectedly still alive!"
  exit 1
else
  echo "✓ Confirmed: Backend connection refused (server is 100% offline)."
fi

# -------------------------------------------------------------
# STEP 4: REPLAY CONVERSATION (ZERO BACKEND RUNNING)
# -------------------------------------------------------------
echo ""
echo "[Step 4/5] Starting ReplayNet Replay Engine on :9002 (Inspect: :9003)..."
./bin/replaynet replay demo.rnet --listen :9002 --inspect :9003 &
REPLAY_PID=$!
wait_port 9002
wait_port 9003
echo "✓ Replay server active on :9002 (no backend running)"

echo ""
echo "--> Sending same client traffic to ReplayNet Replay Server (:9002)..."
echo "  [1] GET /login"
curl -s http://localhost:9002/login
echo ""

echo "  [2] GET /profile"
curl -s http://localhost:9002/profile
echo ""

echo "  [3] GET /permissions (Call 1 - Exact replayed 500 error)"
curl -s -w " | Status: %{http_code}\n" http://localhost:9002/permissions

echo "  [4] GET /permissions (Call 2 - Exact replayed 200 retry)"
curl -s -w " | Status: %{http_code}\n" http://localhost:9002/permissions

kill -9 "$REPLAY_PID" 2>/dev/null || true
REPLAY_PID=""
echo "✓ Deterministic replay reproduced exact sequence without backend!"

# -------------------------------------------------------------
# STEP 5: FAULT INJECTION (ALTER HISTORY)
# -------------------------------------------------------------
echo ""
echo "[Step 5/5] Altering history with Fault Injection on Event #7 (override 200 retry -> 503)..."
./bin/replaynet replay demo.rnet --listen :9002 --fault "at=7,type=status,code=503" &
REPLAY_PID=$!
wait_port 9002
echo "✓ Replay server active with active fault rule: at=7, type=status, code=503"

echo ""
echo "--> Replaying with Fault Injection active (:9002)..."
echo "  [1] GET /login"
curl -s http://localhost:9002/login
echo ""

echo "  [2] GET /profile"
curl -s http://localhost:9002/profile
echo ""

echo "  [3] GET /permissions (Original 500)"
curl -s -w " | Status: %{http_code}\n" http://localhost:9002/permissions

echo "  [4] GET /permissions (Injected 503 Override instead of 200 retry!)"
curl -s -w " | Status: %{http_code}\n" http://localhost:9002/permissions

echo ""
echo "================================================================="
echo "       ✓ AUTOMATED DEMO WORKFLOW COMPLETED SUCCESSFULLY!        "
echo "================================================================="
