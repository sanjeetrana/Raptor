#!/bin/bash
# One-command way to start the NoDepDB server.
# Usage: ./run.sh

echo "Starting NoDepDB server on 127.0.0.1:6380 ..."
python3 nodepdb/server.py
