"""
Unit Tests for Write-Ahead Log (WAL) and StorageEngine WAL Integration
======================================================================
Tests:
- WAL file creation
- SET record being written
- DELETE record being written
- EXPIRE record being written
- FLUSH record being written
- Multiple operations appended in strict sequence
- WAL persistence after closing and reopening
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


class TestWALManagerDirect(unittest.TestCase):
    """Direct tests for the WALManager component."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.wal_path = pathlib.Path(self.temp_dir.name) / "test.wal"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_wal_file_creation(self) -> None:
        self.assertFalse(self.wal_path.exists())
        wal = WALManager(self.wal_path)
        self.assertTrue(self.wal_path.exists())
        wal.close()

    def test_set_record_written(self) -> None:
        with WALManager(self.wal_path) as wal:
            wal.log_set("user:1", {"name": "Alice"}, ttl=60.0)

        records = list(WALManager.read_from_file(self.wal_path))
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["op"], "SET")
        self.assertEqual(rec["key"], "user:1")
        self.assertEqual(rec["value"], {"name": "Alice"})
        self.assertEqual(rec["ttl"], 60.0)
        self.assertIn("ts", rec)

    def test_delete_record_written(self) -> None:
        with WALManager(self.wal_path) as wal:
            wal.log_delete("user:1")

        records = list(WALManager.read_from_file(self.wal_path))
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["op"], "DELETE")
        self.assertEqual(rec["key"], "user:1")
        self.assertIn("ts", rec)

    def test_expire_record_written(self) -> None:
        with WALManager(self.wal_path) as wal:
            wal.log_expire("session:token", 300.0)

        records = list(WALManager.read_from_file(self.wal_path))
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["op"], "EXPIRE")
        self.assertEqual(rec["key"], "session:token")
        self.assertEqual(rec["ttl"], 300.0)
        self.assertIn("ts", rec)

    def test_flush_record_written(self) -> None:
        with WALManager(self.wal_path) as wal:
            wal.log_flush()

        records = list(WALManager.read_from_file(self.wal_path))
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["op"], "FLUSH")
        self.assertIn("ts", rec)

    def test_multiple_operations_in_order(self) -> None:
        with WALManager(self.wal_path) as wal:
            wal.log_set("k1", "v1")
            wal.log_set("k2", "v2", ttl=10.0)
            wal.log_expire("k1", 5.0)
            wal.log_delete("k2")
            wal.log_flush()

        records = list(WALManager.read_from_file(self.wal_path))
        self.assertEqual(len(records), 5)
        self.assertEqual(records[0]["op"], "SET")
        self.assertEqual(records[0]["key"], "k1")
        self.assertEqual(records[1]["op"], "SET")
        self.assertEqual(records[1]["key"], "k2")
        self.assertEqual(records[2]["op"], "EXPIRE")
        self.assertEqual(records[2]["key"], "k1")
        self.assertEqual(records[3]["op"], "DELETE")
        self.assertEqual(records[3]["key"], "k2")
        self.assertEqual(records[4]["op"], "FLUSH")

    def test_wal_persistence_after_close(self) -> None:
        wal1 = WALManager(self.wal_path)
        wal1.log_set("persisted", 123)
        wal1.close()

        # Reopen with new manager instance and append more
        wal2 = WALManager(self.wal_path)
        wal2.log_set("another", 456)
        wal2.close()

        # Read back raw lines directly from disk
        with open(self.wal_path, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]

        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["key"], "persisted")
        self.assertEqual(lines[1]["key"], "another")


class TestStorageEngineWALIntegration(unittest.TestCase):
    """Tests for StorageEngine write-ahead logging integration."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.wal_path = pathlib.Path(self.temp_dir.name) / "engine.wal"
        self.engine = StorageEngine(wal_path=self.wal_path)

    def tearDown(self) -> None:
        self.engine.close()
        self.temp_dir.cleanup()

    def _read_wal_records(self) -> list:
        with open(self.wal_path, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def test_set_logs_to_wal(self) -> None:
        self.engine.set("theme", "dark", ttl=3600.0)
        records = self._read_wal_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["op"], "SET")
        self.assertEqual(records[0]["key"], "theme")
        self.assertEqual(records[0]["value"], "dark")
        self.assertEqual(records[0]["ttl"], 3600.0)

    def test_delete_logs_to_wal(self) -> None:
        self.engine.set("cache_key", "data")
        self.assertTrue(self.engine.delete("cache_key"))
        records = self._read_wal_records()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["op"], "SET")
        self.assertEqual(records[1]["op"], "DELETE")
        self.assertEqual(records[1]["key"], "cache_key")

    def test_delete_missing_does_not_log(self) -> None:
        self.assertFalse(self.engine.delete("nonexistent"))
        records = self._read_wal_records()
        self.assertEqual(len(records), 0)

    def test_expire_logs_to_wal(self) -> None:
        self.engine.set("session", "xyz")
        self.assertTrue(self.engine.expire("session", 600.0))
        records = self._read_wal_records()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[1]["op"], "EXPIRE")
        self.assertEqual(records[1]["key"], "session")
        self.assertEqual(records[1]["ttl"], 600.0)

    def test_expire_missing_does_not_log(self) -> None:
        self.assertFalse(self.engine.expire("nonexistent", 10.0))
        records = self._read_wal_records()
        self.assertEqual(len(records), 0)

    def test_flush_logs_to_wal(self) -> None:
        self.engine.set("k1", 1)
        self.engine.flush()
        records = self._read_wal_records()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["op"], "SET")
        self.assertEqual(records[1]["op"], "FLUSH")

    def test_sequential_operations_persisted(self) -> None:
        self.engine.set("counter", 1)
        self.engine.set("counter", 2)
        self.engine.set("counter", 3)
        self.engine.expire("counter", 100.0)
        self.engine.delete("counter")

        records = self._read_wal_records()
        self.assertEqual(len(records), 5)
        self.assertEqual([r["op"] for r in records], ["SET", "SET", "SET", "EXPIRE", "DELETE"])


if __name__ == "__main__":
    unittest.main()
