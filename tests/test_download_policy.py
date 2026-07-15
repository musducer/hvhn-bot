import unittest

from download_policy import is_allowed_pdf_url, safe_redirect_url
import watcher


class _RedirectResponse:
    status_code = 302
    url = "https://drive.google.com/uc?id=abc"

    def __init__(self, location):
        self.headers = {"Location": location}
        self.closed = False

    def close(self):
        self.closed = True


class _Session:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def get(self, *_args, **_kwargs):
        self.calls += 1
        return self.response


class DownloadPolicyTest(unittest.TestCase):
    def test_only_https_drive_download_hosts_are_allowed(self):
        self.assertTrue(is_allowed_pdf_url("https://drive.google.com/file/d/abc/view"))
        self.assertTrue(is_allowed_pdf_url("https://drive.usercontent.google.com/download?id=abc"))
        self.assertTrue(is_allowed_pdf_url("https://doc-00-00-docs.googleusercontent.com/file.pdf"))
        self.assertFalse(is_allowed_pdf_url("http://drive.google.com/file/d/abc/view"))
        self.assertFalse(is_allowed_pdf_url("https://drive.google.com.evil.example/file.pdf"))
        self.assertFalse(is_allowed_pdf_url("https://user@drive.google.com/file.pdf"))
        self.assertFalse(is_allowed_pdf_url("https://drive.google.com:444/file.pdf"))
        self.assertFalse(is_allowed_pdf_url("https://127.0.0.1/private.pdf"))

    def test_redirect_policy_rejects_leaving_google_download_hosts(self):
        with self.assertRaises(ValueError):
            safe_redirect_url("https://drive.google.com/file/d/abc", "http://127.0.0.1/secret")

    def test_watcher_does_not_follow_an_unsafe_redirect(self):
        response = _RedirectResponse("http://169.254.169.254/latest/meta-data")
        session = _Session(response)
        with self.assertRaises(ValueError):
            watcher._safe_session_get(
                session,
                "https://drive.google.com/uc?id=abc",
                headers={"User-Agent": "test"},
            )
        self.assertEqual(session.calls, 1)
        self.assertTrue(response.closed)


if __name__ == "__main__":
    unittest.main()
