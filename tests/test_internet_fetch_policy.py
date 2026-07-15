import unittest
from unittest.mock import patch

from internet_curator import _requests_get_public, normalize_url, same_site


class _Redirect:
    status_code = 302

    def __init__(self, location):
        self.headers = {"location": location}
        self.closed = False

    def close(self):
        self.closed = True


class InternetFetchPolicyTests(unittest.TestCase):
    def test_normalization_rejects_private_or_credentialed_targets(self):
        self.assertEqual(normalize_url("http://127.0.0.1/admin"), "")
        self.assertEqual(normalize_url("http://169.254.169.254/latest"), "")
        self.assertEqual(normalize_url("https://user:pass@example.com/"), "")
        self.assertEqual(normalize_url("https://example.com:8443/"), "")
        self.assertEqual(normalize_url("https://localhost/"), "")
        self.assertEqual(normalize_url("https://example.com/article"), "https://example.com/article")

    def test_www_redirect_is_same_site_but_cross_site_redirect_is_blocked(self):
        self.assertTrue(same_site("https://www.example.com/a", "https://example.com"))
        response = _Redirect("http://169.254.169.254/latest/meta-data")
        with patch("internet_curator.requests.get", return_value=response) as get:
            result = _requests_get_public("https://example.com/article", timeout=5)
        self.assertIsNone(result)
        self.assertEqual(get.call_count, 1)
        self.assertTrue(response.closed)


if __name__ == "__main__":
    unittest.main()
