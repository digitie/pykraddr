"""SQLAlchemy 2 storage and daily incremental update logic for Juso TXT files."""

from __future__ import annotations

import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Column, DateTime, Index, MetaData, String, Table, create_engine, func, select
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


class RoadNameAddressStore:
    """SQLAlchemy 2 store for full loads and daily incremental Juso address updates.

    The default backend is SQLite, which keeps the address DB portable while still
    using SQLAlchemy 2 Core tables, engines, transactions, and dialect upserts.
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
        """Create tables and indexes when they do not exist."""

        self.metadata.create_all(self.engine)

    def reset(self) -> None:
        """Delete all loaded address rows and sync metadata."""

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
        """Load a full monthly ZIP/TXT into SQLite.

        When ``replace`` is true the previous store contents are removed first.
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
        """Apply a daily change ZIP/TXT using Juso movement reason codes.

        ``31`` and ``34`` are upserted. ``63`` is deleted.
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
        values = [{column: getattr(row, column) for column in columns} for row in rows]
        statement = sqlite_insert(target).values(values)
        update_values = {
            column: getattr(statement.excluded, column)
            for column in columns
            if column not in set(target.primary_key.columns.keys())
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
            for name in ROAD_NAME_ADDRESS_COLUMNS
        ],
        Index("ix_road_name_addresses_legal_dong", "legal_dong_code"),
        Index("ix_road_name_addresses_road_name", "road_name_code"),
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
            for name in RELATED_JIBUN_COLUMNS
        ],
        Index("ix_related_jibuns_road_mgmt", "road_address_management_number"),
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
