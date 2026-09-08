"""
Unit Tests for In-Memory StorageEngine
======================================
Tests CRUD operations, TTL expiration, remaining TTL queries, and concurrency.
"""

import pathlib
import sys
import threading
import time
import unittest

# Ensure project root is in sys.path
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage_engine import StorageEngine


class TestStorageEngineCore(unittest.TestCase):
    """Test suite for core in-memory CRUD operations."""

    def setUp(self) -> None:
        self.engine = StorageEngine()

    def test_set_and_get(self) -> None:
        self.assertTrue(self.engine.set("user:100", {"name": "Bob", "role": "admin"}))
        self.assertEqual(self.engine.get("user:100"), {"name": "Bob", "role": "admin"})

    def test_get_nonexistent_key(self) -> None:
        self.assertIsNone(self.engine.get("nonexistent"))

    def test_overwrite_key(self) -> None:
        self.assertTrue(self.engine.set("config:theme", "light"))
        self.assertEqual(self.engine.get("config:theme"), "light")
        self.assertTrue(self.engine.set("config:theme", "dark"))
        self.assertEqual(self.engine.get("config:theme"), "dark")

    def test_delete(self) -> None:
        self.engine.set("temp_key", "temporary_value")
        self.assertTrue(self.engine.delete("temp_key"))
        self.assertFalse(self.engine.delete("temp_key"))
        self.assertIsNone(self.engine.get("temp_key"))

    def test_exists(self) -> None:
        self.assertFalse(self.engine.exists("item"))
        self.engine.set("item", 42)
        self.assertTrue(self.engine.exists("item"))
        self.engine.delete("item")
        self.assertFalse(self.engine.exists("item"))

    def test_various_data_types(self) -> None:
        test_cases = [
            ("str_key", "hello world"),
            ("int_key", 12345),
            ("float_key", 99.99),
            ("bool_key", True),
            ("list_key", [1, 2, "three", {"four": 4}]),
            ("dict_key", {"nested": {"data": True}}),
            ("bytes_key", b"binary_data"),
        ]
        for k, v in test_cases:
            self.assertTrue(self.engine.set(k, v))
            self.assertEqual(self.engine.get(k), v)
            self.assertTrue(self.engine.exists(k))

    def test_none_value(self) -> None:
        self.assertTrue(self.engine.set("null_key", None))
        self.assertTrue(self.engine.exists("null_key"))
        self.assertIsNone(self.engine.get("null_key"))
        self.assertIn("null_key", self.engine.keys())
        self.assertTrue(self.engine.delete("null_key"))
        self.assertFalse(self.engine.exists("null_key"))

    def test_keys(self) -> None:
        self.assertEqual(self.engine.keys(), [])
        self.engine.set("a", 1)
        self.engine.set("b", 2)
        self.engine.set("c", 3)
        self.assertCountEqual(self.engine.keys(), ["a", "b", "c"])

    def test_flush(self) -> None:
        self.engine.set("k1", "v1")
        self.engine.set("k2", "v2", ttl=10.0)
        self.assertTrue(self.engine.flush())
        self.assertEqual(self.engine.keys(), [])
        self.assertIsNone(self.engine.get("k1"))
        self.assertIsNone(self.engine.get("k2"))
        self.assertIsNone(self.engine.ttl("k2"))

    def test_invalid_key_type(self) -> None:
        with self.assertRaises(TypeError):
            self.engine.set(123, "val")  # type: ignore
        with self.assertRaises(TypeError):
            self.engine.get(None)  # type: ignore
        with self.assertRaises(TypeError):
            self.engine.delete(3.14)  # type: ignore
        with self.assertRaises(TypeError):
            self.engine.exists([])  # type: ignore
        with self.assertRaises(TypeError):
            self.engine.expire(123, 10.0)  # type: ignore
        with self.assertRaises(TypeError):
            self.engine.ttl({})  # type: ignore


