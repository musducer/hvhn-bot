import unittest
from concurrent.futures import TimeoutError as FutureTimeoutError
from unittest.mock import patch

import keep_alive


class KeepAliveWebhookTest(unittest.TestCase):
    def setUp(self):
        self.client = keep_alive.app.test_client()
        keep_alive._mint_attempts.clear()

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

    def test_rejects_formula_like_names_and_invalid_order_codes(self):
        with patch.object(keep_alive, "MINT_SECRET", "secret"):
            response = self.client.post(
                "/mint-invite",
                json={
                    "order_code": "bad code",
                    "name": "=IMPORTXML",
                    "email": "an@example.com",
                    "duration_days": 30,
                },
                headers={"X-HVHN-Secret": "secret"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "invalid_input")

    def test_authenticated_requests_are_rate_limited_before_bot_dispatch(self):
        payload = {
            "order_code": "ORDER1",
            "name": "An",
            "email": "an@example.com",
            "duration_days": 30,
        }
        with patch.object(keep_alive, "MINT_SECRET", "secret"), \
             patch.object(keep_alive, "MINT_RATE_LIMIT", 1):
            first = self.client.post("/mint-invite", json=payload, headers={"X-HVHN-Secret": "secret"})
            second = self.client.post("/mint-invite", json=payload, headers={"X-HVHN-Secret": "secret"})
        self.assertEqual(first.status_code, 503)
        self.assertEqual(second.status_code, 429)

    def test_webhook_responses_do_not_allow_browser_caching(self):
        response = self.client.get("/")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_mint_timeout_returns_promptly_and_cancels_pending_work(self):
        class SlowFuture:
            cancelled = False

            def result(self, timeout):
                raise FutureTimeoutError()

            def cancel(self):
                self.cancelled = True

        class Cog:
            async def mint_invite_for_order(self, *_args):
                return {}

        class Loop:
            def is_running(self):
                return True

        class Bot:
            loop = Loop()

            def get_cog(self, _name):
                return Cog()

        future = SlowFuture()
        payload = {
            "order_code": "ORDER1",
            "name": "An",
            "email": "an@example.com",
            "duration_days": 30,
        }
        def submit(coro, _loop):
            coro.close()
            return future

        with patch.object(keep_alive, "MINT_SECRET", "secret"), \
             patch.object(keep_alive, "_bot", Bot()), \
             patch("keep_alive.asyncio.run_coroutine_threadsafe", side_effect=submit):
            response = self.client.post(
                "/mint-invite", json=payload, headers={"X-HVHN-Secret": "secret"}
            )
        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.get_json()["error"], "mint_timeout")
        self.assertTrue(future.cancelled)


if __name__ == "__main__":
    unittest.main()
