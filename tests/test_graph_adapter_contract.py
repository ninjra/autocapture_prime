import unittest

from autocapture.indexing.graph import GraphAdapter


class GraphAdapterContractTests(unittest.TestCase):
    def test_graph_adapter(self) -> None:
        adapter = GraphAdapter()
        adapter.add_edge("a", "b", "rel")
        neighbors = adapter.neighbors("a")
        self.assertEqual(len(neighbors), 1)
        self.assertEqual(neighbors[0].target, "b")
        self.assertIn("a", adapter.nodes())


if __name__ == "__main__":
    unittest.main()
