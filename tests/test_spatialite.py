from __future__ import annotations

import io
import zipfile

from kraddr.geo import (
    SpatialiteAddressStore,
    VWorldLikeGeocodeRequest,
    iter_location_summary_records,
    iter_navigation_building_records,
)
from kraddr.geo.reverse import NAVIGATION_BUILDING_COLUMNS
from kraddr.geo.spatialite import LOCATION_SUMMARY_ENTRANCE_COLUMNS


def _zip_bytes(name: str, line: str, *, encoding: str = "cp949") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, (line + "\n").encode(encoding))
    return buffer.getvalue()


def _location_summary_line(**overrides: str) -> str:
    values = {
        "sigungu_code": "11110",
        "entrance_serial_no": "1",
        "legal_dong_code": "1111010100",
        "sido_name": "Seoul",
        "sigungu_name": "Jongno-gu",
        "eup_myeon_dong_name": "Cheongun-dong",
        "road_name_code": "111103100012",
        "road_name": "Jahamun-ro",
        "underground_yn": "0",
        "building_main_no": "96",
        "building_sub_no": "0",
        "building_name": "Pyeongan",
        "postal_code": "03047",
        "building_use": "residence",
        "apartment_kind_code": "0",
        "detail_building_name": "main",
        "entrance_x": "953243.0",
        "entrance_y": "1954023.0",
    }
    values.update(overrides)
    return "|".join(values[column] for column in LOCATION_SUMMARY_ENTRANCE_COLUMNS)


def _navigation_line(**overrides: str) -> str:
    values = {
        "jurisdiction_emd_code": "1111010100",
        "sido_name": "Seoul",
        "sigungu_name": "Jongno-gu",
        "eup_myeon_dong_name": "Cheongun-dong",
        "road_name_code": "111103100012",
        "road_name": "Jahamun-ro",
        "underground_yn": "0",
        "building_main_no": "96",
        "building_sub_no": "0",
        "postal_code": "03047",
        "building_management_number": "1111010100101080014031432",
        "sigungu_building_name": "Pyeongan",
        "building_use": "residence",
        "administrative_dong_code": "1111051500",
        "administrative_dong_name": "Cheongunhyoja-dong",
        "ground_floor_count": "4",
        "underground_floor_count": "0",
        "apartment_kind_code": "2",
        "building_count": "1",
        "detail_building_name": "",
        "building_name_history": "",
        "detail_building_name_history": "",
        "residential_yn": "1",
        "building_center_x": "953247.0",
        "building_center_y": "1954041.0",
        "entrance_x": "953243.2",
        "entrance_y": "1954034.2",
        "sido_name_en": "Seoul",
        "sigungu_name_en": "Jongno-gu",
        "eup_myeon_dong_name_en": "Cheongun-dong",
        "road_name_en": "Jahamun-ro",
        "eup_myeon_dong_type": "1",
        "change_reason_code": "31",
    }
    values.update(overrides)
    return "|".join(values[column] for column in NAVIGATION_BUILDING_COLUMNS)


class FakeVWorldClient:
    def __init__(self) -> None:
        self.coord_calls: list[dict[str, str]] = []
        self.address_calls: list[dict[str, object]] = []

    def get_coord(self, address: str, type: str, **kwargs: str) -> dict[str, object]:
        self.coord_calls.append({"address": address, "type": type, **kwargs})
        return {
            "response": {
                "status": "OK",
                "result": {
                    "text": "fallback road",
                    "point": {"x": "127.1", "y": "37.4"},
                },
            }
        }

    def get_address(self, point, **kwargs: object) -> dict[str, object]:
        self.address_calls.append({"point": point, **kwargs})
        return {
            "response": {
                "status": "OK",
                "result": [
                    {
                        "type": "road",
                        "text": "fallback reverse road",
                        "zipcode": "03047",
                    }
                ],
            }
        }


def test_location_summary_parser_reads_entrance_records() -> None:
    records = list(
        iter_location_summary_records(
            _zip_bytes("entrc_seoul.txt", _location_summary_line()),
            encoding="cp949",
        )
    )

    assert len(records) == 1
    assert records[0].point_xy() == (953243.0, 1954023.0)
    assert records[0].road_address == "Seoul Jongno-gu Jahamun-ro 96 (Pyeongan)"


