"""Agent 模型选择与第三方 provider 路由配置。"""

import os
from pathlib import Path

from dotenv import load_dotenv

from susu_agent.sdk_compat import ensure_litellm_usage_compatibility


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

# 必须在任何 Agent 发起模型调用前应用。该函数具有版本检测且可重复调用。
ensure_litellm_usage_compatibility()

DEFAULT_AGENT_MODEL = "gpt-5.4-mini"


def resolve_agent_model(specific_variable: str) -> str:
    """读取专用模型变量，并回退到项目统一模型。

    第三方模型必须把 ``litellm/`` provider 前缀作为显式的 Agent
    model 传给 SDK，不能只依赖 ``OPENAI_DEFAULT_MODEL``。
    """
    specific_model = os.getenv(specific_variable, "").strip()
    shared_model = os.getenv("AGENT_MODEL", "").strip()
    return specific_model or shared_model or DEFAULT_AGENT_MODEL


def supports_native_structured_output(model: str) -> bool:
    """判断模型是否使用 Agents SDK 的原生 JSON Schema 输出。

    DeepSeek 当前会拒绝 SDK 为 ``output_type`` 发送的
    ``response_format=json_schema``，因此改用 JSON 文本并在本地校验。
    """
    return not model.strip().lower().startswith("litellm/deepseek/")
