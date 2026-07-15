import unittest
from unittest.mock import patch

import keep_alive


class KeepAliveWebhookTest(unittest.TestCase):
    def setUp(self):
        self.client = keep_alive.app.test_client()

    def test_secret_is_required(self):
        with patch.object(keep_alive, "MINT_SECRET", "secret"):
            response = self.client.post("/mint-invite", json={}, headers={"X-HVHN-Secret": "wrong"})
        self.assertEqual(response.status_code, 401)

    def test_invalid_payload_is_rejected_before_bot_dispatch(self):
        payload = {
            "order_code": "ORDER1",
            "name": "An",
            "email": "not-an-email",
            "duration_days": 30,
        }
        with patch.object(keep_alive, "MINT_SECRET", "bí-mật"):
            response = self.client.post(
                "/mint-invite",
                json=payload,
                headers={"X-HVHN-Secret": "bí-mật"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "invalid_input")

    def test_payload_size_is_bounded(self):
        with patch.object(keep_alive, "MINT_SECRET", "secret"):
            response = self.client.post(
                "/mint-invite",
                data=b"x" * (17 * 1024),
                content_type="application/json",
                headers={"X-HVHN-Secret": "secret"},
            )
        self.assertEqual(response.status_code, 413)


if __name__ == "__main__":
    unittest.main()
