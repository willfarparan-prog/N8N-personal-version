import unittest

from api._lib.nodes.base import Artifact, NodeResult


class ArtifactContractTests(unittest.TestCase):
    def test_serializes_the_complete_canonical_envelope(self):
        artifact = Artifact(kind="text", value="hello", provider="openrouter")
        self.assertEqual(
            artifact.to_dict(),
            {
                "kind": "text", "url": None, "value": "hello", "mime_type": None,
                "name": None, "provider": "openrouter", "model": None,
                "metadata": {}, "usage": {},
            },
        )

    def test_rejects_unknown_artifact_kinds(self):
        with self.assertRaises(ValueError):
            Artifact(kind="unknown")

    def test_legacy_async_result_stays_compatible(self):
        self.assertEqual(NodeResult(status="pending_external").status, "waiting_provider")


if __name__ == "__main__":
    unittest.main()
