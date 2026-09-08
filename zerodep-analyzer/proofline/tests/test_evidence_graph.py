"""
test_evidence_graph.py — Tests for evidence_graph.py

Verifies: append-only storage, JSON round-trip, node kinds.
"""
import json
import sys
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from proofline.evidence_graph import (
    EvidenceGraph,
    EvidenceNode,
    EvidenceEdge,
    ChangeSummary,
    VerificationChecklistItem,
)
from proofline.symbol_map import Confidence, Location


class TestEvidenceGraph(unittest.TestCase):

    def _make_node(self, kind: str, name: str) -> EvidenceNode:
        return EvidenceNode(
            node_id=f"{kind}_{name}",
            kind=kind,
            name=name,
            file="test.py",
            line=1,
            confidence=Confidence.PROVEN,
        )

    def _make_edge(self, src: str, dst: str) -> EvidenceEdge:
        return EvidenceEdge(
            src_id=src,
            dst_id=dst,
            relationship="calls",
            confidence=Confidence.PROVEN,
        )

    def test_append_only_nodes(self):
        eg = EvidenceGraph()
        n1 = self._make_node("changed_symbol", "foo")
        n2 = self._make_node("caller", "bar")
        eg.add_node(n1)
        eg.add_node(n2)
        self.assertEqual(len(eg.nodes()), 2)
        # Verify order preserved (append-only)
        self.assertEqual(eg.nodes()[0].name, "foo")
        self.assertEqual(eg.nodes()[1].name, "bar")

    def test_append_only_edges(self):
        eg = EvidenceGraph()
        e1 = self._make_edge("sym_1", "caller_1")
        e2 = self._make_edge("sym_1", "test_1")
        eg.add_edge(e1)
        eg.add_edge(e2)
        self.assertEqual(len(eg.edges()), 2)

    def test_nodes_by_kind(self):
        eg = EvidenceGraph()
        eg.add_node(self._make_node("changed_symbol", "fn1"))
        eg.add_node(self._make_node("caller", "caller1"))
        eg.add_node(self._make_node("caller", "caller2"))
        eg.add_node(self._make_node("route", "GET /orders"))
        eg.add_node(self._make_node("test", "test_fn1"))

        self.assertEqual(len(eg.nodes_by_kind("caller")), 2)
        self.assertEqual(len(eg.nodes_by_kind("route")), 1)
        self.assertEqual(len(eg.nodes_by_kind("test")), 1)
        self.assertEqual(len(eg.nodes_by_kind("nonexistent")), 0)

    def test_json_round_trip(self):
        eg = EvidenceGraph(before_dir="/before", after_dir="/after")
        eg.add_node(self._make_node("changed_symbol", "auth.validate_token"))
        eg.add_node(self._make_node("caller", "orders.get_orders"))
        eg.add_edge(self._make_edge(
            "caller_orders.get_orders", "changed_symbol_auth.validate_token"
        ))

        json_str = eg.to_json()
        parsed = json.loads(json_str)

        self.assertEqual(parsed["before_dir"], "/before")
        self.assertEqual(parsed["after_dir"], "/after")
        self.assertEqual(len(parsed["nodes"]), 2)
        self.assertEqual(len(parsed["edges"]), 1)

    def test_change_summary_to_dict(self):
        cs = ChangeSummary(
            symbol_name="auth.validate_token",
            file="auth.py",
            change_type="modified",
            implementation_changed=True,
            proven_callers=3,
            inferred_callers=2,
            unknown_callers=1,
            test_count=2,
            tests_changed=False,
            severity="HIGH",
            confidence="MEDIUM",
        )
        d = cs.to_dict()
        self.assertEqual(d["symbol_name"], "auth.validate_token")
        self.assertEqual(d["callers"]["proven"], 3)
        self.assertEqual(d["callers"]["total"], 6)
        self.assertEqual(d["severity"], "HIGH")
        self.assertIn("disclaimer", d["tests"])
        self.assertIn("association only", d["tests"]["disclaimer"])

    def test_verification_checklist_item(self):
        item = VerificationChecklistItem(
            action="Test malformed token behavior",
            priority="HIGH",
            reason="Broad exception handler added",
        )
        self.assertEqual(item.priority, "HIGH")
        self.assertIn("malformed", item.action)

    def test_evidence_node_to_dict(self):
        node = self._make_node("route", "GET /orders")
        d = node.to_dict()
        self.assertEqual(d["kind"], "route")
        self.assertEqual(d["confidence"], "PROVEN")
        self.assertIn("file", d)
        self.assertIn("line", d)

    def test_evidence_edge_to_dict(self):
        edge = EvidenceEdge(
            src_id="sym_1",
            dst_id="caller_1",
            relationship="calls",
            confidence=Confidence.INFERRED,
        )
        d = edge.to_dict()
        self.assertEqual(d["confidence"], "INFERRED")
        self.assertEqual(d["relationship"], "calls")

    def test_empty_graph_serializes(self):
        eg = EvidenceGraph()
        json_str = eg.to_json()
        parsed = json.loads(json_str)
        self.assertEqual(parsed["nodes"], [])
        self.assertEqual(parsed["edges"], [])

    def test_graph_is_mutable_after_init(self):
        """Append-only means we can keep adding, not that we can't add."""
        eg = EvidenceGraph()
        for i in range(100):
            eg.add_node(self._make_node("caller", f"fn_{i}"))
        self.assertEqual(len(eg.nodes()), 100)


if __name__ == "__main__":
    unittest.main()
