"""
test_caller_graph.py — Tests for caller_graph.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from proofline.symbol_map import Confidence, Location
from proofline.caller_graph import CallGraph, GraphEdge, CallerResult


class TestCallGraph(unittest.TestCase):

    def _make_edge(self, src: str, dst: str, confidence: Confidence) -> GraphEdge:
        return GraphEdge(
            src=src,
            dst=dst,
            confidence=confidence,
            location=Location(file="test.py", line=1),
        )

    def test_add_edge_and_callers_of(self):
        g = CallGraph()
        edge = self._make_edge("A.foo", "B.bar", Confidence.PROVEN)
        g.add_edge(edge)
        callers = g.callers_of("B.bar")
        self.assertEqual(len(callers), 1)
        self.assertEqual(callers[0].src, "A.foo")

    def test_callees_of(self):
        g = CallGraph()
        edge = self._make_edge("A.foo", "B.bar", Confidence.PROVEN)
        g.add_edge(edge)
        callees = g.callees_of("A.foo")
        self.assertEqual(len(callees), 1)
        self.assertEqual(callees[0].dst, "B.bar")

    def test_multiple_edges(self):
        g = CallGraph()
        g.add_edge(self._make_edge("X", "Y", Confidence.PROVEN))
        g.add_edge(self._make_edge("Z", "Y", Confidence.INFERRED))
        g.add_edge(self._make_edge("W", "Y", Confidence.UNKNOWN))
        callers = g.callers_of("Y")
        self.assertEqual(len(callers), 3)

    def test_confidence_preserved(self):
        g = CallGraph()
        g.add_edge(self._make_edge("A", "B", Confidence.UNKNOWN))
        edge = g.callers_of("B")[0]
        self.assertEqual(edge.confidence, Confidence.UNKNOWN)

    def test_len(self):
        g = CallGraph()
        for i in range(5):
            g.add_edge(self._make_edge(f"src{i}", "dst", Confidence.PROVEN))
        self.assertEqual(len(g), 5)

    def test_empty_graph(self):
        g = CallGraph()
        self.assertEqual(g.callers_of("nonexistent"), [])
        self.assertEqual(g.callees_of("nonexistent"), [])
        self.assertEqual(len(g), 0)

    def test_caller_result_summary(self):
        cr = CallerResult(symbol_name="foo")
        cr.proven_callers = [self._make_edge("A", "foo", Confidence.PROVEN)]
        cr.inferred_callers = [self._make_edge("B", "foo", Confidence.INFERRED),
                               self._make_edge("C", "foo", Confidence.INFERRED)]
        cr.unknown_callers = [self._make_edge("D", "foo", Confidence.UNKNOWN)]

        self.assertEqual(cr.total, 4)
        self.assertIn("1 PROVEN", cr.summary_str())
        self.assertIn("2 INFERRED", cr.summary_str())
        self.assertIn("1 UNKNOWN", cr.summary_str())

    def test_edge_to_dict(self):
        edge = self._make_edge("src", "dst", Confidence.INFERRED)
        d = edge.to_dict()
        self.assertEqual(d["src"], "src")
        self.assertEqual(d["dst"], "dst")
        self.assertEqual(d["confidence"], "INFERRED")
        self.assertIn("location", d)


if __name__ == "__main__":
    unittest.main()
