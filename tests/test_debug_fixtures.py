from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from kraddr.geo import KrAddrClient, save_fixture


@dataclass
class FakeResponse:
    payload: dict[str, Any] | None = None
    status_code: int = 200
    text: str = "{}"
    content: bytes = b""
    headers: dict[str, str] | None = None
    encoding: str | None = "utf-8"

    def json(self) -> Any:
        return self.payload


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((url, dict(kwargs.get("params") or {})))
        return self.response


def _search_payload() -> dict[str, Any]:
    return {
        "results": {
            "common": {
                "totalCount": "1",
                "currentPage": "1",
                "countPerPage": "10",
                "errorCode": "0",
                "errorMessage": "정상",
            },
            "juso": [
                {
                    "roadAddr": "서울특별시 중구 세종대로 110",
                    "zipNo": "04524",
                    "admCd": "1114010300",
                    "rnMgtSn": "111402005001",
                    "bdMgtSn": "1114010300100310000000001",
                    "rn": "세종대로",
                    "udrtYn": "0",
                    "buldMnnm": "110",
                    "buldSlno": "0",
                }
            ],
        }
    }


def test_debug_search_returns_redacted_run() -> None:
    session = FakeSession(FakeResponse(payload=_search_payload()))
    client = KrAddrClient("secret-key", session=session)

    run = client.debug_search("세종대로 110", add_info=True)

    assert run.ok
    assert run.function == "search"
    assert run.request["query"]["confmKey"] == "<REDACTED>"
    assert run.processed["total_count"] == 1
    assert run.processed["items"][0]["road_address"] == "서울특별시 중구 세종대로 110"


def test_save_fixture_redacts_sensitive_values(tmp_path) -> None:
    path = save_fixture(
        base_dir=tmp_path,
        function_name="search",
        case_name="Search Seoul",
        description="fixture 저장 테스트",
        input_data={"keyword": "서울", "api_key": "secret"},
        request_data={"query": {"confmKey": "secret"}},
        response_data={"body": _search_payload()},
        parsed_result={},
        processed_result={"total_count": 1},
        overwrite=False,
    )

    saved = json.loads(path.read_text(encoding="utf-8"))

    assert path.name == "search-seoul.json"
    assert saved["input"]["api_key"] == "<REDACTED>"
    assert saved["request"]["query"]["confmKey"] == "<REDACTED>"
    with pytest.raises(FileExistsError):
        save_fixture(
            base_dir=tmp_path,
            function_name="search",
            case_name="Search Seoul",
            description="fixture 저장 테스트",
            input_data={},
            request_data={},
            response_data={},
            parsed_result={},
            processed_result={},
        )
