import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from openai.types.responses.response_usage import InputTokensDetails

from susu_agent.sdk_compat import ensure_litellm_usage_compatibility


class SdkCompatibilityTests(unittest.TestCase):
    def test_missing_cache_write_tokens_defaults_to_zero(self) -> None:
        ensure_litellm_usage_compatibility()

        details = InputTokensDetails(cached_tokens=7)

        self.assertEqual(details.cached_tokens, 7)
        self.assertEqual(details.cache_write_tokens, 0)

    def test_compatibility_patch_is_idempotent(self) -> None:
        ensure_litellm_usage_compatibility()
        changed_again = ensure_litellm_usage_compatibility()

        self.assertFalse(changed_again)