def test_spatialite_store_prioritizes_location_summary_and_indexes(tmp_path) -> None:
    summary = list(
        iter_location_summary_records(
            _zip_bytes("entrc_seoul.txt", _location_summary_line()),
            encoding="cp949",
        )
    )
    navigation = list(
        iter_navigation_building_records(
            _zip_bytes("match_build_seoul.txt", _navigation_line(), encoding="utf-8"),
            encoding="utf-8",
        )
    )

    with SpatialiteAddressStore(tmp_path / "kraddr_geo.sqlite", load_spatialite=False) as store:
        summary_result = store.load_location_summary_records(summary, source="summary-fixture")
        navigation_result = store.load_navigation_building_records(navigation, source="nav-fixture")
        store.rebuild_search_index()
        candidates = store.get_coord(
            VWorldLikeGeocodeRequest(
                rnMgtSn="111103100012",
                udrtYn="0",
                buldMnnm=96,
                buldSlno=0,
                crs="EPSG:5179",
            )
        )
        reverse = store.get_address(
            {
                "x": 953243.0,
                "y": 1954023.0,
                "crs": "EPSG:5179",
                "max_distance_m": 10,
            }
        )
        postal = store.lookup_postal_code("03047")

        with store.engine.connect() as connection:
            index_names = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA index_list('juso_address_points')"
                )
            }
            road_plan = _query_plan(
                connection,
                """
                EXPLAIN QUERY PLAN
                SELECT *
                FROM juso_address_points
                WHERE road_name_code = '111103100012'
                  AND underground_yn = '0'
                  AND building_main_no = '96'
                  AND building_sub_no = '0'
                """,
            )
            postal_plan = _query_plan(
                connection,
                """
                EXPLAIN QUERY PLAN
                SELECT *
                FROM juso_address_points
                WHERE postal_code = '03047'
                """,
            )
            xy_plan = _query_plan(
                connection,
                """
                EXPLAIN QUERY PLAN
                SELECT *
                FROM juso_address_points
                WHERE x BETWEEN 953200 AND 953300
                  AND y BETWEEN 1954000 AND 1954050
                """,
            )
            listing_plan = _query_plan(
                connection,
                """
                EXPLAIN QUERY PLAN
                SELECT *
                FROM juso_address_points
                ORDER BY
                    source_priority,
                    road_name_code,
                    building_main_no,
                    building_sub_no,
                    point_id
                LIMIT 10
                """,
            )
            road_name_plan = _query_plan(
                connection,
                """
                EXPLAIN QUERY PLAN
                SELECT rowid
                FROM juso_address_points
                WHERE road_name >= 'Jahamun-ro'
                  AND road_name < 'Jahamun-rp'
                LIMIT 10
                """,
            )
            fts_rows = connection.exec_driver_sql(
                """
                SELECT rowid
                FROM juso_address_fts
                WHERE juso_address_fts MATCH ?
                """,
                ('"Jahamun"',),
            ).all()
            search_index_ready = connection.exec_driver_sql(
                """
                SELECT value
                FROM juso_spatial_metadata
                WHERE key = 'address_search_index_ready'
                """
            ).scalar()

    assert summary_result.loaded == 1
    assert navigation_result.loaded == 2
    assert len(candidates) == 3
    assert candidates[0].source == "location_summary"
    assert candidates[0].coordinate_role == "summary_entrance"
    assert reverse is not None
    assert reverse.road_address == "Seoul Jongno-gu Jahamun-ro 96 (Pyeongan)"
    assert len(postal) == 3
    assert "ix_juso_points_road_lookup" in index_names
    assert "ix_juso_points_xy" in index_names
    assert "ix_juso_points_postal_code" in index_names
    assert "ix_juso_points_listing_order" in index_names
    assert "ix_juso_points_postal_lookup" in index_names
    assert "ix_juso_points_road_name" in index_names
    assert "ix_juso_points_parcel_address" in index_names
    assert "ix_juso_points_building_name" in index_names
    assert "ix_juso_points_road_lookup" in road_plan
    assert "ix_juso_points_postal_code" in postal_plan
    assert "ix_juso_points_xy" in xy_plan
    assert "ix_juso_points_listing_order" in listing_plan
    assert "ix_juso_points_road_name" in road_name_plan
    assert len(fts_rows) >= 1
    assert search_index_ready == "fts5_trigram"


def test_spatialite_store_validates_krmois_probe(tmp_path) -> None:
    summary = list(
        iter_location_summary_records(
            _zip_bytes("entrc_seoul.txt", _location_summary_line()),
            encoding="cp949",
        )
    )

    with SpatialiteAddressStore(tmp_path / "kraddr_geo.sqlite", load_spatialite=False) as store:
        store.load_location_summary_records(summary, source="summary-fixture")
        result = store.validate_krmois_probe(
            {
                "source_id": "mois-1",
                "address": "Seoul Jongno-gu Jahamun-ro 96 (Pyeongan)",
                "x": 953243.1,
                "y": 1954023.1,
                "crs": "EPSG:5179",
                "distance_tolerance_m": 2,
            }
        )

    assert result.source_id == "mois-1"
    assert result.address_match is True
    assert result.within_tolerance is True
    assert result.reverse_distance_m is not None
    assert result.reverse_distance_m < 1


def test_spatialite_store_uses_vworld_fallback_when_local_data_misses(tmp_path) -> None:
    client = FakeVWorldClient()

    with SpatialiteAddressStore(
        tmp_path / "kraddr_geo.sqlite",
        load_spatialite=False,
        vworld_client=client,
    ) as store:
        geocoded = store.get_coord({"query": "missing address", "crs": "EPSG:4326"})
        reversed_candidate = store.get_address(
            {"x": 127.1, "y": 37.4, "crs": "EPSG:4326", "max_distance_m": 10}
        )

    assert geocoded[0].source == "vworld"
    assert geocoded[0].road_address == "fallback road"
    assert client.coord_calls[0]["address"] == "missing address"
    assert reversed_candidate is not None
    assert reversed_candidate.source == "vworld"
    assert reversed_candidate.road_address == "fallback reverse road"
    assert client.address_calls[0]["point"] == (127.1, 37.4)


def _query_plan(connection, sql: str) -> str:
    return "\n".join(str(row[-1]) for row in connection.exec_driver_sql(sql))
