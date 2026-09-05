import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from susu_agent.model_config import (
    DEFAULT_AGENT_MODEL,
    resolve_agent_model,
    supports_native_structured_output,
)


class AgentModelConfigTests(unittest.TestCase):
    def test_specific_model_overrides_shared_model(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AGENT_MODEL": "litellm/deepseek/deepseek-chat",
                "TUTOR_MODEL": "gpt-5.4-mini",
            },
        ):
            self.assertEqual(
                resolve_agent_model("TUTOR_MODEL"),
                "gpt-5.4-mini",
            )

    def test_shared_model_is_used_when_specific_model_is_empty(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AGENT_MODEL": "litellm/deepseek/deepseek-chat",
                "TUTOR_MODEL": "",
            },
        ):
            self.assertEqual(
                resolve_agent_model("TUTOR_MODEL"),
                "litellm/deepseek/deepseek-chat",
            )

    def test_code_default_is_used_without_model_variables(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                resolve_agent_model("TUTOR_MODEL"),
                DEFAULT_AGENT_MODEL,
            )

    def test_deepseek_uses_local_structured_output_compatibility(self) -> None:
        self.assertFalse(
            supports_native_structured_output(
                "litellm/deepseek/deepseek-chat"
            )
        )
        self.assertTrue(supports_native_structured_output("gpt-5.4-mini"))


if __name__ == "__main__":
    unittest.main()
