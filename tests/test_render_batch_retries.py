import unittest
from unittest.mock import patch

import hvhn_batch


class ImmediateFuture:
    def __init__(self, error=None, value=None):
        self.error = error
        self.value = value

    def result(self):
        if self.error:
            raise self.error
        return self.value


class FakePool:
    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def submit(self, _fn, doc, recipient):
        return ImmediateFuture(error=RuntimeError(f"cannot render {doc} for {recipient['email']}"))


class RenderBatchRetryTest(unittest.TestCase):
    def test_exhausted_render_is_not_reported_as_a_successful_batch(self):
        with patch.object(hvhn_batch, "ProcessPoolExecutor", FakePool), \
                patch.object(hvhn_batch, "as_completed", side_effect=lambda futures: list(futures)), \
                patch.object(hvhn_batch.os, "makedirs"), \
                patch.object(hvhn_batch, "out_root", return_value="output"):
            with self.assertRaises(hvhn_batch.RenderBatchError) as caught:
                hvhn_batch.render_batch(
                    ["source.pdf"], [{"name": "An", "email": "an@example.com"}], retries=1,
                )
        self.assertEqual(len(caught.exception.failed_jobs), 1)


if __name__ == "__main__":
    unittest.main()
