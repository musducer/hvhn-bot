import inspect
import unittest

from cogs.utilities import Utilities


class ConcurrencyGuardTests(unittest.TestCase):
    def test_anonymous_question_is_claimed_atomically(self):
        source = inspect.getsource(Utilities.answer.callback)
        self.assertIn("WHERE id=$1 AND answered=FALSE RETURNING content", source)
        self.assertIn("SET answered=FALSE", source)


if __name__ == "__main__":
    unittest.main()
