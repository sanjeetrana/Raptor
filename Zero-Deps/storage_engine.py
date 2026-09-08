"""
In-Memory Storage Engine Core with Write-Ahead Logging & Recovery
=================================================================
Zero-dependency, thread-safe in-memory key-value storage engine with WAL support
and crash recovery / replay.

Features:
- Primary dictionary-based key-value store
- Dedicated TTL expiry tracking dictionary
- Lazy TTL expiration on access
- Thread safety via threading.RLock
- Write-Ahead Logging (WAL) integration for append-only durability
- Crash recovery / replay from WAL upon initialization
"""

from __future__ import annotations

import pathlib
import threading
import time
from typing import Any, Dict, List, Optional, Union

from wal import WALManager


class StorageEngine:
    """
    In-memory key-value storage engine with TTL expiry support, thread-safety,
    append-only Write-Ahead Logging (WAL), and startup crash recovery.
    """

    def __init__(
        self,
        wal_path: Optional[Union[str, pathlib.Path]] = None,
        wal: Optional[WALManager] = None,
    ) -> None:
        self._data: Dict[str, Any] = {}
        self._expiry: Dict[str, float] = {}
        self._lock = threading.RLock()

        target_wal_path: Optional[pathlib.Path] = None
        if wal is not None:
            target_wal_path = wal.filepath
        elif wal_path is not None:
            target_wal_path = pathlib.Path(wal_path).resolve()

        # Step 1: Replay existing WAL if present to restore in-memory state
        if target_wal_path is not None and target_wal_path.exists():
            self._replay_wal(target_wal_path)

        # Step 2: Initialize WAL manager for future write operations
        if wal is not None:
            self._wal: Optional[WALManager] = wal
            self._owns_wal = False
        elif wal_path is not None:
            self._wal = WALManager(wal_path)
            self._owns_wal = True
        else:
            self._wal = None
            self._owns_wal = False

    def _replay_wal(self, wal_path: pathlib.Path) -> None:
        """
        Replays WAL records in strict file order to reconstruct the in-memory state.
        Does not emit new WAL records during replay.
        """
        records = WALManager.recover_records(wal_path, truncate_torn_tail=True)
        now = time.time()

        for rec in records:
            op = rec.get("op")
            if op == "SET":
                key = rec.get("key")
                if not isinstance(key, str):
                    continue
                val = rec.get("value")
                ttl = rec.get("ttl")
                ts = rec.get("ts", now)

                if ttl is not None:
                    if ttl <= 0:
                        self._data.pop(key, None)
                        self._expiry.pop(key, None)
                    else:
                        expire_at = ts + ttl
                        if expire_at <= now:
                            # Already expired at recovery time
                            self._data.pop(key, None)
                            self._expiry.pop(key, None)
                        else:
                            self._data[key] = val
                            self._expiry[key] = expire_at
                else:
                    self._data[key] = val
                    self._expiry.pop(key, None)

            elif op == "DELETE":
                key = rec.get("key")
                if isinstance(key, str):
                    self._data.pop(key, None)
                    self._expiry.pop(key, None)

            elif op == "EXPIRE":
                key = rec.get("key")
                if isinstance(key, str) and key in self._data:
                    ttl = rec.get("ttl")
                    ts = rec.get("ts", now)
                    if ttl is not None and ttl <= 0:
                        self._data.pop(key, None)
                        self._expiry.pop(key, None)
                    elif ttl is not None:
                        expire_at = ts + ttl
                        if expire_at <= now:
                            # Expired by recovery time
                            self._data.pop(key, None)
                            self._expiry.pop(key, None)
                        else:
                            self._expiry[key] = expire_at

            elif op == "FLUSH":
                self._data.clear()
                self._expiry.clear()

    @property
    def wal(self) -> Optional[WALManager]:
        """Returns the attached WALManager instance, if any."""
        return self._wal

    def _is_expired(self, key: str, now: Optional[float] = None) -> bool:
        """Helper to check if a key has exceeded its expiration timestamp."""
        if key not in self._expiry:
            return False
        if now is None:
            now = time.time()
        return self._expiry[key] <= now

    def _purge_if_expired(self, key: str, now: Optional[float] = None) -> bool:
        """
        Lazily evicts key if expired.
        Returns True if evicted, False otherwise.
        """
        if self._is_expired(key, now):
            self._data.pop(key, None)
            self._expiry.pop(key, None)
            return True
        return False

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> bool:
        """
        Stores key-value pair with optional TTL in seconds.
        Logs to WAL before in-memory mutation when WAL is enabled.
        Returns True on success.
        """
        if not isinstance(key, str):
            raise TypeError(f"Key must be a string, got {type(key).__name__}")

        with self._lock:
            if self._wal is not None:
                self._wal.log_set(key, value, ttl=ttl)

            if ttl is not None and ttl <= 0:
                # Setting with non-positive TTL expires/deletes the key immediately
                self._data.pop(key, None)
                self._expiry.pop(key, None)
                return True

            self._data[key] = value
            if ttl is not None:
                self._expiry[key] = time.time() + ttl
            else:
                self._expiry.pop(key, None)

            return True

    def get(self, key: str) -> Optional[Any]:
        """
        Retrieves the value for key.
        Returns None if key does not exist or has expired.
        """
        if not isinstance(key, str):
            raise TypeError(f"Key must be a string, got {type(key).__name__}")

        with self._lock:
            if self._purge_if_expired(key):
                return None
            return self._data.get(key)

    def delete(self, key: str) -> bool:
        """
        Deletes key from storage.
        Logs to WAL before in-memory mutation when WAL is enabled.
        Returns True if the key was present and unexpired, False otherwise.
        """
        if not isinstance(key, str):
            raise TypeError(f"Key must be a string, got {type(key).__name__}")

        with self._lock:
            if self._purge_if_expired(key):
                return False

            if key in self._data:
                if self._wal is not None:
                    self._wal.log_delete(key)

                self._data.pop(key, None)
                self._expiry.pop(key, None)
                return True

            return False

    def exists(self, key: str) -> bool:
        """
        Checks whether key exists and is unexpired.
        Returns True/False.
        """
        if not isinstance(key, str):
            raise TypeError(f"Key must be a string, got {type(key).__name__}")

        with self._lock:
            if self._purge_if_expired(key):
                return False
            return key in self._data

    def expire(self, key: str, ttl: float) -> bool:
        """
        Sets or updates the TTL (in seconds) for an existing key.
        Logs to WAL before in-memory mutation when WAL is enabled.
        Returns True if key exists and was updated, False otherwise.
        """
        if not isinstance(key, str):
            raise TypeError(f"Key must be a string, got {type(key).__name__}")

        with self._lock:
            if self._purge_if_expired(key) or key not in self._data:
                return False

            if self._wal is not None:
                self._wal.log_expire(key, ttl)

            if ttl <= 0:
                self._data.pop(key, None)
                self._expiry.pop(key, None)
                return True

            self._expiry[key] = time.time() + ttl
            return True

    def ttl(self, key: str) -> Optional[float]:
        """
        Returns remaining TTL in seconds.
        - Returns float > 0 for remaining time
        - Returns -1 for key with no TTL
        - Returns None for missing or expired key
        """
        if not isinstance(key, str):
            raise TypeError(f"Key must be a string, got {type(key).__name__}")

        with self._lock:
            if self._purge_if_expired(key) or key not in self._data:
                return None

            if key not in self._expiry:
                return -1

            remaining = self._expiry[key] - time.time()
            return max(0.0, remaining)

    def keys(self) -> List[str]:
        """
        Returns a list of all active, unexpired keys.
        """
        with self._lock:
            now = time.time()
            expired_keys = [k for k, exp in self._expiry.items() if exp <= now]
            for k in expired_keys:
                self._data.pop(k, None)
                self._expiry.pop(k, None)

            return list(self._data.keys())

    def flush(self) -> bool:
        """
        Clears all data and expiry entries.
        Logs to WAL before clearing state when WAL is enabled.
        Returns True.
        """
        with self._lock:
            if self._wal is not None:
                self._wal.log_flush()

            self._data.clear()
            self._expiry.clear()
            return True

    def close(self) -> None:
        """Closes the storage engine and any owned WAL manager."""
        with self._lock:
            if self._wal is not None and self._owns_wal:
                self._wal.close()

    def __enter__(self) -> StorageEngine:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
