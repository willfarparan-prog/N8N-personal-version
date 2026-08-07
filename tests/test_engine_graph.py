import unittest

from api._lib.graph import GraphValidationError, build_graph_index, topo_order


class GraphOrderTests(unittest.TestCase):
    def test_orders_fan_out_and_join_only_after_both_parents(self):
        graph = {"nodes": [{"id": item} for item in (1, 2, 3, 4)], "links": [
            [1, 1, 0, 2, 0, ""], [2, 1, 0, 3, 0, ""], [3, 2, 0, 4, 0, ""], [4, 3, 0, 4, 1, ""],
        ]}
        nodes, incoming = build_graph_index(graph)
        self.assertEqual(topo_order(nodes, incoming, 1), [1, 2, 3, 4])

    def test_rejects_reachable_cycles(self):
        graph = {"nodes": [{"id": item} for item in (1, 2, 3)], "links": [
            [1, 1, 0, 2, 0, ""], [2, 2, 0, 3, 0, ""], [3, 3, 0, 2, 0, ""],
        ]}
        nodes, incoming = build_graph_index(graph)
        with self.assertRaises(GraphValidationError):
            topo_order(nodes, incoming, 1)


if __name__ == "__main__":
    unittest.main()
