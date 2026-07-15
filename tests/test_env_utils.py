import os
import unittest
from unittest.mock import patch

from env_utils import env_float, env_int


class EnvUtilsTests(unittest.TestCase):
    def test_invalid_integer_uses_default(self):
        with patch.dict(os.environ, {"HVHN_TEST_INT": "not-a-number"}):
            self.assertEqual(env_int("HVHN_TEST_INT", 7), 7)

    def test_integer_is_clamped_to_bounds(self):
        with patch.dict(os.environ, {"HVHN_TEST_INT": "999"}):
            self.assertEqual(
                env_int("HVHN_TEST_INT", 7, minimum=1, maximum=20),
                20,
            )

    def test_invalid_float_uses_default_and_applies_bounds(self):
        with patch.dict(os.environ, {"HVHN_TEST_FLOAT": "broken"}):
            self.assertEqual(
                env_float("HVHN_TEST_FLOAT", 2.5, minimum=3.0),
                3.0,
            )


if __name__ == "__main__":
    unittest.main()
