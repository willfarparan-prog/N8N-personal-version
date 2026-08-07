import unittest
from api._lib.url_safety import is_safe_public_https_url

class WebhookSafetyTests(unittest.TestCase):
    def test_requires_https_and_rejects_local_addresses(self):
        self.assertFalse(is_safe_public_https_url("http://example.com"))
        self.assertFalse(is_safe_public_https_url("https://127.0.0.1/hook"))

if __name__ == "__main__": unittest.main()