class TestStorageEngineTTL(unittest.TestCase):
    """Test suite for TTL expiration and query behaviors."""

    def setUp(self) -> None:
        self.engine = StorageEngine()

    def test_lazy_expiration(self) -> None:
        self.engine.set("token", "xyz-123", ttl=0.1)
        self.assertTrue(self.engine.exists("token"))
        self.assertEqual(self.engine.get("token"), "xyz-123")

        time.sleep(0.15)

        # Lazy eviction triggers on access
        self.assertFalse(self.engine.exists("token"))
        self.assertIsNone(self.engine.get("token"))
        self.assertNotIn("token", self.engine.keys())
        self.assertFalse(self.engine.delete("token"))

    def test_ttl_query(self) -> None:
        # Non-existent key -> None
        self.assertIsNone(self.engine.ttl("missing"))

        # Key without TTL -> -1
        self.engine.set("persistent", "val")
        self.assertEqual(self.engine.ttl("persistent"), -1)

        # Key with TTL -> remaining seconds (positive float)
        self.engine.set("expiring", "val", ttl=5.0)
        rem = self.engine.ttl("expiring")
        self.assertIsNotNone(rem)
        self.assertGreater(rem, 3.0)
        self.assertLessEqual(rem, 5.0)

    def test_expire_method(self) -> None:
        self.engine.set("session", "abc")
        self.assertEqual(self.engine.ttl("session"), -1)

        # Set TTL via expire()
        self.assertTrue(self.engine.expire("session", ttl=10.0))
        rem = self.engine.ttl("session")
        self.assertIsNotNone(rem)
        self.assertGreater(rem, 8.0)

        # Expire non-existent key returns False
        self.assertFalse(self.engine.expire("nonexistent", ttl=10.0))

    def test_set_with_nonpositive_ttl(self) -> None:
        self.engine.set("dead_on_arrival", "val", ttl=0)
        self.assertIsNone(self.engine.get("dead_on_arrival"))
        self.assertFalse(self.engine.exists("dead_on_arrival"))

        self.engine.set("negative_ttl", "val", ttl=-5.0)
        self.assertIsNone(self.engine.get("negative_ttl"))

    def test_expire_with_nonpositive_ttl(self) -> None:
        self.engine.set("active", "data")
        self.assertTrue(self.engine.expire("active", ttl=0))
        self.assertIsNone(self.engine.get("active"))
        self.assertFalse(self.engine.exists("active"))

    def test_overwrite_clears_or_updates_ttl(self) -> None:
        # Set with TTL
        self.engine.set("key", "val1", ttl=10.0)
        self.assertGreater(self.engine.ttl("key"), 0)

        # Overwrite without TTL removes expiration
        self.engine.set("key", "val2")
        self.assertEqual(self.engine.ttl("key"), -1)

    def test_keys_with_mixed_expiration(self) -> None:
        self.engine.set("k_perm", "permanent")
        self.engine.set("k_short", "short-lived", ttl=0.1)
        self.engine.set("k_long", "long-lived", ttl=10.0)

        time.sleep(0.15)

        active_keys = self.engine.keys()
        self.assertIn("k_perm", active_keys)
        self.assertIn("k_long", active_keys)
        self.assertNotIn("k_short", active_keys)


class TestStorageEngineConcurrency(unittest.TestCase):
    """Test suite verifying thread-safety under concurrent load."""

    def setUp(self) -> None:
        self.engine = StorageEngine()

    def test_concurrent_read_write_delete(self) -> None:
        num_threads = 8
        ops_per_thread = 100
        threads = []

        def worker(tid: int) -> None:
            for i in range(ops_per_thread):
                key = f"t_{tid}_k_{i}"
                self.engine.set(key, i, ttl=10.0 if i % 3 == 0 else None)
                val = self.engine.get(key)
                self.assertEqual(val, i)
                if i % 2 == 0:
                    self.engine.delete(key)

        for tid in range(num_threads):
            t = threading.Thread(target=worker, args=(tid,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Check expected final state
        for tid in range(num_threads):
            for i in range(ops_per_thread):
                key = f"t_{tid}_k_{i}"
                if i % 2 == 0:
                    self.assertFalse(self.engine.exists(key))
                else:
                    self.assertTrue(self.engine.exists(key))


if __name__ == "__main__":
    unittest.main()
