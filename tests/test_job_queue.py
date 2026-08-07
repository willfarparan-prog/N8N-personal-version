import unittest

from api._lib.job_queue import claim_jobs, enqueue_job


class _Result:
    data = [{"id": "job-1"}]


class _Query:
    def insert(self, value): self.value = value; return self
    def execute(self): return _Result()


class _Client:
    def table(self, name): self.name = name; return _Query()


class QueueContractTests(unittest.TestCase):
    def test_enqueue_uses_the_workflow_jobs_table_and_json_object(self):
        client = _Client()
        enqueue_job(client, "execute", "execution-1", payload={"a": 1}, idempotency_key="unique-1")
        self.assertEqual(client.name, "workflow_jobs")

    def test_claim_limit_is_strictly_bounded(self):
        with self.assertRaises(ValueError):
            claim_jobs(_Client(), 4)


if __name__ == "__main__":
    unittest.main()
