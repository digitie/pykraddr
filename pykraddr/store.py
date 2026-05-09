"""Juso TXT 파일을 위한 SQLAlchemy 2 저장소와 일별 증분 갱신 로직."""

from __future__ import annotations

import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    select,
    text,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine, RowMapping

from .data import (
    RELATED_JIBUN_COLUMNS,
    ROAD_NAME_ADDRESS_COLUMNS,
    archive_standard_date,
    iter_related_jibun_records,
    iter_road_name_address_records,
)
from .models import RelatedJibunRecord, RoadNameAddressKoreanRecord

ROAD_TABLE = "road_name_addresses"
JIBUN_TABLE = "related_jibuns"

ROAD_DERIVED_COLUMNS = (
    "building_management_number",
    "sido_code",
    "sigungu_code",
    "eup_myeon_dong_code",
    "ri_code",
    "road_sigungu_code",
    "road_number",
    "pnu",
)
JIBUN_DERIVED_COLUMNS = (
    "sido_code",
    "sigungu_code",
    "eup_myeon_dong_code",
    "ri_code",
    "road_sigungu_code",
    "road_number",
    "pnu",
)


class RoadNameAddressStore:
    """전체분 적재와 일별 증분 갱신을 처리하는 SQLAlchemy 2 저장소.

    기본 백엔드는 SQLite다. 주소 DB를 휴대하기 쉽게 유지하면서도 SQLAlchemy 2
    Core 테이블, 엔진, 트랜잭션, 방언별 upsert를 사용한다.
    """

    def __init__(self, path: str | os.PathLike[str] | Engine) -> None:
        self.path: Path | None = None
        if isinstance(path, Engine):
            self.engine = path
        else:
            self.path = Path(path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(f"sqlite:///{self.path}", future=True)
        self.metadata = _make_metadata()
        self.road_table = self.metadata.tables[ROAD_TABLE]
        self.jibun_table = self.metadata.tables[JIBUN_TABLE]
        self.sync_metadata_table = self.metadata.tables["sync_metadata"]
        self.create_schema()

    def close(self) -> None:
        self.engine.dispose()

    def __enter__(self) -> RoadNameAddressStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def create_schema(self) -> None:
        """테이블을 만들고, 호환용 파생 컬럼과 인덱스를 준비한다."""

        self.metadata.create_all(self.engine)
        if self.engine.dialect.name == "sqlite":
            self._add_missing_sqlite_columns()
        self._create_indexes()

    def reset(self) -> None:
        """적재된 주소 행과 동기화 메타데이터를 모두 삭제한다."""

        with self.engine.begin() as connection:
            connection.execute(self.road_table.delete())
            connection.execute(self.jibun_table.delete())
            connection.execute(self.sync_metadata_table.delete())

    def load_full_archive(
        self,
        archive_path: str | os.PathLike[str],
        *,
        replace: bool = True,
        batch_size: int = 10_000,
    ) -> dict[str, int]:
        """월 전체분 ZIP/TXT를 SQLite에 적재한다.

        ``replace``가 참이면 기존 저장소 내용을 먼저 제거한다.
        """

        if replace:
            self.reset()
        road_count = self.upsert_road_records(
            iter_road_name_address_records(archive_path),
            batch_size=batch_size,
        )
        jibun_count = self.upsert_related_jibun_records(
            iter_related_jibun_records(archive_path),
            batch_size=batch_size,
        )
        self.set_metadata("full_archive_path", str(archive_path))
        inferred = _first_month_or_date(str(archive_path))
        if inferred:
            self.set_metadata("full_standard_date", inferred)
        return {"road": road_count, "jibun": jibun_count}

    def apply_daily_archive(
        self,
        archive_path: str | os.PathLike[str],
        *,
        batch_size: int = 10_000,
    ) -> dict[str, int]:
        """Juso 변동 사유 코드를 사용해 일변동 ZIP/TXT를 반영한다.

        ``31``과 ``34``는 upsert하고, ``63``은 삭제한다.
        """

        road_counts = self.apply_road_changes(
            iter_road_name_address_records(archive_path),
            batch_size=batch_size,
        )
        jibun_counts = self.apply_related_jibun_changes(
            iter_related_jibun_records(archive_path),
            batch_size=batch_size,
        )
        applied_date = archive_standard_date(archive_path)
        if applied_date is not None:
            self.set_metadata("last_daily_date", applied_date.isoformat())
        return {
            "road_upserted": road_counts["upserted"],
            "road_deleted": road_counts["deleted"],
            "jibun_upserted": jibun_counts["upserted"],
            "jibun_deleted": jibun_counts["deleted"],
        }

    def upsert_road_records(
        self,
        records: Iterable[RoadNameAddressKoreanRecord],
        *,
        batch_size: int = 10_000,
    ) -> int:
        return _batched_write(
            records,
            batch_size=batch_size,
            writer=lambda batch: self._upsert_rows(ROAD_TABLE, ROAD_NAME_ADDRESS_COLUMNS, batch),
        )

    def upsert_related_jibun_records(
        self,
        records: Iterable[RelatedJibunRecord],
        *,
        batch_size: int = 10_000,
    ) -> int:
        return _batched_write(
            records,
            batch_size=batch_size,
            writer=lambda batch: self._upsert_rows(JIBUN_TABLE, RELATED_JIBUN_COLUMNS, batch),
        )

    def apply_road_changes(
        self,
        records: Iterable[RoadNameAddressKoreanRecord],
        *,
        batch_size: int = 10_000,
    ) -> dict[str, int]:
        return _apply_changes(
            records,
            batch_size=batch_size,
            upsert=lambda batch: self._upsert_rows(ROAD_TABLE, ROAD_NAME_ADDRESS_COLUMNS, batch),
            delete=lambda batch: self._delete_road_rows(batch),
        )

    def apply_related_jibun_changes(
        self,
        records: Iterable[RelatedJibunRecord],
        *,
        batch_size: int = 10_000,
    ) -> dict[str, int]:
        return _apply_changes(
            records,
            batch_size=batch_size,
            upsert=lambda batch: self._upsert_rows(JIBUN_TABLE, RELATED_JIBUN_COLUMNS, batch),
            delete=lambda batch: self._delete_jibun_rows(batch),
        )

    def count_road_addresses(self) -> int:
        with self.engine.connect() as connection:
            return int(connection.scalar(select(func.count()).select_from(self.road_table)) or 0)

    def count_related_jibuns(self) -> int:
        with self.engine.connect() as connection:
            return int(connection.scalar(select(func.count()).select_from(self.jibun_table)) or 0)

    def get_road_address(
        self,
        primary_key: tuple[str, str, str, str, str],
    ) -> RowMapping | None:
        with self.engine.connect() as connection:
            return (
                connection.execute(
                    select(self.road_table).where(
                        self.road_table.c.road_address_management_number == primary_key[0],
                        self.road_table.c.road_name_code == primary_key[1],
                        self.road_table.c.underground_yn == primary_key[2],
                        self.road_table.c.building_main_no == primary_key[3],
                        self.road_table.c.building_sub_no == primary_key[4],
                    )
                )
                .mappings()
                .first()
            )

    def get_road_addresses_by_management_number(
        self,
        management_number: str,
    ) -> list[RowMapping]:
        """26자리 도로명주소/건물 관리번호에 연결된 도로명주소 행을 반환한다."""

        with self.engine.connect() as connection:
            return list(
                connection.execute(
                    select(self.road_table).where(
                        self.road_table.c.road_address_management_number == management_number
                    )
                )
                .mappings()
                .all()
            )

    def find_road_addresses_by_pnu(self, pnu: str, *, limit: int = 100) -> list[RowMapping]:
        """19자리 PNU 필지 키에 연결된 도로명주소 행을 반환한다."""

        with self.engine.connect() as connection:
            return list(
                connection.execute(
                    select(self.road_table)
                    .where(self.road_table.c.pnu == pnu)
                    .limit(limit)
                )
                .mappings()
                .all()
            )

    def find_related_jibuns_by_pnu(self, pnu: str, *, limit: int = 100) -> list[RowMapping]:
        """19자리 PNU 필지 키에 연결된 관련 지번 행을 반환한다."""

        with self.engine.connect() as connection:
            return list(
                connection.execute(
                    select(self.jibun_table)
                    .where(self.jibun_table.c.pnu == pnu)
                    .limit(limit)
                )
                .mappings()
                .all()
            )

    def get_metadata(self, key: str) -> str | None:
        with self.engine.connect() as connection:
            value = connection.scalar(
                select(self.sync_metadata_table.c.value).where(
                    self.sync_metadata_table.c.key == key
                )
            )
        return str(value) if value is not None else None

    def set_metadata(self, key: str, value: str) -> None:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self.engine.begin() as connection:
            self._upsert_metadata(connection, key, value)
            self._upsert_metadata(connection, "updated_at", now)

    def _upsert_rows(self, table: str, columns: tuple[str, ...], rows: list[Any]) -> int:
        if not rows:
            return 0
        target = self.metadata.tables[table]
        values = [_row_values(table, columns, row) for row in rows]
        statement = sqlite_insert(target).values(values)
        primary_key_columns = set(target.primary_key.columns.keys())
        update_values = {
            column: getattr(statement.excluded, column)
            for column in target.columns.keys()
            if column not in primary_key_columns
        }
        with self.engine.begin() as connection:
            connection.execute(
                statement.on_conflict_do_update(
                    index_elements=[column.name for column in target.primary_key.columns],
                    set_=update_values,
                )
            )
        return len(rows)

    def _delete_road_rows(self, rows: list[RoadNameAddressKoreanRecord]) -> int:
        if not rows:
            return 0
        with self.engine.begin() as connection:
            for row in rows:
                connection.execute(
                    self.road_table.delete().where(
                        self.road_table.c.road_address_management_number == row.primary_key[0],
                        self.road_table.c.road_name_code == row.primary_key[1],
                        self.road_table.c.underground_yn == row.primary_key[2],
                        self.road_table.c.building_main_no == row.primary_key[3],
                        self.road_table.c.building_sub_no == row.primary_key[4],
                    )
                )
        return len(rows)

    def _delete_jibun_rows(self, rows: list[RelatedJibunRecord]) -> int:
        if not rows:
            return 0
        with self.engine.begin() as connection:
            for row in rows:
                connection.execute(
                    self.jibun_table.delete().where(
                        self.jibun_table.c.road_address_management_number == row.primary_key[0],
                        self.jibun_table.c.legal_dong_code == row.primary_key[1],
                        self.jibun_table.c.mountain_yn == row.primary_key[2],
                        self.jibun_table.c.lot_main_no == row.primary_key[3],
                        self.jibun_table.c.lot_sub_no == row.primary_key[4],
                    )
                )
        return len(rows)

    def _upsert_metadata(self, connection: Any, key: str, value: str) -> None:
        statement = sqlite_insert(self.sync_metadata_table).values(key=key, value=value)
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=[self.sync_metadata_table.c.key],
                set_={"value": statement.excluded.value},
            )
        )

    def _add_missing_sqlite_columns(self) -> None:
        """이전 버전이 만든 DB를 열 때 누락된 파생 컬럼을 추가한다."""

        tables = (self.road_table, self.jibun_table)
        preparer = self.engine.dialect.identifier_preparer
        with self.engine.begin() as connection:
            for table in tables:
                existing = {
                    str(row["name"])
                    for row in connection.execute(
                        text(f"PRAGMA table_info({preparer.quote(table.name)})")
                    ).mappings()
                }
                for column in table.columns:
                    if column.name in existing:
                        continue
                    connection.execute(
                        text(
                            "ALTER TABLE "
                            f"{preparer.quote(table.name)} "
                            f"ADD COLUMN {preparer.quote(column.name)} VARCHAR NOT NULL DEFAULT ''"
                        )
                    )

    def _create_indexes(self) -> None:
        with self.engine.begin() as connection:
            for table in (self.road_table, self.jibun_table):
                for index in table.indexes:
                    index.create(connection, checkfirst=True)

    def backfill_derived_columns(self) -> None:
        """이전 버전으로 적재한 DB의 코드/PNU 파생 컬럼을 채운다.

        새 전체분/일변동 적재는 upsert 중에 이 컬럼들을 채운다. 이 헬퍼는
        월 전체분을 다시 적재하지 않고 기존 SQLite DB를 업그레이드할 때 유용하다.
        """

        if self.engine.dialect.name != "sqlite":
            raise NotImplementedError("backfill_derived_columns는 현재 SQLite만 지원합니다")
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"""
                    UPDATE {ROAD_TABLE}
                    SET
                        building_management_number = road_address_management_number,
                        sido_code = substr(legal_dong_code, 1, 2),
                        sigungu_code = substr(legal_dong_code, 1, 5),
                        eup_myeon_dong_code = substr(legal_dong_code, 1, 8),
                        ri_code = substr(legal_dong_code, 9, 2),
                        road_sigungu_code = substr(road_name_code, 1, 5),
                        road_number = substr(road_name_code, 6),
                        pnu = legal_dong_code || mountain_yn
                              || printf('%04d', CAST(lot_main_no AS INTEGER))
                              || printf('%04d', CAST(lot_sub_no AS INTEGER))
                    """
                )
            )
            connection.execute(
                text(
                    f"""
                    UPDATE {JIBUN_TABLE}
                    SET
                        sido_code = substr(legal_dong_code, 1, 2),
                        sigungu_code = substr(legal_dong_code, 1, 5),
                        eup_myeon_dong_code = substr(legal_dong_code, 1, 8),
                        ri_code = substr(legal_dong_code, 9, 2),
                        road_sigungu_code = substr(road_name_code, 1, 5),
                        road_number = substr(road_name_code, 6),
                        pnu = legal_dong_code || mountain_yn
                              || printf('%04d', CAST(lot_main_no AS INTEGER))
                              || printf('%04d', CAST(lot_sub_no AS INTEGER))
                    """
                )
            )


