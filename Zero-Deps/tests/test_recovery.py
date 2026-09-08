"""
Unit Tests for Crash Recovery and WAL Replay
============================================
Tests:
- SET recovery (basic key-value restoration)
- SET with TTL recovery (remaining TTL computed from record timestamp)
- Expired SET is not restored
- DELETE recovery
- EXPIRE recovery
- FLUSH recovery
- Multiple operations replayed in strict chronological order
- Recovery after closing and reopening StorageEngine instance
- Incomplete / torn final WAL record handled safely without crashing
- Corruption in middle of WAL raises ValueError
- New writes continue appending cleanly after recovery
"""

import json
import pathlib
import sys
import tempfile
import time
import unittest

# Ensure project root is in sys.path
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage_engine import StorageEngine
from wal import WALManager


class TestCrashRecovery(unittest.TestCase):
    """Test suite for WAL replay and crash recovery."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.wal_path = pathlib.Path(self.temp_dir.name) / "recovery_test.wal"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_set_recovery(self) -> None:
        # Step 1: Write directly to WAL
        with WALManager(self.wal_path) as wal:
            wal.log_set("k1", "value1")
            wal.log_set("k2", {"number": 42, "flag": True})

        # Step 2: Initialize engine pointing to that WAL
        with StorageEngine(wal_path=self.wal_path) as engine:
            self.assertEqual(engine.get("k1"), "value1")
            self.assertEqual(engine.get("k2"), {"number": 42, "flag": True})
            self.assertTrue(engine.exists("k1"))
            self.assertTrue(engine.exists("k2"))
            self.assertEqual(engine.ttl("k1"), -1)
            self.assertEqual(engine.ttl("k2"), -1)

    def test_set_with_ttl_recovery(self) -> None:
        # Write record with TTL that has not expired yet
        with WALManager(self.wal_path) as wal:
            wal.log_set("active_token", "secret", ttl=100.0)

        # Recover immediately
        with StorageEngine(wal_path=self.wal_path) as engine:
            self.assertEqual(engine.get("active_token"), "secret")
            rem = engine.ttl("active_token")
            self.assertIsNotNone(rem)
            self.assertGreater(rem, 90.0)
            self.assertLessEqual(rem, 100.0)

    def test_expired_set_not_restored(self) -> None:
        # Write record with timestamp in the past such that ts + ttl < now
        past_ts = time.time() - 100.0
        expired_record = {
            "op": "SET",
            "key": "old_session",
            "value": "expired_data",
            "ttl": 10.0,
            "ts": past_ts,
        }
        with open(self.wal_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(expired_record) + "\n")

        # Recover
        with StorageEngine(wal_path=self.wal_path) as engine:
            self.assertIsNone(engine.get("old_session"))
            self.assertFalse(engine.exists("old_session"))
            self.assertNotIn("old_session", engine.keys())
            self.assertIsNone(engine.ttl("old_session"))

    def test_delete_recovery(self) -> None:
        with WALManager(self.wal_path) as wal:
            wal.log_set("user:1", "Alice")
            wal.log_set("user:2", "Bob")
            wal.log_delete("user:1")

        with StorageEngine(wal_path=self.wal_path) as engine:
            self.assertIsNone(engine.get("user:1"))
            self.assertFalse(engine.exists("user:1"))
            self.assertEqual(engine.get("user:2"), "Bob")
            self.assertEqual(engine.keys(), ["user:2"])

    def test_expire_recovery(self) -> None:
        # Write SET then EXPIRE
        with WALManager(self.wal_path) as wal:
            wal.log_set("session", "abc")
            wal.log_expire("session", 300.0)

        with StorageEngine(wal_path=self.wal_path) as engine:
            self.assertEqual(engine.get("session"), "abc")
            rem = engine.ttl("session")
            self.assertIsNotNone(rem)
            self.assertGreater(rem, 280.0)
            self.assertLessEqual(rem, 300.0)

    def test_expire_already_elapsed_not_restored(self) -> None:
        past_ts = time.time() - 50.0
        records = [
            {"op": "SET", "key": "exp_key", "value": "val", "ts": past_ts},
            {"op": "EXPIRE", "key": "exp_key", "ttl": 10.0, "ts": past_ts},
        ]
        with open(self.wal_path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        with StorageEngine(wal_path=self.wal_path) as engine:
            self.assertIsNone(engine.get("exp_key"))
            self.assertFalse(engine.exists("exp_key"))

    def test_flush_recovery(self) -> None:
        with WALManager(self.wal_path) as wal:
            wal.log_set("k1", "v1")
            wal.log_set("k2", "v2")
            wal.log_flush()
            wal.log_set("k3", "v3")

        with StorageEngine(wal_path=self.wal_path) as engine:
            self.assertIsNone(engine.get("k1"))
            self.assertIsNone(engine.get("k2"))
            self.assertEqual(engine.get("k3"), "v3")
            self.assertEqual(engine.keys(), ["k3"])

    def test_multiple_operations_ordered_replay(self) -> None:
        with WALManager(self.wal_path) as wal:
            wal.log_set("item", "v1")
            wal.log_set("item", "v2")
            wal.log_set("item", "v3")
            wal.log_delete("item")
            wal.log_set("item", "final_val")

        with StorageEngine(wal_path=self.wal_path) as engine:
            self.assertEqual(engine.get("item"), "final_val")

    def test_recovery_after_close_and_reopen(self) -> None:
        # Engine 1 writes data and closes
        with StorageEngine(wal_path=self.wal_path) as engine1:
            engine1.set("persisted_key", "persisted_value")
            engine1.set("temp_key", "will_be_deleted")
            engine1.delete("temp_key")

        # Engine 2 opens the same WAL and recovers state
        with StorageEngine(wal_path=self.wal_path) as engine2:
            self.assertEqual(engine2.get("persisted_key"), "persisted_value")
            self.assertIsNone(engine2.get("temp_key"))

    def test_incomplete_final_wal_record(self) -> None:
        # Write valid records followed by an incomplete trailing line
        with open(self.wal_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"op": "SET", "key": "k1", "value": "val1", "ts": time.time()}) + "\n")
            f.write(json.dumps({"op": "SET", "key": "k2", "value": "val2", "ts": time.time()}) + "\n")
            # Incomplete / torn write
            f.write('{"op": "SET", "key": "k3", "val')

        # Recovery should succeed without crashing and recover k1 and k2
        with StorageEngine(wal_path=self.wal_path) as engine:
            self.assertEqual(engine.get("k1"), "val1")
            self.assertEqual(engine.get("k2"), "val2")
            self.assertIsNone(engine.get("k3"))

    def test_corrupted_middle_record_raises(self) -> None:
        with open(self.wal_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"op": "SET", "key": "k1", "value": "val1", "ts": time.time()}) + "\n")
            f.write("CORRUPTED_JSON_LINE\n")
            f.write(json.dumps({"op": "SET", "key": "k2", "value": "val2", "ts": time.time()}) + "\n")

        with self.assertRaises(ValueError):
            StorageEngine(wal_path=self.wal_path)

    def test_new_writes_after_recovery(self) -> None:
        # Session 1: Write and close
        with StorageEngine(wal_path=self.wal_path) as engine1:
            engine1.set("init_key", "init_val")

        # Session 2: Recover and write more
        with StorageEngine(wal_path=self.wal_path) as engine2:
            self.assertEqual(engine2.get("init_key"), "init_val")
            engine2.set("new_key", "new_val")

        # Session 3: Recover everything
        with StorageEngine(wal_path=self.wal_path) as engine3:
            self.assertEqual(engine3.get("init_key"), "init_val")
            self.assertEqual(engine3.get("new_key"), "new_val")


if __name__ == "__main__":
    unittest.main()
