"""debug 실행 결과를 pytest replay용 fixture JSON으로 저장한다."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .debug import jsonable, redact_sensitive

DEFAULT_ASSERTION = {
    "mode": "snapshot",
    "exclude_fields": ["fetched_at", "request_id", "updated_at"],
    "required_fields": [],
}


def save_fixture(
    *,
    base_dir: str | Path,
    function_name: str,
    case_name: str,
    description: str,
    input_data: dict[str, Any],
    request_data: dict[str, Any],
    response_data: dict[str, Any],
    parsed_result: Any,
    processed_result: Any,
    assertion: dict[str, Any] | None = None,
    library_version: str | None = None,
    overwrite: bool = False,
) -> Path:
    """하나의 실행 결과를 tests/fixtures/{function}/{case}.json 형식으로 저장한다."""

    safe_case_name = slugify(case_name)
    fixture_dir = Path(base_dir) / function_name
    fixture_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = fixture_dir / f"{safe_case_name}.json"

    if fixture_path.exists() and not overwrite:
        raise FileExistsError(f"Fixture already exists: {fixture_path}")

    fixture = {
        "name": safe_case_name,
        "function": function_name,
        "description": description,
        "input": redact_sensitive(jsonable(input_data)),
        "request": redact_sensitive(jsonable(request_data)),
        "response": redact_sensitive(jsonable(response_data)),
        "parsed": jsonable(parsed_result),
        "processed": jsonable(processed_result),
        "assertion": assertion or dict(DEFAULT_ASSERTION),
        "meta": {
            "created_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
            "library_version": library_version,
            "source": "debug_ui",
        },
    }

    with fixture_path.open("w", encoding="utf-8") as file:
        json.dump(fixture, file, ensure_ascii=False, indent=2)
        file.write("\n")

    return fixture_path


def slugify(value: str) -> str:
    """fixture 파일명으로 쓸 수 있는 안전한 이름을 만든다."""

    slug = re.sub(r"[^\w가-힣.-]+", "-", value.strip().lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-_.")
    return slug or "case"
