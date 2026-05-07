from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from pykraddr import KrAddrAuthError, KrAddrClient


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


def test_search_parses_juso_page_and_additional_fields() -> None:
    session = FakeSession(
        FakeResponse(
            payload={
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
                            "roadAddrPart1": "서울특별시 중구 세종대로 110",
                            "zipNo": "04524",
                            "admCd": "1114010300",
                            "rnMgtSn": "111402005001",
                            "bdMgtSn": "1114010300100310000000001",
                            "rn": "세종대로",
                            "udrtYn": "0",
                            "buldMnnm": "110",
                            "buldSlno": "0",
                            "hstryYn": "N",
                            "relJibun": "",
                            "hemdNm": "명동",
                        }
                    ],
                }
            }
        )
    )
    client = KrAddrClient("test-key", session=session)

    page = client.search("세종대로 110", add_info=True, first_sort="road")

    assert page.total_count == 1
    assert page.items[0].road_address == "서울특별시 중구 세종대로 110"
    assert page.items[0].building_main_no == 110
    assert page.items[0].administrative_dong_name == "명동"
    assert session.calls[0][0].endswith("/addrLinkApi.do")
    assert session.calls[0][1]["resultType"] == "json"
    assert session.calls[0][1]["addInfoYn"] == "Y"


def test_client_requires_key() -> None:
    with pytest.raises(KrAddrAuthError):
        KrAddrClient("")
