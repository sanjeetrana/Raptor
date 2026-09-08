"""
Write-Ahead Log (WAL) Manager
=============================
Append-only log manager ensuring write durability before in-memory state mutations
and recovery replay support.

Format:
JSON Lines (jsonl), where each line contains a single serialized JSON object
representing a state-mutating operation.

Supported Operations:
- SET:    {"op": "SET", "key": str, "value": Any, "ttl": Optional[float], "ts": float}
- DELETE: {"op": "DELETE", "key": str, "ts": float}
- EXPIRE: {"op": "EXPIRE", "key": str, "ttl": float, "ts": float}
- FLUSH:  {"op": "FLUSH", "ts": float}
"""

from __future__ import annotations

import json
import os
import pathlib
import threading
import time
from typing import Any, Dict, Iterator, List, Optional, Union


class WALManager:
    """
    Append-only Write-Ahead Log manager using JSON Lines.
    Ensures durability via immediate flushing and fsync on every write.
    """

    def __init__(self, filepath: Union[str, pathlib.Path]) -> None:
        self.filepath = pathlib.Path(filepath).resolve()
        if self.filepath.parent:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._file = open(self.filepath, mode="a", encoding="utf-8")

    def _write_record(self, record: Dict[str, Any]) -> None:
        """Serializes and flushes a single record to the append-only log file."""
        line = json.dumps(record, separators=(",", ":")) + "\n"
        with self._lock:
            if self._file.closed:
                raise ValueError("Cannot write to closed WAL file.")
            self._file.write(line)
            self._file.flush()
            os.fsync(self._file.fileno())

    def log_set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Logs a SET operation."""
        record: Dict[str, Any] = {
            "op": "SET",
            "key": key,
            "value": value,
            "ttl": ttl,
            "ts": time.time(),
        }
        self._write_record(record)

    def log_delete(self, key: str) -> None:
        """Logs a DELETE operation."""
        record: Dict[str, Any] = {
            "op": "DELETE",
            "key": key,
            "ts": time.time(),
        }
        self._write_record(record)

    def log_expire(self, key: str, ttl: float) -> None:
        """Logs an EXPIRE operation."""
        record: Dict[str, Any] = {
            "op": "EXPIRE",
            "key": key,
            "ttl": ttl,
            "ts": time.time(),
        }
        self._write_record(record)

    def log_flush(self) -> None:
        """Logs a FLUSH operation."""
        record: Dict[str, Any] = {
            "op": "FLUSH",
            "ts": time.time(),
        }
        self._write_record(record)

    @staticmethod
    def recover_records(
        filepath: Union[str, pathlib.Path],
        truncate_torn_tail: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Parses and recovers valid records from the WAL file.
        Safely ignores an incomplete/torn final record caused by an interrupted write.
        Raises ValueError if corruption occurs within prior (middle) records.
        """
        path = pathlib.Path(filepath).resolve()
        if not path.exists():
            return []

        with open(path, mode="r", encoding="utf-8", errors="replace") as f:
            raw_lines = f.readlines()

        indexed_lines = [(i, line.strip()) for i, line in enumerate(raw_lines) if line.strip()]
        if not indexed_lines:
            return []

        valid_records: List[Dict[str, Any]] = []
        has_torn_tail = False
        last_valid_line_idx = -1

        for pos, (orig_idx, line) in enumerate(indexed_lines):
            is_last = (pos == len(indexed_lines) - 1)
            try:
                record = json.loads(line)
                valid_records.append(record)
                last_valid_line_idx = orig_idx
            except json.JSONDecodeError as err:
                if is_last:
                    # Torn write at the end of the log
                    has_torn_tail = True
                else:
                    # Non-final corrupted record
                    raise ValueError(
                        f"Corrupted WAL record at line {orig_idx + 1}: {err}"
                    ) from err

        if has_torn_tail and truncate_torn_tail:
            valid_content = "".join(raw_lines[: last_valid_line_idx + 1]) if last_valid_line_idx >= 0 else ""
            if valid_content and not valid_content.endswith("\n"):
                valid_content += "\n"
            with open(path, mode="w", encoding="utf-8") as f:
                f.write(valid_content)
                f.flush()
                os.fsync(f.fileno())

        return valid_records

    @staticmethod
    def read_from_file(filepath: Union[str, pathlib.Path]) -> Iterator[Dict[str, Any]]:
        """Reads and yields all valid records from any given WAL file path."""
        records = WALManager.recover_records(filepath, truncate_torn_tail=False)
        yield from records

    def read_records(self) -> Iterator[Dict[str, Any]]:
        """Yields all parsed records from this WAL file."""
        yield from self.read_from_file(self.filepath)

    def close(self) -> None:
        """Flushes, syncs, and closes the WAL file handle."""
        with self._lock:
            if not self._file.closed:
                self._file.flush()
                try:
                    os.fsync(self._file.fileno())
                except OSError:
                    pass
                self._file.close()

    def __enter__(self) -> WALManager:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
