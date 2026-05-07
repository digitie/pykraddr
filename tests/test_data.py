from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from datetime import date
from typing import Any

from pykraddr.data import (
    RoadNameAddressDataClient,
    iter_related_jibun_records,
    iter_road_name_address_records,
)

ROAD_LINE = "|".join(
    [
        "1111010100100010000000001",
        "1111010100",
        "서울특별시",
        "종로구",
        "청운동",
        "",
        "0",
        "1",
        "0",
        "111102005001",
        "자하문로",
        "0",
        "1",
        "0",
        "1111051500",
        "청운효자동",
        "03048",
        "",
        "20240101",
        "0",
        "31",
        "청운빌딩",
        "청운빌딩",
        "",
    ]
)
JIBUN_LINE = "|".join(
    [
        "1111010100100010000000001",
        "1111010100",
        "서울특별시",
        "종로구",
        "청운동",
        "",
        "0",
        "1",
        "0",
        "111102005001",
        "0",
        "1",
        "0",
        "31",
    ]
)


def _zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("rnaddrkor_서울특별시.txt", (ROAD_LINE + "\n").encode("cp949"))
        archive.writestr("jibun_rnaddrkor_서울특별시.txt", (JIBUN_LINE + "\n").encode("cp949"))
    return buffer.getvalue()


def test_iter_records_from_cp949_zip() -> None:
    content = _zip_bytes()

    road = list(iter_road_name_address_records(content))
    jibun = list(iter_related_jibun_records(content))

    assert road[0].road_name == "자하문로"
    assert road[0].effective_date_value == date(2024, 1, 1)
    assert road[0].primary_key == (
        "1111010100100010000000001",
        "111102005001",
        "0",
        "1",
        "0",
    )
    assert jibun[0].legal_eup_myeon_dong_name == "청운동"


@dataclass
class FakeResponse:
    payload: dict[str, Any]
    status_code: int = 200
    text: str = "{}"
    content: bytes = b""
    headers: dict[str, str] | None = None
    encoding: str | None = "utf-8"

    def json(self) -> Any:
        return self.payload


class FakeSession:
    headers: dict[str, str] = {}

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        return FakeResponse(
            {
                "results": {
                    "allMonthFileList": [
                        {
                            "crtrYm": "202601",
                            "fileTypeNm": "ALLRNADR_KOR",
                            "fileNm": "202601_full.zip",
                            "tmprFileNm": "RNADDR_KOR_2601.zip",
                            "isExist": "Y",
                            "ctpvClsfCd": "00",
                        },
                        {"crtrYm": "202602", "isExist": "N"},
                    ],
                    "dayFileList": [
                        {
                            "crtrYmd": "20260102",
                            "fileNm": "daily.zip",
                            "tmprFileNm": "daily-real.zip",
                            "isExist": "Y",
                        }
                    ],
                    "possibleDataList": [
                        {"APLY_DTA_SE_CD": "22", "RTL_DTA_CRT_CRTR_ENG_NM": "JUSUKRDAY"}
                    ],
                }
            }
        )

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        return FakeResponse({}, content=b"zip-bytes")


def test_latest_full_file_and_download_params(tmp_path) -> None:
    client = RoadNameAddressDataClient(session=FakeSession())

    latest = client.latest_full_file(today=date(2026, 2, 1))
    path = client.download_file(latest, tmp_path)
    daily = client.daily_files(year=2026, month=1)

    assert latest.standard_date == "202601"
    assert latest.request_type == "ALLRNADR_KOR"
    assert path.read_bytes() == b"zip-bytes"
    assert daily[0].request_type == "JUSUKRDAY"
