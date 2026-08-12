"""供各个 JSON Schema 复用的格式检查器。"""

from datetime import datetime

from jsonschema import FormatChecker

ISO_DATETIME_FORMAT_CHECKER = FormatChecker()


@ISO_DATETIME_FORMAT_CHECKER.checks("date-time")
def is_iso_datetime_with_timezone(value: object) -> bool:
    """检查 ISO 8601 时间字符串是否包含时区信息。"""
    if not isinstance(value, str):
        return True
    if "T" not in value:
        return False

    try:
        parsed_value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False

    return parsed_value.tzinfo is not None