def _make_metadata() -> MetaData:
    metadata = MetaData()
    Table(
        ROAD_TABLE,
        metadata,
        *[
            Column(
                name,
                String,
                primary_key=name
                in {
                    "road_address_management_number",
                    "road_name_code",
                    "underground_yn",
                    "building_main_no",
                    "building_sub_no",
                },
                nullable=False,
                default="",
            )
            for name in (*ROAD_NAME_ADDRESS_COLUMNS, *ROAD_DERIVED_COLUMNS)
        ],
        Index("ix_road_name_addresses_mgmt_no", "road_address_management_number"),
        Index("ix_road_name_addresses_building_mgmt", "building_management_number"),
        Index("ix_road_name_addresses_legal_dong", "legal_dong_code"),
        Index("ix_road_name_addresses_sigungu", "sigungu_code"),
        Index("ix_road_name_addresses_emd", "eup_myeon_dong_code"),
        Index("ix_road_name_addresses_road_name", "road_name_code"),
        Index(
            "ix_road_name_addresses_road_lookup",
            "road_name_code",
            "underground_yn",
            "building_main_no",
            "building_sub_no",
        ),
        Index("ix_road_name_addresses_pnu", "pnu"),
        Index("ix_road_name_addresses_postal_code", "postal_code"),
    )
    Table(
        JIBUN_TABLE,
        metadata,
        *[
            Column(
                name,
                String,
                primary_key=name
                in {
                    "road_address_management_number",
                    "legal_dong_code",
                    "mountain_yn",
                    "lot_main_no",
                    "lot_sub_no",
                },
                nullable=False,
                default="",
            )
            for name in (*RELATED_JIBUN_COLUMNS, *JIBUN_DERIVED_COLUMNS)
        ],
        Index("ix_related_jibuns_road_mgmt", "road_address_management_number"),
        Index("ix_related_jibuns_legal_dong", "legal_dong_code"),
        Index(
            "ix_related_jibuns_legal_lot",
            "legal_dong_code",
            "mountain_yn",
            "lot_main_no",
            "lot_sub_no",
        ),
        Index("ix_related_jibuns_sigungu", "sigungu_code"),
        Index("ix_related_jibuns_pnu", "pnu"),
    )
    Table(
        "sync_metadata",
        metadata,
        Column("key", String, primary_key=True),
        Column("value", String, nullable=False),
        Column("updated_at", DateTime(timezone=True), default=lambda: datetime.now(UTC)),
    )
    return metadata


