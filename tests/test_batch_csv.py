import unittest
from api._lib.batch_csv import BatchCsvError, parse_batch_csv

class BatchCsvTests(unittest.TestCase):
    def test_strips_empty_rows_and_preserves_order(self):
        headers, rows = parse_batch_csv(b"name,prompt\nA,one\n,\nB,two\n")
        self.assertEqual(headers, ["name", "prompt"])
        self.assertEqual(rows, [{"name": "A", "prompt": "one"}, {"name": "B", "prompt": "two"}])

    def test_rejects_duplicate_headers(self):
        with self.assertRaises(BatchCsvError): parse_batch_csv(b"name,name\nA,B\n")

if __name__ == "__main__": unittest.main()
