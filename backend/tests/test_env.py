import os
import unittest
from unittest.mock import patch

from utils.env import env_bool


class EnvironmentBooleanTest(unittest.TestCase):
    def test_common_true_values_are_enabled(self):
        for raw in ("1", "true", "yes", "on", " TRUE ", "Yes", " ON "):
            with self.subTest(raw=raw), patch.dict(
                os.environ,
                {"SOCRATE_TEST_FLAG": raw},
                clear=False,
            ):
                self.assertTrue(env_bool("SOCRATE_TEST_FLAG"))

    def test_false_and_unknown_values_are_disabled(self):
        for raw in ("", "0", "false", "no", "off", "unexpected"):
            with self.subTest(raw=raw), patch.dict(
                os.environ,
                {"SOCRATE_TEST_FLAG": raw},
                clear=False,
            ):
                self.assertFalse(env_bool("SOCRATE_TEST_FLAG"))

    def test_missing_value_uses_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(env_bool("SOCRATE_TEST_FLAG"))
            self.assertTrue(env_bool("SOCRATE_TEST_FLAG", default=True))

    def test_present_value_overrides_default(self):
        with patch.dict(
            os.environ,
            {"SOCRATE_TEST_FLAG": "false"},
            clear=False,
        ):
            self.assertFalse(env_bool("SOCRATE_TEST_FLAG", default=True))


if __name__ == "__main__":
    unittest.main()