def _batched_write(records: Iterable[Any], *, batch_size: int, writer: Any) -> int:
    count = 0
    batch: list[Any] = []
    for record in records:
        batch.append(record)
        if len(batch) >= batch_size:
            count += writer(batch)
            batch = []
    if batch:
        count += writer(batch)
    return count


def _apply_changes(
    records: Iterable[Any],
    *,
    batch_size: int,
    upsert: Any,
    delete: Any,
) -> dict[str, int]:
    upserted = 0
    deleted = 0
    upsert_batch: list[Any] = []
    delete_batch: list[Any] = []
    for record in records:
        code = str(record.change_reason_code).strip()
        if code == "63":
            delete_batch.append(record)
            if len(delete_batch) >= batch_size:
                deleted += delete(delete_batch)
                delete_batch = []
            continue
        upsert_batch.append(record)
        if len(upsert_batch) >= batch_size:
            upserted += upsert(upsert_batch)
            upsert_batch = []
    if upsert_batch:
        upserted += upsert(upsert_batch)
    if delete_batch:
        deleted += delete(delete_batch)
    return {"upserted": upserted, "deleted": deleted}


def _first_month_or_date(text: str) -> str | None:
    digits = "".join(char if char.isdigit() else " " for char in text).split()
    for part in digits:
        if len(part) >= 8:
            return f"{part[:4]}-{part[4:6]}-{part[6:8]}"
        if len(part) >= 6:
            return f"{part[:4]}-{part[4:6]}"
    return None


