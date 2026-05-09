from __future__ import annotations

import io
import zipfile
from typing import Any

from pykraddr.reverse import (
    NAVIGATION_BUILDING_COLUMNS,
    ReverseGeocoder,
    ReverseGeocodeResult,
    VWorldReverseGeocoder,
    iter_navigation_building_records,
    make_address_point_metadata,
)


def _navigation_line(**overrides: str) -> str:
    values = {
        "jurisdiction_emd_code": "4113510900",
        "sido_name": "Gyeonggi-do",
        "sigungu_name": "Seongnam-si Bundang-gu",
        "eup_myeon_dong_name": "Sampyeong-dong",
        "road_name_code": "411354340327",
        "road_name": "Pangyoyeok-ro",
        "underground_yn": "0",
        "building_main_no": "235",
        "building_sub_no": "0",
        "postal_code": "13494",
        "building_management_number": "4113510900106810000000001",
        "sigungu_building_name": "Alpha Building",
        "building_use": "office",
        "administrative_dong_code": "4113565500",
        "administrative_dong_name": "Sampyeong-dong",
        "ground_floor_count": "10",
        "underground_floor_count": "2",
        "apartment_kind_code": "0",
        "building_count": "1",
        "detail_building_name": "",
        "building_name_history": "",
        "detail_building_name_history": "",
        "residential_yn": "0",
        "building_center_x": "965000.000000",
        "building_center_y": "1943000.000000",
        "entrance_x": "965010.000000",
        "entrance_y": "1943010.000000",
        "sido_name_en": "Gyeonggi-do",
        "sigungu_name_en": "Seongnam-si Bundang-gu",
        "eup_myeon_dong_name_en": "Sampyeong-dong",
        "road_name_en": "Pangyoyeok-ro",
        "eup_myeon_dong_type": "1",
        "change_reason_code": "31",
    }
    values.update(overrides)
    return "|".join(values[column] for column in NAVIGATION_BUILDING_COLUMNS)


def _zip_bytes(name: str, line: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, (line + "\n").encode("utf-8"))
    return buffer.getvalue()


def test_navigation_building_parser_and_address_text() -> None:
    rows = list(
        iter_navigation_building_records(
            _zip_bytes("build_gyeonggi.txt", _navigation_line()),
            encoding="utf-8",
        )
    )

    assert len(rows) == 1
    assert rows[0].building_number == "235"
    assert rows[0].point_xy() == (965010.0, 1943010.0)
    assert rows[0].road_address == (
        "Gyeonggi-do Seongnam-si Bundang-gu Pangyoyeok-ro 235 (Alpha Building)"
    )


def test_navigation_building_parser_falls_back_to_center_point() -> None:
    rows = list(
        iter_navigation_building_records(
            _zip_bytes("build_gyeonggi.txt", _navigation_line(entrance_x="", entrance_y="")),
            encoding="utf-8",
        )
    )

    assert rows[0].point_xy() == (965000.0, 1943000.0)


def test_address_point_metadata_has_point_geometry() -> None:
    metadata = make_address_point_metadata(schema="kraddr", srid=5179)
    table = metadata.tables["kraddr.road_address_points"]

    assert table.c.building_management_number.primary_key
    assert table.c.geom.type.srid == 5179
    assert table.c.geom.type.geometry_type == "POINT"


class FakeVWorldClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    def reverse_geocode_latlon(self, lat: float, lon: float, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"lat": lat, "lon": lon, **kwargs})
        return self.payload


def test_vworld_reverse_geocoder_parses_road_response() -> None:
    client = FakeVWorldClient(
        {
            "response": {
                "status": "OK",
                "result": [
                    {
                        "type": "road",
                        "text": "Gyeonggi-do Seongnam-si Bundang-gu Pangyoyeok-ro 235",
                        "zipcode": "13494",
                    }
                ],
            }
        }
    )
    geocoder = VWorldReverseGeocoder(client=client)

    result = geocoder.reverse_road_address(lon=127.1, lat=37.4)

    assert result is not None
    assert result.source == "vworld"
    assert result.road_address == "Gyeonggi-do Seongnam-si Bundang-gu Pangyoyeok-ro 235"
    assert result.postal_code == "13494"
    assert client.calls[0]["type"] == "both"


class FakeOfflineStore:
    def __init__(self, result: ReverseGeocodeResult | None) -> None:
        self.result = result
        self.calls = 0

    def nearest_road_address(
        self,
        *,
        lon: float,
        lat: float,
        max_distance_m: float | None,
    ) -> ReverseGeocodeResult | None:
        self.calls += 1
        return self.result


def test_reverse_geocoder_prefers_offline_result() -> None:
    offline = FakeOfflineStore(
        ReverseGeocodeResult(
            address_type="road",
            road_address="offline address",
            source="juso_navigation_db",
        )
    )
    vworld = VWorldReverseGeocoder(
        client=FakeVWorldClient({"response": {"status": "OK", "result": []}})
    )
    geocoder = ReverseGeocoder(offline_store=offline, vworld=vworld)

    result = geocoder.reverse_road_address(lon=127.1, lat=37.4)

    assert result is not None
    assert result.source == "juso_navigation_db"
    assert result.road_address == "offline address"
    assert offline.calls == 1
    assert vworld.client.calls == []


def test_reverse_geocoder_uses_vworld_when_offline_misses() -> None:
    offline = FakeOfflineStore(None)
    vworld = VWorldReverseGeocoder(
        client=FakeVWorldClient(
            {
                "response": {
                    "status": "OK",
                    "result": [{"type": "road", "text": "online address"}],
                }
            }
        )
    )
    geocoder = ReverseGeocoder(offline_store=offline, vworld=vworld)

    result = geocoder.reverse_road_address(lon=127.1, lat=37.4)

    assert result is not None
    assert result.source == "vworld"
    assert result.road_address == "online address"
