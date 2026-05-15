from __future__ import annotations

from typing import Any


def remove_fields(value: Any, exclude_fields: list[str]) -> Any:
    if isinstance(value, dict):
        return {
            key: remove_fields(item, exclude_fields)
            for key, item in value.items()
            if key not in exclude_fields
        }
    if isinstance(value, list):
        return [remove_fields(item, exclude_fields) for item in value]
    return value


def assert_case(actual: Any, expected: Any, assertion: dict[str, Any]) -> None:
    mode = assertion.get("mode", "snapshot")

    if mode == "snapshot":
        exclude_fields = assertion.get("exclude_fields", [])
        assert remove_fields(actual, exclude_fields) == remove_fields(expected, exclude_fields)
    elif mode == "required_fields":
        for field in assertion.get("required_fields", []):
            assert field in actual
    elif mode == "schema_only":
        assert actual is not None
    elif mode == "count":
        assert actual.get("total_count") == expected.get("total_count")
    else:
        raise ValueError(f"Unknown assertion mode: {mode}")
