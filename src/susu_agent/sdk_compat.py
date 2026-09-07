"""第三方模型适配器与 OpenAI SDK 之间的窄范围兼容处理。"""

import logging


logger = logging.getLogger(__name__)


def ensure_litellm_usage_compatibility() -> bool:
    """允许 LiteLLM 未报告 cache_write_tokens 时按 0 处理。

    openai-agents 0.6.5 的 LiteLLM adapter 只向 Responses API 的
    ``InputTokensDetails`` 传入 ``cached_tokens``，而较新的 openai-python
    将 ``cache_write_tokens`` 设为必填字段。这会让一个已经成功返回的
    第三方模型响应在 usage 归一化阶段失败。

    该补丁只在字段存在且仍为必填时生效；未来 SDK 修复或字段本身已有
    默认值时不做任何修改。
    """
    try:
        from openai.types.responses.response_usage import InputTokensDetails
    except (ImportError, ModuleNotFoundError):
        return False

    field = InputTokensDetails.model_fields.get("cache_write_tokens")
    if field is None or not field.is_required():
        return False

    field.default = 0
    InputTokensDetails.model_rebuild(force=True)
    logger.info(
        "Enabled LiteLLM usage compatibility: missing cache_write_tokens defaults to 0"
    )
    return True