def _row_values(table: str, columns: tuple[str, ...], row: Any) -> dict[str, str]:
    values = {column: _clean(getattr(row, column)) for column in columns}
    if table == ROAD_TABLE:
        values.update(_legal_code_values(values["legal_dong_code"]))
        values.update(_road_code_values(values["road_name_code"]))
        values["building_management_number"] = values["road_address_management_number"]
        values["pnu"] = _pnu(
            values["legal_dong_code"],
            values["mountain_yn"],
            values["lot_main_no"],
            values["lot_sub_no"],
        )
    elif table == JIBUN_TABLE:
        values.update(_legal_code_values(values["legal_dong_code"]))
        values.update(_road_code_values(values["road_name_code"]))
        values["pnu"] = _pnu(
            values["legal_dong_code"],
            values["mountain_yn"],
            values["lot_main_no"],
            values["lot_sub_no"],
        )
    return values


def _legal_code_values(legal_dong_code: str) -> dict[str, str]:
    return {
        "sido_code": legal_dong_code[:2],
        "sigungu_code": legal_dong_code[:5],
        "eup_myeon_dong_code": legal_dong_code[:8],
        "ri_code": legal_dong_code[8:10],
    }


def _road_code_values(road_name_code: str) -> dict[str, str]:
    return {
        "road_sigungu_code": road_name_code[:5],
        "road_number": road_name_code[5:12],
    }


def _pnu(
    legal_dong_code: str,
    mountain_yn: str,
    lot_main_no: str,
    lot_sub_no: str,
) -> str:
    return (
        legal_dong_code
        + (mountain_yn or "0")[:1]
        + _zero_pad_number(lot_main_no, 4)
        + _zero_pad_number(lot_sub_no, 4)
    )


def _zero_pad_number(value: str, width: int) -> str:
    text_value = _clean(value)
    if not text_value:
        return "0" * width
    return text_value.zfill(width)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
