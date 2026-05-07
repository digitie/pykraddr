from __future__ import annotations

import io
import zipfile

from pykraddr import RoadNameAddressStore


def _road_line(change_code: str, building_name: str = "청운빌딩") -> str:
    return "|".join(
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
            change_code,
            building_name,
            building_name,
            "",
        ]
    )


def _archive(name: str, lines: list[str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, ("\n".join(lines) + "\n").encode("cp949"))
    return buffer.getvalue()


def test_store_full_load_and_daily_delete(tmp_path) -> None:
    full_path = tmp_path / "RNADDR_KOR_2601.zip"
    full_path.write_bytes(_archive("rnaddrkor_서울특별시.txt", [_road_line("31")]))
    daily_path = tmp_path / "AlterD.JUSUKR.20260102.TH_SGCO_RNADR_MST"
    daily_path.write_bytes(_archive("AlterD.JUSUKR.20260102.TH_SGCO_RNADR_MST", [_road_line("63")]))

    with RoadNameAddressStore(tmp_path / "addr.sqlite") as store:
        counts = store.load_full_archive(full_path)
        daily_counts = store.apply_daily_archive(daily_path)

        assert counts["road"] == 1
        assert daily_counts["road_deleted"] == 1
        assert store.count_road_addresses() == 0
        assert store.get_metadata("last_daily_date") == "2026-01-02"


def test_store_daily_update_upserts_existing_row(tmp_path) -> None:
    full_path = tmp_path / "RNADDR_KOR_2601.zip"
    full_path.write_bytes(_archive("rnaddrkor_서울특별시.txt", [_road_line("31")]))
    daily_path = tmp_path / "AlterD.JUSUKR.20260103.TH_SGCO_RNADR_MST"
    daily_path.write_bytes(
        _archive("AlterD.JUSUKR.20260103.TH_SGCO_RNADR_MST", [_road_line("34", "수정빌딩")])
    )

    with RoadNameAddressStore(tmp_path / "addr.sqlite") as store:
        store.load_full_archive(full_path)
        store.apply_daily_archive(daily_path)
        row = store.get_road_address(
            (
                "1111010100100010000000001",
                "111102005001",
                "0",
                "1",
                "0",
            )
        )

        assert row is not None
        assert row["building_register_name"] == "수정빌딩"
