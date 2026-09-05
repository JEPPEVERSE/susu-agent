"""第三方模型的 JSON 文本输出解析与 Pydantic 校验。"""

import json
import re
from typing import TypeVar

from pydantic import BaseModel


StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


def build_json_output_instruction(model_type: type[BaseModel]) -> str:
    """生成供不支持原生 JSON Schema 的模型使用的输出约束。"""
    schema = json.dumps(
        model_type.model_json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        "\n\n## JSON 文本兼容模式\n\n"
        "当前模型不使用 API 原生结构化输出。你必须只返回一个合法的 "
        "JSON object，不要使用 Markdown 代码围栏，不要添加解释、前言或后记。"
        "所有必填字段都必须出现，字段和值必须符合以下 JSON Schema：\n\n"
        f"{schema}"
    )


def parse_structured_output(
    output: object,
    model_type: type[StructuredModel],
) -> StructuredModel:
    """兼容原生 Pydantic 输出和第三方模型返回的 JSON 字符串。"""
    if isinstance(output, model_type):
        return output
    if not isinstance(output, str):
        raise TypeError(
            f"Expected {model_type.__name__} or JSON text, "
            f"got {type(output).__name__}."
        )

    text = output.strip()
    if not text:
        raise ValueError(f"{model_type.__name__} output is empty.")

    candidates = [text]
    fenced_match = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fenced_match:
        candidates.append(fenced_match.group(1).strip())

    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        candidates.append(text[first_brace : last_brace + 1])

    parse_errors: list[Exception] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            payload = json.loads(candidate)
            return model_type.model_validate(payload)
        except (json.JSONDecodeError, ValueError, TypeError) as error:
            parse_errors.append(error)

    raise ValueError(
        f"Could not parse {model_type.__name__} from model JSON output."
    ) from parse_errors[-1]
