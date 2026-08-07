import unittest

from api.publications import _estimated_cost_usd


class PublicationCostTests(unittest.TestCase):
    def test_uses_only_workflow_action_metadata(self):
        graph = {"nodes": [
            {"type": "trigger/manual", "properties": {"estimated_cost_usd": 99}},
            {"type": "action/openrouter_text", "properties": {"estimated_cost_usd": "0.23"}},
            {"type": "action/fal_universal_media", "properties": {}},
        ]}
        self.assertEqual(_estimated_cost_usd(graph), 0.33)

    def test_invalid_estimates_fail_closed_to_default(self):
        graph = {"nodes": [{"type": "action/openrouter_text", "properties": {"estimated_cost_usd": "-1"}}]}
        self.assertEqual(_estimated_cost_usd(graph), 0.1)


if __name__ == "__main__":
    unittest.main()
