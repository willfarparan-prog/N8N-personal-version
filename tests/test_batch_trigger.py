import unittest

from api._lib.nodes.base import NODE_REGISTRY


class BatchTriggerTests(unittest.TestCase):
    def test_batch_input_trigger_is_registered(self):
        # Import side effects are part of the engine contract.
        from api._lib import nodes  # noqa: F401
        self.assertIn("trigger/batch_input", NODE_REGISTRY)


if __name__ == "__main__":
    unittest.main()
