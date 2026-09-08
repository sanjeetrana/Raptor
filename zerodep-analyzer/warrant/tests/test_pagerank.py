"""Tests for PageRank engine."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
from pagerank import pagerank, normalise


class TestPageRank(unittest.TestCase):
    def test_scores_sum_to_one(self):
        graph = {"A": {"B", "C"}, "B": {"C"}, "C": {"A"}, "D": {"C"}}
        scores = pagerank(graph)
        total = sum(scores.values())
        self.assertAlmostEqual(total, 1.0, places=4)

    def test_well_connected_node_ranks_higher(self):
        # C receives links from all other nodes
        graph = {"A": {"C"}, "B": {"C"}, "C": {"A"}, "D": {"C"}}
        scores = pagerank(graph)
        # C should rank higher than D (D receives no inbound links)
        self.assertGreater(scores["C"], scores["D"])

    def test_empty_graph(self):
        self.assertEqual(pagerank({}), {})

    def test_single_node(self):
        graph = {"A": set()}
        scores = pagerank(graph)
        self.assertIn("A", scores)
        self.assertAlmostEqual(scores["A"], 1.0, places=4)

    def test_dangling_nodes_handled(self):
        # B has no outbound links — should not crash
        graph = {"A": {"B"}, "B": set()}
        scores = pagerank(graph)
        self.assertEqual(len(scores), 2)
        self.assertGreater(scores["B"], 0)  # B gets link from A

    def test_all_nodes_have_scores(self):
        graph = {"A": {"B"}, "B": {"C"}, "C": set()}
        scores = pagerank(graph)
        self.assertIn("A", scores)
        self.assertIn("B", scores)
        self.assertIn("C", scores)

    def test_normalise(self):
        scores = {"A": 0.4, "B": 0.8, "C": 0.2}
        normed = normalise(scores)
        self.assertAlmostEqual(normed["B"], 1.0)
        self.assertAlmostEqual(normed["A"], 0.5)
        self.assertAlmostEqual(normed["C"], 0.25)

    def test_normalise_empty(self):
        self.assertEqual(normalise({}), {})

    def test_normalise_zero_max(self):
        scores = {"A": 0.0, "B": 0.0}
        normed = normalise(scores)
        self.assertEqual(normed, {"A": 0.0, "B": 0.0})

    def test_convergence_within_max_iter(self):
        # 4-node cycle — should converge well within 100 iterations
        graph = {"A": {"B"}, "B": {"C"}, "C": {"D"}, "D": {"A"}}
        scores = pagerank(graph, max_iter=100)
        # All nodes should have roughly equal rank in a cycle
        vals = list(scores.values())
        self.assertAlmostEqual(max(vals) - min(vals), 0.0, places=3)

    def test_call_graph_as_input(self):
        """Simulate using function call graph as PageRank input."""
        # validate_token is called by 3 functions → should rank highest
        graph = {
            "auth.validate_token": set(),
            "orders.create_order": {"auth.validate_token"},
            "orders.cancel_order": {"auth.validate_token"},
            "routes.get_orders": {"auth.validate_token", "orders.create_order"},
        }
        scores = pagerank(graph)
        # validate_token has 3 inbound links — must rank highest
        self.assertEqual(
            max(scores, key=scores.get),
            "auth.validate_token",
        )


if __name__ == "__main__":
    unittest.main()
