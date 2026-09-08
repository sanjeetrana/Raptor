import unittest
from pathlib import Path

from loglens import parse_log_file


class TestLogLens(unittest.TestCase):

    def setUp(self):
        self.test_file = Path("test_sample.log")

        self.test_file.write_text(
            "2026-08-28 10:00:00 INFO Server started\n"
            "2026-08-28 10:01:00 WARNING High memory usage\n"
            "2026-08-28 10:02:00 ERROR Database failed for user 101\n"
            "2026-08-28 10:03:00 ERROR Database failed for user 102\n",
            encoding="utf-8"
        )

    def tearDown(self):
        if self.test_file.exists():
            self.test_file.unlink()

    def test_total_lines(self):
        data = parse_log_file("test_sample.log")
        self.assertEqual(data["total_lines"], 4)

    def test_error_count(self):
        data = parse_log_file("test_sample.log")
        self.assertEqual(data["levels"]["ERROR"], 2)

    def test_warning_count(self):
        data = parse_log_file("test_sample.log")
        self.assertEqual(data["levels"]["WARNING"], 1)

    def test_info_count(self):
        data = parse_log_file("test_sample.log")
        self.assertEqual(data["levels"]["INFO"], 1)


if __name__ == "__main__":
    unittest.main()