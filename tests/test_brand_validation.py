import unittest

from api.brand_kits import _actual_image_mime


class BrandValidationTests(unittest.TestCase):
    def test_detects_allowed_magic_bytes(self):
        self.assertEqual(_actual_image_mime(b"\x89PNG\r\n\x1a\nrest"), "image/png")
        self.assertEqual(_actual_image_mime(b"\xff\xd8\xffrest"), "image/jpeg")
        self.assertEqual(_actual_image_mime(b"RIFFxxxxWEBPrest"), "image/webp")

    def test_rejects_claimed_but_invalid_bytes(self):
        self.assertIsNone(_actual_image_mime(b"not an image"))


if __name__ == "__main__":
    unittest.main()
