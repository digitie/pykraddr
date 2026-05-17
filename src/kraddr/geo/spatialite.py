"""SQLite/SpatiaLite store for Juso geocoding datasets."""

from __future__ import annotations

import json
import math
import os
import struct
import tempfile
import zipfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    bindparam,
    create_engine,
    func,
    select,
    text,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine, RowMapping

from .data import _content_bytes, _iter_decoded_lines, _iter_text_members, _split_line
from .dto import (
    CoordinateCandidate,
    KRMoisAddressProbe,
    KRMoisAddressValidationResult,
    PostalCodeLookupRequest,
    VWorldLikeGeocodeRequest,
    VWorldLikeReverseGeocodeRequest,
)
from .reverse import (
    NavigationBuildingRecord,
    ReverseGeocodeResult,
    iter_navigation_building_records,
)

SPATIALITE_ADDRESS_POINT_TABLE = "juso_address_points"
SPATIALITE_ADDRESS_SEARCH_TABLE = "juso_address_fts"
SPATIALITE_BOUNDARY_TABLE = "juso_boundary_polygons"
SPATIALITE_METADATA_TABLE = "juso_spatial_metadata"
DEFAULT_SRID = 5179
SEARCH_INDEX_READY_METADATA_KEY = "address_search_index_ready"

LOCATION_SUMMARY_ENTRANCE_COLUMNS = (
    "sigungu_code",
    "entrance_serial_no",
    "legal_dong_code",
    "sido_name",
    "sigungu_name",
    "eup_myeon_dong_name",
    "road_name_code",
    "road_name",
    "underground_yn",
    "building_main_no",
    "building_sub_no",
    "building_name",
    "postal_code",
    "building_use",
    "apartment_kind_code",
    "detail_building_name",
    "entrance_x",
    "entrance_y",
)
NAVIGATION_ROAD_SECTION_ENTRANCE_COLUMNS = (
    "sigungu_code",
    "entrance_serial_no",
    "road_name_code",
    "underground_yn",
    "building_main_no",
    "building_sub_no",
    "legal_dong_code",
    "entrance_type_code",
    "x",
    "y",
    "reserved",
)


def _freeze(raw: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(raw or {}))


@dataclass(frozen=True, slots=True)
class LocationSummaryEntranceRecord:
    """One row from the Juso location summary entrance dataset."""

    sigungu_code: str
    entrance_serial_no: str
    legal_dong_code: str
    sido_name: str
    sigungu_name: str
    eup_myeon_dong_name: str
    road_name_code: str
    road_name: str
    underground_yn: str
    building_main_no: str
    building_sub_no: str
    building_name: str
    postal_code: str
    building_use: str
    apartment_kind_code: str
    detail_building_name: str
    entrance_x: str
    entrance_y: str
    source_member: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw", _freeze(self.raw))

    @property
    def source_key(self) -> str:
        parts = (
            self.sigungu_code,
            self.entrance_serial_no,
            self.road_name_code,
            self.underground_yn,
            self.building_main_no,
            self.building_sub_no,
        )
        return ":".join(parts)

    @property
    def building_number(self) -> str:
        main = _strip_number(self.building_main_no)
        sub = _strip_number(self.building_sub_no)
        return main if sub in {"", "0"} else f"{main}-{sub}"

    @property
    def road_address(self) -> str:
        parts = [self.sido_name, self.sigungu_name, self.road_name, self.building_number]
        address = " ".join(part for part in parts if part)
        name = self.building_name or self.detail_building_name
        return f"{address} ({name})" if name else address

    def point_xy(self) -> tuple[float, float] | None:
        return _xy(self.entrance_x, self.entrance_y)


@dataclass(frozen=True, slots=True)
class NavigationRoadSectionEntranceRecord:
    """Road-section entrance row from the navigation database."""

    sigungu_code: str
    entrance_serial_no: str
    road_name_code: str
    underground_yn: str
    building_main_no: str
    building_sub_no: str
    legal_dong_code: str
    entrance_type_code: str
    x: str
    y: str
    reserved: str = ""
    source_member: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw", _freeze(self.raw))

    @property
    def source_key(self) -> str:
        parts = (
            self.sigungu_code,
            self.entrance_serial_no,
            self.road_name_code,
            self.underground_yn,
            self.building_main_no,
            self.building_sub_no,
            self.legal_dong_code,
        )
        return ":".join(parts)

    def point_xy(self) -> tuple[float, float] | None:
        return _xy(self.x, self.y)


@dataclass(frozen=True, slots=True)
class SpatialiteLoadResult:
    """Summary returned after loading rows into the SpatiaLite store."""

    loaded: int = 0
    skipped: int = 0
    deleted: int = 0


@dataclass(frozen=True, slots=True)
class BoundarySpatialiteLoadResult:
    """Summary returned after loading boundary polygons."""

    loaded: int = 0
    skipped: int = 0
    files: tuple[str, ...] = ()


class SpatialiteAddressStore:
    """SQLite store that optionally enables SpatiaLite geometry columns.

    The tables keep plain ``x``/``y`` columns and WKT/WKB geometry payloads even when the
    SpatiaLite extension is unavailable. When the extension can be loaded, geometry
    columns and RTree spatial indexes are added in-place.
    """

    def __init__(
        self,
        path_or_engine: str | os.PathLike[str] | Engine,
        *,
        srid: int = DEFAULT_SRID,
        load_spatialite: bool = True,
        vworld_client: Any | None = None,
        vworld_api_key: str | None = None,
        vworld_domain: str | None = None,
        vworld_timeout: float = 10.0,
        echo: bool = False,
    ) -> None:
        self.srid = srid
        self.spatialite_enabled = False
        self.vworld_client = vworld_client or _make_vworld_client(
            api_key=vworld_api_key,
            domain=vworld_domain,
            timeout=vworld_timeout,
        )
        self.path: Path | None = None
        if isinstance(path_or_engine, Engine):
            self.engine = path_or_engine
        else:
            self.path = Path(path_or_engine)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(f"sqlite:///{self.path}", future=True, echo=echo)
        self.metadata = make_spatialite_metadata()
        self.point_table = self.metadata.tables[SPATIALITE_ADDRESS_POINT_TABLE]
        self.boundary_table = self.metadata.tables[SPATIALITE_BOUNDARY_TABLE]
        self.metadata_table = self.metadata.tables[SPATIALITE_METADATA_TABLE]
        self.create_schema(load_spatialite=load_spatialite)

    def close(self) -> None:
        self.engine.dispose()

    def __enter__(self) -> SpatialiteAddressStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def create_schema(self, *, load_spatialite: bool = True) -> None:
        self.metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            if self.engine.dialect.name == "sqlite":
                _set_sqlite_pragmas(connection)
                _ensure_sqlite_performance_indexes(connection)
                _ensure_sqlite_search_index(connection)
                if load_spatialite:
                    self.spatialite_enabled = _try_enable_spatialite(connection, self.srid)
                    if self.spatialite_enabled:
                        self.spatialite_enabled = _ensure_spatialite_geometry(connection, self.srid)

    def reset(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(self.point_table.delete())
            connection.execute(self.boundary_table.delete())
            connection.execute(self.metadata_table.delete())

    def set_metadata(self, key: str, value: str) -> None:
        now = datetime.now(UTC)
        stmt = sqlite_insert(self.metadata_table).values(
            key=key,
            value=value,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["key"],
            set_={"value": stmt.excluded.value, "updated_at": stmt.excluded.updated_at},
        )
        with self.engine.begin() as connection:
            connection.execute(stmt)

    def load_navigation_building_archive(
        self,
        path: str | Path | bytes,
        *,
        replace: bool = False,
        batch_size: int = 10_000,
        source: str | None = None,
    ) -> SpatialiteLoadResult:
        return self.load_navigation_building_records(
            iter_navigation_building_records(path),
            replace=replace,
            batch_size=batch_size,
            source=source or _source_name(path),
        )

    def load_navigation_building_records(
        self,
        records: Iterable[NavigationBuildingRecord],
        *,
        replace: bool = False,
        batch_size: int = 10_000,
        source: str = "juso_navigation_db",
    ) -> SpatialiteLoadResult:
        loaded = 0
        skipped = 0
        batch: list[dict[str, Any]] = []
        if replace:
            self.delete_source(source)
        for record in records:
            rows = _navigation_address_point_rows(record, source=source, srid=self.srid)
            if not rows:
                skipped += 1
                continue
            batch.extend(rows)
            if len(batch) >= batch_size:
                self._upsert_point_rows(batch)
                loaded += len(batch)
                batch = []
        if batch:
            self._upsert_point_rows(batch)
            loaded += len(batch)
        self.set_metadata("last_navigation_source", source)
        return SpatialiteLoadResult(loaded=loaded, skipped=skipped)

    def load_location_summary_archive(
        self,
        path: str | Path | bytes,
        *,
        replace: bool = False,
        encoding: str | None = None,
        batch_size: int = 10_000,
        source: str | None = None,
    ) -> SpatialiteLoadResult:
        return self.load_location_summary_records(
            iter_location_summary_records(path, encoding=encoding),
            replace=replace,
            batch_size=batch_size,
            source=source or _source_name(path),
        )

    def load_location_summary_records(
        self,
        records: Iterable[LocationSummaryEntranceRecord],
        *,
        replace: bool = False,
        batch_size: int = 10_000,
        source: str = "juso_location_summary_db",
    ) -> SpatialiteLoadResult:
        loaded = 0
        skipped = 0
        batch: list[dict[str, Any]] = []
        if replace:
            self.delete_source(source)
        for record in records:
            row = _location_summary_address_point_row(record, source=source, srid=self.srid)
            if row is None:
                skipped += 1
                continue
            batch.append(row)
            if len(batch) >= batch_size:
                self._upsert_point_rows(batch)
                loaded += len(batch)
                batch = []
        if batch:
            self._upsert_point_rows(batch)
            loaded += len(batch)
        self.set_metadata("last_location_summary_source", source)
        return SpatialiteLoadResult(loaded=loaded, skipped=skipped)

    def load_navigation_road_section_entrance_archive(
        self,
        path: str | Path | bytes,
        *,
        replace: bool = False,
        encoding: str | None = None,
        batch_size: int = 10_000,
        source: str | None = None,
    ) -> SpatialiteLoadResult:
        return self.load_navigation_road_section_entrance_records(
            iter_navigation_road_section_entrance_records(path, encoding=encoding),
            replace=replace,
            batch_size=batch_size,
            source=source or _source_name(path),
        )

    def load_navigation_road_section_entrance_records(
        self,
        records: Iterable[NavigationRoadSectionEntranceRecord],
        *,
        replace: bool = False,
        batch_size: int = 10_000,
        source: str = "juso_navigation_road_section_entrance",
    ) -> SpatialiteLoadResult:
        loaded = 0
        skipped = 0
        batch: list[dict[str, Any]] = []
        if replace:
            self.delete_source(source)
        for record in records:
            row = _road_section_entrance_point_row(record, source=source, srid=self.srid)
            if row is None:
                skipped += 1
                continue
            batch.append(row)
            if len(batch) >= batch_size:
                self._upsert_point_rows(batch)
                loaded += len(batch)
                batch = []
        if batch:
            self._upsert_point_rows(batch)
            loaded += len(batch)
        self.set_metadata("last_road_section_entrance_source", source)
        return SpatialiteLoadResult(loaded=loaded, skipped=skipped)

    def load_boundary_zips(
        self,
        paths: Sequence[str | Path],
        *,
        replace: bool = False,
        encoding: str = "cp949",
        source_system: str = "juso_boundary_shapes",
    ) -> BoundarySpatialiteLoadResult:
        if replace:
            with self.engine.begin() as connection:
                connection.execute(self.boundary_table.delete())
        loaded = 0
        skipped = 0
        files: list[str] = []
        for path in paths:
            frame = read_boundary_zip(path, srid=self.srid, encoding=encoding)
            source_file = Path(path).name
            files.append(source_file)
            rows: list[dict[str, Any]] = []
            for data in frame.to_dict("records"):
                geom = data.get("geom")
                if geom is None or geom.is_empty:
                    skipped += 1
                    continue
                source_layer = str(data.get("__source_layer") or "unknown")
                boundary_level = str(data.get("__boundary_level") or boundary_level_from_path(path))
                raw_source_code = _boundary_source_code(data, source_layer=source_layer)
                region_code = _clean_boundary_value(data.get("__source_region_code"))
                source_row = _clean_boundary_value(data.get("__source_row"))
                source_parts = [part for part in (region_code, raw_source_code, source_row) if part]
                source_code = ":".join(source_parts)
                rows.append(
                    {
                        "source_system": source_system,
                        "source_file": f"{source_file}:{data.get('__source_shp', '')}".rstrip(":"),
                        "source_layer": source_layer,
                        "source_code": source_code,
                        "source_name": _boundary_source_name(data),
                        "legal_dong_code": raw_source_code if len(raw_source_code) == 10 else None,
                        "boundary_level": boundary_level,
                        "mapping_status": "unverified",
                        "srid": self.srid,
                        "geom_wkt": geom.wkt,
                        "geom_wkb": bytes(geom.wkb),
                        "loaded_at": datetime.now(UTC),
                        "raw_json": _jsonable_mapping(data, skip={"geom"}),
                    }
                )
            self._upsert_boundary_rows(rows)
            loaded += len(rows)
        self.set_metadata("last_boundary_sources", json.dumps(files, ensure_ascii=False))
        return BoundarySpatialiteLoadResult(loaded=loaded, skipped=skipped, files=tuple(files))

    def delete_source(self, source: str) -> int:
        with self.engine.begin() as connection:
            result = connection.execute(
                self.point_table.delete().where(self.point_table.c.source == source)
            )
            return int(result.rowcount or 0)

    def count_points(self) -> int:
        with self.engine.connect() as connection:
            return int(connection.scalar(select(func.count()).select_from(self.point_table)) or 0)

    def rebuild_search_index(self) -> None:
        """Build the trigram search index for fast contains-style address search."""

        with self.engine.begin() as connection:
            _ensure_sqlite_search_index(connection)
            connection.execute(
                text(
                    f"""
                    INSERT INTO {SPATIALITE_ADDRESS_SEARCH_TABLE}
                        ({SPATIALITE_ADDRESS_SEARCH_TABLE})
                    VALUES ('rebuild')
                    """
                )
            )
            _mark_search_index_ready(connection)

    def get_coord(
        self,
        request: VWorldLikeGeocodeRequest | Mapping[str, Any],
        *,
        fallback: bool = True,
    ) -> list[CoordinateCandidate]:
        dto = _coerce_geocode_request(request)
        if dto.road_name_code and dto.building_main_no is not None:
            rows = self._query_by_road_key(dto)
        elif dto.query:
            rows = self._query_by_address_text(dto.query, limit=dto.limit)
        else:
            return []
        candidates = [
            _candidate_in_crs(_candidate_from_row(row), dto.crs) for row in rows[: dto.limit]
        ]
        if candidates or not fallback or self.vworld_client is None or not dto.query:
            return candidates
        return _vworld_get_coord_candidates(self.vworld_client, dto)

    def get_address(
        self,
        request: VWorldLikeReverseGeocodeRequest | Mapping[str, Any],
        *,
        fallback: bool = True,
    ) -> CoordinateCandidate | None:
        dto = _coerce_reverse_request(request)
        x, y = _transform_xy(dto.x, dto.y, dto.crs, f"EPSG:{self.srid}")
        result = self.nearest_road_address_xy(x=x, y=y, max_distance_m=dto.max_distance_m)
        if result is None:
            if fallback and self.vworld_client is not None:
                return _vworld_get_address_candidate(self.vworld_client, dto)
            return None
        return _candidate_in_crs(
            CoordinateCandidate(
                x=result.x or x,
                y=result.y or y,
                crs="EPSG:5179",
                road_address=result.road_address,
                parcel_address=result.parcel_address,
                postal_code=result.postal_code,
                legal_dong_code=result.legal_dong_code,
                road_name_code=result.road_name_code,
                building_management_number=result.building_management_number,
                building_name=result.building_name,
                source=result.source,
                distance_m=result.distance_m,
                raw=dict(result.raw),
            ),
            dto.crs,
        )

    def nearest_road_address(
        self,
        *,
        lon: float,
        lat: float,
        max_distance_m: float | None = 50.0,
    ) -> ReverseGeocodeResult | None:
        x, y = _transform_xy(lon, lat, "EPSG:4326", f"EPSG:{self.srid}")
        return self.nearest_road_address_xy(x=x, y=y, max_distance_m=max_distance_m)

    def nearest_road_address_xy(
        self,
        *,
        x: float,
        y: float,
        max_distance_m: float | None = 50.0,
    ) -> ReverseGeocodeResult | None:
        distance_expr = (
            (self.point_table.c.x - x) * (self.point_table.c.x - x)
            + (self.point_table.c.y - y) * (self.point_table.c.y - y)
        )
        stmt = select(
            self.point_table,
            func.sqrt(distance_expr).label("distance_m"),
        )
        if max_distance_m is not None:
            stmt = stmt.where(
                self.point_table.c.x.between(x - max_distance_m, x + max_distance_m),
                self.point_table.c.y.between(y - max_distance_m, y + max_distance_m),
            )
        stmt = stmt.order_by(distance_expr, self.point_table.c.source_priority).limit(1)
        with self.engine.connect() as connection:
            row = connection.execute(stmt).mappings().first()
        return _reverse_result_from_row(row) if row is not None else None

    def lookup_postal_code(
        self,
        request: PostalCodeLookupRequest | Mapping[str, Any] | str,
    ) -> list[CoordinateCandidate]:
        dto = _coerce_postal_request(request)
        stmt = (
            select(self.point_table)
            .where(self.point_table.c.postal_code == dto.zipcode)
            .order_by(
                self.point_table.c.road_name_code,
                self.point_table.c.building_main_no,
                self.point_table.c.building_sub_no,
                self.point_table.c.source_priority,
            )
            .limit(dto.limit)
            .offset(dto.offset)
        )
        with self.engine.connect() as connection:
            rows = list(connection.execute(stmt).mappings().all())
        return [_candidate_from_row(row) for row in rows]

    def validate_krmois_probe(
        self,
        probe: KRMoisAddressProbe | Mapping[str, Any],
    ) -> KRMoisAddressValidationResult:
        dto = (
            probe
            if isinstance(probe, KRMoisAddressProbe)
            else KRMoisAddressProbe.model_validate(probe)
        )
        input_x: float | None = None
        input_y: float | None = None
        if dto.lon is not None and dto.lat is not None:
            input_x, input_y = _transform_xy(dto.lon, dto.lat, "EPSG:4326", f"EPSG:{self.srid}")
        elif dto.x is not None and dto.y is not None:
            input_x, input_y = _transform_xy(dto.x, dto.y, dto.crs, f"EPSG:{self.srid}")

        geocode_candidate = None
        geocode_distance = None
        if dto.best_address:
            matches = self.get_coord({"query": dto.best_address, "limit": 1, "crs": "EPSG:5179"})
            if matches:
                geocode_candidate = matches[0]
                if input_x is not None and input_y is not None:
                    geocode_distance = _distance(
                        input_x,
                        input_y,
                        geocode_candidate.x,
                        geocode_candidate.y,
                    )

        reverse_candidate = None
        reverse_distance = None
        if input_x is not None and input_y is not None:
            result = self.nearest_road_address_xy(
                x=input_x,
                y=input_y,
                max_distance_m=dto.distance_tolerance_m,
            )
            if result is not None:
                reverse_candidate = CoordinateCandidate(
                    x=result.x or input_x,
                    y=result.y or input_y,
                    crs="EPSG:5179",
                    road_address=result.road_address,
                    postal_code=result.postal_code,
                    legal_dong_code=result.legal_dong_code,
                    road_name_code=result.road_name_code,
                    building_management_number=result.building_management_number,
                    building_name=result.building_name,
                    source=result.source,
                    distance_m=result.distance_m,
                    raw=dict(result.raw),
                )
                reverse_distance = result.distance_m

        address_text = dto.best_address or ""
        candidate_address = (
            (geocode_candidate.road_address if geocode_candidate else None)
            or (reverse_candidate.road_address if reverse_candidate else None)
            or ""
        )
        distance_values = [
            value for value in (geocode_distance, reverse_distance) if value is not None
        ]
        within_tolerance = (
            bool(distance_values) and min(distance_values) <= dto.distance_tolerance_m
        )
        return KRMoisAddressValidationResult(
            source_id=dto.source_id,
            input_address=dto.best_address,
            input_x=input_x,
            input_y=input_y,
            input_crs=dto.crs,
            geocode_candidate=geocode_candidate,
            reverse_candidate=reverse_candidate,
            geocode_distance_m=geocode_distance,
            reverse_distance_m=reverse_distance,
            address_match=bool(address_text and address_text in candidate_address),
            within_tolerance=within_tolerance,
        )

    def _query_by_road_key(self, dto: VWorldLikeGeocodeRequest) -> list[RowMapping]:
        stmt = select(self.point_table).where(
            self.point_table.c.road_name_code == dto.road_name_code,
            self.point_table.c.building_main_no == _number_text(dto.building_main_no),
        )
        if dto.underground_yn is not None:
            stmt = stmt.where(self.point_table.c.underground_yn == dto.underground_yn)
        if dto.building_sub_no is not None:
            stmt = stmt.where(
                self.point_table.c.building_sub_no == _number_text(dto.building_sub_no)
            )
        if dto.legal_dong_code is not None:
            stmt = stmt.where(self.point_table.c.legal_dong_code == dto.legal_dong_code)
        stmt = stmt.order_by(self.point_table.c.source_priority, self.point_table.c.coordinate_role)
        with self.engine.connect() as connection:
            return list(connection.execute(stmt).mappings().all())

    def _query_by_address_text(self, query: str, *, limit: int) -> list[RowMapping]:
        like = f"%{query.strip()}%"
        stmt = (
            select(self.point_table)
            .where(
                (self.point_table.c.road_address == query)
                | (self.point_table.c.road_address.like(like))
                | (self.point_table.c.building_name == query)
            )
            .order_by(
                (self.point_table.c.road_address == query).desc(),
                self.point_table.c.source_priority,
            )
            .limit(limit)
        )
        with self.engine.connect() as connection:
            return list(connection.execute(stmt).mappings().all())

    def _upsert_point_rows(self, rows: Sequence[dict[str, Any]]) -> None:
        if not rows:
            return
        stmt = sqlite_insert(self.point_table)
        update_values = {
            column.name: getattr(stmt.excluded, column.name)
            for column in self.point_table.c
            if column.name != "point_id"
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=["point_id"],
            set_=update_values,
        )
        with self.engine.begin() as connection:
            connection.execute(stmt, list(rows))
            if self.spatialite_enabled:
                _refresh_point_geometries(connection, self.srid, [row["point_id"] for row in rows])

    def _upsert_boundary_rows(self, rows: Sequence[dict[str, Any]]) -> None:
        if not rows:
            return
        stmt = sqlite_insert(self.boundary_table)
        update_values = {
            column.name: getattr(stmt.excluded, column.name)
            for column in self.boundary_table.c
            if column.name != "id"
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=["source_system", "source_layer", "source_code"],
            set_=update_values,
        )
        with self.engine.begin() as connection:
            connection.execute(stmt, list(rows))
            if self.spatialite_enabled:
                _refresh_boundary_geometries(connection, self.srid)


def make_spatialite_metadata() -> MetaData:
    metadata = MetaData()
    Table(
        SPATIALITE_ADDRESS_POINT_TABLE,
        metadata,
        Column("point_id", String(180), primary_key=True),
        Column("source", String(300), nullable=False, default=""),
        Column("source_dataset", String(80), nullable=False),
        Column("source_key", String(180), nullable=False),
        Column("source_priority", Integer, nullable=False, default=100),
        Column("coordinate_role", String(40), nullable=False),
        Column("building_management_number", String(30)),
        Column("legal_dong_code", String(10)),
        Column("sido_name", String(40), nullable=False, default=""),
        Column("sigungu_name", String(40), nullable=False, default=""),
        Column("eup_myeon_dong_name", String(40), nullable=False, default=""),
        Column("road_name_code", String(12)),
        Column("road_name", String(80), nullable=False, default=""),
        Column("underground_yn", String(1), nullable=False, default="0"),
        Column("building_main_no", String(10), nullable=False, default="0"),
        Column("building_sub_no", String(10), nullable=False, default="0"),
        Column("postal_code", String(5), nullable=False, default=""),
        Column("road_address", String(300), nullable=False, default=""),
        Column("parcel_address", String(300), nullable=False, default=""),
        Column("building_name", String(200), nullable=False, default=""),
        Column("building_use", String(100), nullable=False, default=""),
        Column("x", Float, nullable=False),
        Column("y", Float, nullable=False),
        Column("srid", Integer, nullable=False, default=DEFAULT_SRID),
        Column("geom_wkt", String, nullable=False),
        Column("geom_wkb", LargeBinary, nullable=False),
        Column("loaded_at", DateTime(timezone=True), nullable=False),
        Column("raw_json", JSON, nullable=False, default=dict),
        UniqueConstraint(
            "source_dataset",
            "source_key",
            "coordinate_role",
            name="uq_juso_point_source_role",
        ),
        Index("ix_juso_points_source", "source"),
        Index("ix_juso_points_dataset_role", "source_dataset", "coordinate_role"),
        Index("ix_juso_points_priority", "source_priority"),
        Index(
            "ix_juso_points_listing_order",
            "source_priority",
            "road_name_code",
            "building_main_no",
            "building_sub_no",
            "point_id",
        ),
        Index("ix_juso_points_building_mgmt", "building_management_number"),
        Index("ix_juso_points_legal_dong", "legal_dong_code"),
        Index("ix_juso_points_road_name", "road_name"),
        Index(
            "ix_juso_points_road_lookup",
            "road_name_code",
            "underground_yn",
            "building_main_no",
            "building_sub_no",
        ),
        Index("ix_juso_points_postal_code", "postal_code"),
        Index(
            "ix_juso_points_postal_lookup",
            "postal_code",
            "road_name_code",
            "building_main_no",
            "building_sub_no",
            "source_priority",
        ),
        Index("ix_juso_points_xy", "x", "y"),
        Index("ix_juso_points_road_address", "road_address"),
        Index("ix_juso_points_parcel_address", "parcel_address"),
        Index("ix_juso_points_building_name", "building_name"),
    )
    Table(
        SPATIALITE_BOUNDARY_TABLE,
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("source_system", String(80), nullable=False),
        Column("source_file", String(260), nullable=False),
        Column("source_layer", String(80), nullable=False),
        Column("source_code", String(30), nullable=False),
        Column("source_name", String(200), nullable=False, default=""),
        Column("legal_dong_code", String(10)),
        Column("boundary_level", String(30), nullable=False),
        Column("mapping_status", String(40), nullable=False),
        Column("srid", Integer, nullable=False, default=DEFAULT_SRID),
        Column("geom_wkt", String, nullable=False),
        Column("geom_wkb", LargeBinary, nullable=False),
        Column("loaded_at", DateTime(timezone=True), nullable=False),
        Column("raw_json", JSON, nullable=False, default=dict),
        UniqueConstraint(
            "source_system",
            "source_layer",
            "source_code",
            name="uq_juso_boundary_source",
        ),
        Index("ix_juso_boundaries_legal_code", "legal_dong_code"),
        Index("ix_juso_boundaries_source_code", "source_code"),
        Index("ix_juso_boundaries_layer", "source_layer"),
        Index("ix_juso_boundaries_status", "mapping_status"),
    )
    Table(
        SPATIALITE_METADATA_TABLE,
        metadata,
        Column("key", String(100), primary_key=True),
        Column("value", String, nullable=False, default=""),
        Column("updated_at", DateTime(timezone=True), nullable=False),
    )
    return metadata


def iter_location_summary_records(
    path: str | Path | bytes,
    *,
    encoding: str | None = None,
) -> Iterator[LocationSummaryEntranceRecord]:
    for member in _iter_text_members(_content_bytes(path)):
        if not Path(member.name).name.lower().startswith("entrc_"):
            continue
        for line in _iter_decoded_lines(member.content, encoding=encoding):
            if not line.strip():
                continue
            parts = _split_line(line)
            if len(parts) < len(LOCATION_SUMMARY_ENTRANCE_COLUMNS):
                continue
            values = parts[: len(LOCATION_SUMMARY_ENTRANCE_COLUMNS)]
            yield LocationSummaryEntranceRecord(
                **dict(zip(LOCATION_SUMMARY_ENTRANCE_COLUMNS, values, strict=True)),
                source_member=member.name,
                raw={"source_member": member.name},
            )


def iter_navigation_road_section_entrance_records(
    path: str | Path | bytes,
    *,
    encoding: str | None = None,
) -> Iterator[NavigationRoadSectionEntranceRecord]:
    for member in _iter_navigation_archive_members(path, wanted_prefix="match_rs_entrc"):
        for line in _iter_decoded_lines(member.content, encoding=encoding):
            if not line.strip():
                continue
            parts = _split_line(line)
            if len(parts) < len(NAVIGATION_ROAD_SECTION_ENTRANCE_COLUMNS):
                continue
            values = parts[: len(NAVIGATION_ROAD_SECTION_ENTRANCE_COLUMNS)]
            yield NavigationRoadSectionEntranceRecord(
                **dict(zip(NAVIGATION_ROAD_SECTION_ENTRANCE_COLUMNS, values, strict=True)),
                source_member=member.name,
                raw={"source_member": member.name},
            )


def read_boundary_zip(
    path: str | Path,
    *,
    srid: int = DEFAULT_SRID,
    encoding: str = "cp949",
) -> Any:
    """Read one district-shape ZIP into a GeoDataFrame in EPSG:5179."""

    try:
        import geopandas as gpd  # type: ignore[import-untyped]
        import pandas as pd  # type: ignore[import-untyped]
        from shapely.geometry import MultiPolygon, Polygon  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "Boundary loading requires geopandas and shapely. "
            "Install python-kraddr-geo[spatialite]."
        ) from exc

    archive_path = Path(path)
    with tempfile.TemporaryDirectory(prefix="kraddr-geo-shp-") as tmp:
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(tmp)
        shp_files = sorted(Path(tmp).rglob("*.shp"))
        if not shp_files:
            raise ValueError(f"{archive_path}: no SHP file found")
        frames = []
        for shp_file in shp_files:
            frame = gpd.read_file(shp_file, encoding=encoding)
            if frame.crs is None:
                frame = frame.set_crs(epsg=srid, allow_override=True)
            elif frame.crs.to_epsg() != srid:
                frame = frame.to_crs(epsg=srid)
            frame = frame.rename_geometry("geom")

            def force_multipolygon(geometry: Any) -> Any:
                if isinstance(geometry, Polygon):
                    return MultiPolygon([geometry])
                return geometry

            frame["geom"] = frame["geom"].apply(force_multipolygon)
            frame["__source_shp"] = shp_file.name
            frame["__source_layer"] = shp_file.stem.lower()
            frame["__boundary_level"] = boundary_level_from_path(shp_file.name)
            frame["__source_region_code"] = shp_file.parent.name
            frame["__source_row"] = range(1, len(frame) + 1)
            frames.append(frame)
        combined = pd.concat(frames, ignore_index=True, sort=False)
    return gpd.GeoDataFrame(combined, geometry="geom", crs=f"EPSG:{srid}")


def boundary_level_from_path(path: str | Path) -> str:
    stem = Path(path).stem.upper()
    if "CTPRVN" in stem:
        return "sido"
    if "SIG" in stem and "MAKAREA" not in stem:
        return "sigungu"
    if "GEMD" in stem:
        return "legal_dong"
    if "EMD" in stem:
        return "eup_myeon_dong"
    if "LI" in stem:
        return "ri"
    if "KODIS_BAS" in stem:
        return "basic_zone"
    if "MAKAREA" in stem:
        return "managed_area"
    if "G001" in stem:
        return "sido"
    if "G010" in stem:
        return "sigungu"
    if "G011" in stem:
        return "eup_myeon_dong"
    return "unknown"


def _iter_navigation_archive_members(
    path: str | Path | bytes,
    *,
    wanted_prefix: str,
) -> Iterator[Any]:
    if isinstance(path, bytes):
        yield from (
            member
            for member in _iter_text_members(path)
            if Path(member.name).name.lower().startswith(wanted_prefix)
        )
        return
    archive_path = Path(path)
    if archive_path.suffix.lower() != ".7z":
        content = archive_path.read_bytes()
        for member in _iter_text_members(content):
            member_name = Path(member.name).name.lower()
            archive_name = archive_path.name.lower()
            if member_name.startswith(wanted_prefix):
                yield member
            elif archive_name.startswith(wanted_prefix):
                yield type(
                    "_TextMember",
                    (),
                    {"name": archive_path.name, "content": member.content},
                )()
        return
    yield from _iter_7z_text_members(archive_path, wanted_prefix=wanted_prefix)


def _iter_7z_text_members(path: Path, *, wanted_prefix: str) -> Iterator[Any]:
    try:
        import py7zr  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "Reading Juso .7z archives requires py7zr. Install python-kraddr-geo[spatialite]."
        ) from exc

    with py7zr.SevenZipFile(path) as archive:
        names = [
            name
            for name in archive.getnames()
            if Path(name).name.lower().startswith(wanted_prefix) and name.lower().endswith(".txt")
        ]
    for name in names:
        with tempfile.TemporaryDirectory(prefix="kraddr-geo-7z-") as tmp:
            with py7zr.SevenZipFile(path) as archive:
                archive.extract(path=tmp, targets=[name])
            extracted = Path(tmp) / name
            yield type("_TextMember", (), {"name": name, "content": extracted.read_bytes()})()


def _navigation_address_point_rows(
    record: NavigationBuildingRecord,
    *,
    source: str,
    srid: int,
) -> list[dict[str, Any]]:
    if record.is_deleted or not record.building_management_number:
        return []
    rows: list[dict[str, Any]] = []
    entrance_xy = _xy(record.entrance_x, record.entrance_y)
    center_xy = _xy(record.building_center_x, record.building_center_y)
    if entrance_xy is not None:
        rows.append(
            _base_point_row(
                point_id=f"navigation:{record.building_management_number}:entrance",
                source=source,
                source_dataset="navigation_building",
                source_key=record.building_management_number,
                source_priority=20,
                coordinate_role="entrance",
                x=entrance_xy[0],
                y=entrance_xy[1],
                srid=srid,
                building_management_number=record.building_management_number,
                legal_dong_code=record.legal_dong_code,
                sido_name=record.sido_name,
                sigungu_name=record.sigungu_name,
                eup_myeon_dong_name=record.eup_myeon_dong_name,
                road_name_code=record.road_name_code,
                road_name=record.road_name,
                underground_yn=record.underground_yn,
                building_main_no=record.building_main_no,
                building_sub_no=record.building_sub_no,
                postal_code=record.postal_code,
                road_address=record.road_address,
                building_name=record.building_name,
                building_use=record.building_use,
                raw=record.raw,
            )
        )
    if center_xy is not None:
        rows.append(
            _base_point_row(
                point_id=f"navigation:{record.building_management_number}:center",
                source=source,
                source_dataset="navigation_building",
                source_key=record.building_management_number,
                source_priority=30,
                coordinate_role="center",
                x=center_xy[0],
                y=center_xy[1],
                srid=srid,
                building_management_number=record.building_management_number,
                legal_dong_code=record.legal_dong_code,
                sido_name=record.sido_name,
                sigungu_name=record.sigungu_name,
                eup_myeon_dong_name=record.eup_myeon_dong_name,
                road_name_code=record.road_name_code,
                road_name=record.road_name,
                underground_yn=record.underground_yn,
                building_main_no=record.building_main_no,
                building_sub_no=record.building_sub_no,
                postal_code=record.postal_code,
                road_address=record.road_address,
                building_name=record.building_name,
                building_use=record.building_use,
                raw=record.raw,
            )
        )
    return rows


def _location_summary_address_point_row(
    record: LocationSummaryEntranceRecord,
    *,
    source: str,
    srid: int,
) -> dict[str, Any] | None:
    xy = record.point_xy()
    if xy is None:
        return None
    return _base_point_row(
        point_id=f"location_summary:{record.source_key}",
        source=source,
        source_dataset="location_summary",
        source_key=record.source_key,
        source_priority=10,
        coordinate_role="summary_entrance",
        x=xy[0],
        y=xy[1],
        srid=srid,
        building_management_number=None,
        legal_dong_code=record.legal_dong_code,
        sido_name=record.sido_name,
        sigungu_name=record.sigungu_name,
        eup_myeon_dong_name=record.eup_myeon_dong_name,
        road_name_code=record.road_name_code,
        road_name=record.road_name,
        underground_yn=record.underground_yn,
        building_main_no=record.building_main_no,
        building_sub_no=record.building_sub_no,
        postal_code=record.postal_code,
        road_address=record.road_address,
        building_name=record.building_name or record.detail_building_name,
        building_use=record.building_use,
        raw=record.raw,
    )


def _road_section_entrance_point_row(
    record: NavigationRoadSectionEntranceRecord,
    *,
    source: str,
    srid: int,
) -> dict[str, Any] | None:
    xy = record.point_xy()
    if xy is None:
        return None
    return _base_point_row(
        point_id=f"navigation_rs:{record.source_key}",
        source=source,
        source_dataset="navigation_road_section_entrance",
        source_key=record.source_key,
        source_priority=40,
        coordinate_role="road_section_entrance",
        x=xy[0],
        y=xy[1],
        srid=srid,
        building_management_number=None,
        legal_dong_code=record.legal_dong_code,
        road_name_code=record.road_name_code,
        underground_yn=record.underground_yn,
        building_main_no=record.building_main_no,
        building_sub_no=record.building_sub_no,
        raw=record.raw,
    )


def _base_point_row(
    *,
    point_id: str,
    source: str,
    source_dataset: str,
    source_key: str,
    source_priority: int,
    coordinate_role: str,
    x: float,
    y: float,
    srid: int,
    building_management_number: str | None = None,
    legal_dong_code: str | None = None,
    sido_name: str = "",
    sigungu_name: str = "",
    eup_myeon_dong_name: str = "",
    road_name_code: str | None = None,
    road_name: str = "",
    underground_yn: str = "0",
    building_main_no: str = "0",
    building_sub_no: str = "0",
    postal_code: str = "",
    road_address: str = "",
    parcel_address: str = "",
    building_name: str = "",
    building_use: str = "",
    raw: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    wkt = f"POINT({x} {y})"
    return {
        "point_id": point_id,
        "source": source,
        "source_dataset": source_dataset,
        "source_key": source_key,
        "source_priority": source_priority,
        "coordinate_role": coordinate_role,
        "building_management_number": building_management_number,
        "legal_dong_code": legal_dong_code,
        "sido_name": sido_name,
        "sigungu_name": sigungu_name,
        "eup_myeon_dong_name": eup_myeon_dong_name,
        "road_name_code": road_name_code,
        "road_name": road_name,
        "underground_yn": underground_yn,
        "building_main_no": _number_text(building_main_no),
        "building_sub_no": _number_text(building_sub_no),
        "postal_code": postal_code,
        "road_address": road_address,
        "parcel_address": parcel_address,
        "building_name": building_name,
        "building_use": building_use,
        "x": x,
        "y": y,
        "srid": srid,
        "geom_wkt": wkt,
        "geom_wkb": _point_wkb(x, y),
        "loaded_at": datetime.now(UTC),
        "raw_json": dict(raw or {}),
    }


def _candidate_from_row(row: RowMapping) -> CoordinateCandidate:
    return CoordinateCandidate(
        x=float(row["x"]),
        y=float(row["y"]),
        crs="EPSG:5179",
        road_address=str(row["road_address"] or "") or None,
        parcel_address=str(row["parcel_address"] or "") or None,
        postal_code=str(row["postal_code"] or "") or None,
        legal_dong_code=str(row["legal_dong_code"] or "") or None,
        road_name_code=str(row["road_name_code"] or "") or None,
        underground_yn=str(row["underground_yn"] or "") or None,
        building_main_no=str(row["building_main_no"] or "") or None,
        building_sub_no=str(row["building_sub_no"] or "") or None,
        building_management_number=str(row["building_management_number"] or "") or None,
        building_name=str(row["building_name"] or "") or None,
        source=str(row["source_dataset"] or row["source"] or ""),
        coordinate_role=str(row["coordinate_role"] or ""),
        distance_m=float(row["distance_m"]) if row.get("distance_m") is not None else None,
        raw=dict(row),
    )


def _candidate_in_crs(candidate: CoordinateCandidate, target_crs: str) -> CoordinateCandidate:
    if candidate.crs.upper() == target_crs.upper():
        return candidate
    x, y = _transform_xy(candidate.x, candidate.y, candidate.crs, target_crs)
    data = candidate.model_dump()
    data["x"] = x
    data["y"] = y
    data["crs"] = target_crs
    return CoordinateCandidate.model_validate(data)


def _make_vworld_client(
    *,
    api_key: str | None,
    domain: str | None,
    timeout: float,
) -> Any | None:
    if not api_key and not domain:
        return None
    try:
        from vworld import VworldClient  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("python-vworld-api is required for VWorld fallback.") from exc
    return VworldClient(api_key=api_key, domain=domain, timeout=timeout)


def _vworld_get_coord_candidates(
    client: Any,
    dto: VWorldLikeGeocodeRequest,
) -> list[CoordinateCandidate]:
    if not dto.query:
        return []
    types = ("road", "parcel") if dto.type == "both" else (dto.type,)
    candidates: list[CoordinateCandidate] = []
    for address_type in types:
        payload = client.get_coord(
            dto.query,
            type=address_type,
            crs=dto.crs,
        )
        for row in _vworld_result_rows(payload):
            point = row.get("point")
            if not isinstance(point, Mapping):
                continue
            x = _float_or_none(str(point.get("x") or ""))
            y = _float_or_none(str(point.get("y") or ""))
            if x is None or y is None:
                continue
            candidates.append(
                CoordinateCandidate(
                    x=x,
                    y=y,
                    crs=dto.crs,
                    road_address=_vworld_text(row) if address_type == "road" else None,
                    parcel_address=_vworld_text(row) if address_type == "parcel" else None,
                    source="vworld",
                    coordinate_role="fallback",
                    raw=dict(row),
                )
            )
            if len(candidates) >= dto.limit:
                return candidates
    return candidates


def _vworld_get_address_candidate(
    client: Any,
    dto: VWorldLikeReverseGeocodeRequest,
) -> CoordinateCandidate | None:
    payload = client.get_address(
        (dto.x, dto.y),
        type=dto.type,
        crs=dto.crs,
        zipcode=True,
    )
    for row in _vworld_result_rows(payload):
        address = row.get("address")
        address_map: Mapping[str, Any] = address if isinstance(address, Mapping) else {}
        row_type = str(row.get("type") or row.get("category") or dto.type).lower()
        text_value = _vworld_text(row)
        road_address = _text_from_mapping(row, "roadAddr") or _text_from_mapping(
            address_map, "road"
        )
        parcel_address = _text_from_mapping(row, "jibunAddr") or _text_from_mapping(
            address_map, "parcel"
        )
        if row_type == "road" and road_address is None:
            road_address = text_value
        elif row_type == "parcel" and parcel_address is None:
            parcel_address = text_value
        elif road_address is None and parcel_address is None:
            road_address = text_value
        return CoordinateCandidate(
            x=dto.x,
            y=dto.y,
            crs=dto.crs,
            road_address=road_address,
            parcel_address=parcel_address,
            postal_code=_text_from_mapping(row, "zipcode")
            or _text_from_mapping(row, "zipNo")
            or _text_from_mapping(address_map, "zipcode"),
            source="vworld",
            coordinate_role="fallback",
            raw=dict(row),
        )
    return None


def _vworld_result_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    root = payload.get("response", payload)
    if not isinstance(root, Mapping):
        return []
    status = str(root.get("status") or "").upper()
    if status and status not in {"OK", "NORMAL"}:
        return []
    result = root.get("result")
    if result is None:
        return []
    if isinstance(result, list):
        return [row for row in result if isinstance(row, Mapping)]
    if isinstance(result, Mapping):
        items = result.get("items")
        if isinstance(items, list):
            return [row for row in items if isinstance(row, Mapping)]
        if isinstance(items, Mapping):
            return [items]
        return [result]
    return []


def _vworld_text(row: Mapping[str, Any]) -> str | None:
    return _text_from_mapping(row, "text") or _text_from_mapping(row, "address")


def _text_from_mapping(raw: Mapping[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is None or isinstance(value, Mapping):
        return None
    text_value = str(value).strip()
    return text_value or None


def _reverse_result_from_row(row: RowMapping) -> ReverseGeocodeResult:
    candidate = _candidate_from_row(row)
    return ReverseGeocodeResult(
        address_type="road",
        road_address=candidate.road_address,
        parcel_address=candidate.parcel_address,
        postal_code=candidate.postal_code,
        legal_dong_code=candidate.legal_dong_code,
        road_name_code=candidate.road_name_code,
        building_management_number=candidate.building_management_number,
        building_name=candidate.building_name,
        x=candidate.x,
        y=candidate.y,
        crs="EPSG:5179",
        distance_m=candidate.distance_m,
        source=candidate.source,
        raw=dict(row),
    )


def _set_sqlite_pragmas(connection: Any) -> None:
    for sql in (
        "PRAGMA foreign_keys = ON",
        "PRAGMA temp_store = MEMORY",
        "PRAGMA synchronous = NORMAL",
        "PRAGMA journal_mode = WAL",
    ):
        try:
            connection.execute(text(sql))
        except Exception:
            continue


def _ensure_sqlite_performance_indexes(connection: Any) -> None:
    for sql in (
        f"""
        CREATE INDEX IF NOT EXISTS ix_juso_points_listing_order
        ON {SPATIALITE_ADDRESS_POINT_TABLE}
        (source_priority, road_name_code, building_main_no, building_sub_no, point_id)
        """,
        f"""
        CREATE INDEX IF NOT EXISTS ix_juso_points_postal_lookup
        ON {SPATIALITE_ADDRESS_POINT_TABLE}
        (postal_code, road_name_code, building_main_no, building_sub_no, source_priority)
        """,
        f"""
        CREATE INDEX IF NOT EXISTS ix_juso_points_road_name
        ON {SPATIALITE_ADDRESS_POINT_TABLE} (road_name)
        """,
        f"""
        CREATE INDEX IF NOT EXISTS ix_juso_points_parcel_address
        ON {SPATIALITE_ADDRESS_POINT_TABLE} (parcel_address)
        """,
        f"""
        CREATE INDEX IF NOT EXISTS ix_juso_points_building_name
        ON {SPATIALITE_ADDRESS_POINT_TABLE} (building_name)
        """,
    ):
        connection.execute(text(sql))


def _ensure_sqlite_search_index(connection: Any) -> None:
    connection.execute(
        text(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {SPATIALITE_ADDRESS_SEARCH_TABLE}
            USING fts5(
                road_name,
                road_address,
                parcel_address,
                building_name,
                content='{SPATIALITE_ADDRESS_POINT_TABLE}',
                content_rowid='rowid',
                tokenize='trigram'
            )
            """
        )
    )
    connection.execute(
        text(
            f"""
            CREATE TRIGGER IF NOT EXISTS juso_address_points_fts_ai
            AFTER INSERT ON {SPATIALITE_ADDRESS_POINT_TABLE}
            BEGIN
                INSERT INTO {SPATIALITE_ADDRESS_SEARCH_TABLE}
                    (rowid, road_name, road_address, parcel_address, building_name)
                VALUES (
                    new.rowid,
                    new.road_name,
                    new.road_address,
                    new.parcel_address,
                    new.building_name
                );
            END
            """
        )
    )
    connection.execute(
        text(
            f"""
            CREATE TRIGGER IF NOT EXISTS juso_address_points_fts_ad
            AFTER DELETE ON {SPATIALITE_ADDRESS_POINT_TABLE}
            BEGIN
                INSERT INTO {SPATIALITE_ADDRESS_SEARCH_TABLE}
                    (
                        {SPATIALITE_ADDRESS_SEARCH_TABLE},
                        rowid,
                        road_name,
                        road_address,
                        parcel_address,
                        building_name
                    )
                VALUES (
                    'delete',
                    old.rowid,
                    old.road_name,
                    old.road_address,
                    old.parcel_address,
                    old.building_name
                );
            END
            """
        )
    )
    connection.execute(
        text(
            f"""
            CREATE TRIGGER IF NOT EXISTS juso_address_points_fts_au
            AFTER UPDATE ON {SPATIALITE_ADDRESS_POINT_TABLE}
            BEGIN
                INSERT INTO {SPATIALITE_ADDRESS_SEARCH_TABLE}
                    (
                        {SPATIALITE_ADDRESS_SEARCH_TABLE},
                        rowid,
                        road_name,
                        road_address,
                        parcel_address,
                        building_name
                    )
                VALUES (
                    'delete',
                    old.rowid,
                    old.road_name,
                    old.road_address,
                    old.parcel_address,
                    old.building_name
                );
                INSERT INTO {SPATIALITE_ADDRESS_SEARCH_TABLE}
                    (rowid, road_name, road_address, parcel_address, building_name)
                VALUES (
                    new.rowid,
                    new.road_name,
                    new.road_address,
                    new.parcel_address,
                    new.building_name
                );
            END
            """
        )
    )


def _mark_search_index_ready(connection: Any) -> None:
    connection.execute(
        text(
            f"""
            INSERT INTO {SPATIALITE_METADATA_TABLE} (key, value, updated_at)
            VALUES (:key, :value, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """
        ),
        {"key": SEARCH_INDEX_READY_METADATA_KEY, "value": "fts5_trigram"},
    )


def _try_enable_spatialite(connection: Any, srid: int) -> bool:
    del srid
    raw = getattr(connection.connection, "driver_connection", None)
    if raw is None:
        raw = getattr(connection.connection, "connection", None)
    if raw is None:
        return False
    try:
        raw.enable_load_extension(True)
    except Exception:
        return False
    loaded = False
    for name in ("mod_spatialite", "mod_spatialite.dll", "libspatialite"):
        try:
            raw.load_extension(name)
            loaded = True
            break
        except Exception:
            continue
    try:
        raw.enable_load_extension(False)
    except Exception:
        pass
    if not loaded:
        return False
    try:
        connection.execute(text("SELECT InitSpatialMetaData(1)"))
    except Exception:
        pass
    return True


def _ensure_spatialite_geometry(connection: Any, srid: int) -> bool:
    try:
        _add_geometry_column(connection, SPATIALITE_ADDRESS_POINT_TABLE, "geom", srid, "POINT")
        _add_geometry_column(connection, SPATIALITE_BOUNDARY_TABLE, "geom", srid, "MULTIPOLYGON")
        connection.execute(
            text(f"SELECT CreateSpatialIndex('{SPATIALITE_ADDRESS_POINT_TABLE}', 'geom')")
        )
        connection.execute(
            text(f"SELECT CreateSpatialIndex('{SPATIALITE_BOUNDARY_TABLE}', 'geom')")
        )
    except Exception:
        return False
    return True


def _add_geometry_column(
    connection: Any,
    table_name: str,
    column_name: str,
    srid: int,
    geometry_type: str,
) -> None:
    exists = connection.execute(
        text(f"SELECT 1 FROM pragma_table_info('{table_name}') WHERE name = :name"),
        {"name": column_name},
    ).first()
    if exists:
        return
    connection.execute(
        text(
            "SELECT AddGeometryColumn(:table_name, :column_name, :srid, :geometry_type, 'XY')"
        ),
        {
            "table_name": table_name,
            "column_name": column_name,
            "srid": srid,
            "geometry_type": geometry_type,
        },
    )


def _refresh_point_geometries(connection: Any, srid: int, point_ids: Sequence[str]) -> None:
    if not point_ids:
        return
    connection.execute(
        text(
            f"""
            UPDATE {SPATIALITE_ADDRESS_POINT_TABLE}
               SET geom = MakePoint(x, y, :srid)
             WHERE point_id IN :point_ids
            """
        ).bindparams(bindparam("point_ids", expanding=True)),
        {"srid": srid, "point_ids": tuple(point_ids)},
    )


def _refresh_boundary_geometries(connection: Any, srid: int) -> None:
    connection.execute(
        text(
            f"""
            UPDATE {SPATIALITE_BOUNDARY_TABLE}
               SET geom = GeomFromText(geom_wkt, :srid)
             WHERE geom IS NULL
            """
        ),
        {"srid": srid},
    )


def _coerce_geocode_request(
    request: VWorldLikeGeocodeRequest | Mapping[str, Any],
) -> VWorldLikeGeocodeRequest:
    if isinstance(request, VWorldLikeGeocodeRequest):
        return request
    return VWorldLikeGeocodeRequest.model_validate(request)


def _coerce_reverse_request(
    request: VWorldLikeReverseGeocodeRequest | Mapping[str, Any],
) -> VWorldLikeReverseGeocodeRequest:
    if isinstance(request, VWorldLikeReverseGeocodeRequest):
        return request
    return VWorldLikeReverseGeocodeRequest.model_validate(request)


def _coerce_postal_request(
    request: PostalCodeLookupRequest | Mapping[str, Any] | str,
) -> PostalCodeLookupRequest:
    if isinstance(request, PostalCodeLookupRequest):
        return request
    if isinstance(request, str):
        return PostalCodeLookupRequest.model_validate({"zipNo": request})
    return PostalCodeLookupRequest.model_validate(request)


@lru_cache(maxsize=16)
def _transformer(source_crs: str, target_crs: str) -> Any:
    try:
        from pyproj import Transformer
    except ImportError as exc:
        raise RuntimeError("Coordinate conversion requires pyproj.") from exc
    return Transformer.from_crs(source_crs, target_crs, always_xy=True)


def _transform_xy(x: float, y: float, source_crs: str, target_crs: str) -> tuple[float, float]:
    if source_crs.upper() == target_crs.upper():
        return float(x), float(y)
    transformer = _transformer(source_crs.upper(), target_crs.upper())
    tx, ty = transformer.transform(float(x), float(y))
    return float(tx), float(ty)


def _xy(x: str, y: str) -> tuple[float, float] | None:
    x_value = _float_or_none(x)
    y_value = _float_or_none(y)
    if x_value is None or y_value is None:
        return None
    return x_value, y_value


def _float_or_none(value: str) -> float | None:
    text_value = str(value or "").strip()
    if not text_value:
        return None
    try:
        return float(text_value)
    except ValueError:
        return None


def _strip_number(value: str) -> str:
    text_value = str(value or "").strip()
    return text_value.lstrip("0") or "0"


def _number_text(value: int | str | None) -> str:
    if value is None:
        return "0"
    return _strip_number(str(value))


def _distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.hypot(x1 - x2, y1 - y2)


def _point_wkb(x: float, y: float) -> bytes:
    return struct.pack("<BIdd", 1, 1, float(x), float(y))


def _source_name(path: str | Path | bytes) -> str:
    if isinstance(path, bytes):
        return "bytes"
    return Path(path).name


def _pick_boundary_column(columns: Iterable[Any], candidates: Iterable[str]) -> str | None:
    available = {str(column).upper(): str(column) for column in columns}
    for candidate in candidates:
        value = available.get(candidate.upper())
        if value is not None:
            return value
    return None


_BOUNDARY_CODE_COLUMNS_BY_LAYER = {
    "tl_scco_ctprvn": ("CTPRVN_CD",),
    "tl_scco_sig": ("SIG_CD",),
    "tl_scco_emd": ("EMD_CD",),
    "tl_scco_gemd": ("EMD_CD",),
    "tl_scco_li": ("LI_CD",),
    "tl_kodis_bas": ("BAS_ID", "BAS_MGT_SN"),
    "tl_sppn_makarea": ("MAKAREA_ID",),
}
_BOUNDARY_CODE_COLUMNS = (
    "BJCD",
    "BJD_CD",
    "ADM_CD",
    "CTPRVN_CD",
    "SIG_CD",
    "EMD_CD",
    "LI_CD",
    "BAS_ID",
    "BAS_MGT_SN",
    "MAKAREA_ID",
)
_BOUNDARY_NAME_COLUMNS = (
    "NAME",
    "BJD_NM",
    "ADM_NM",
    "CTP_KOR_NM",
    "SIG_KOR_NM",
    "EMD_KOR_NM",
    "LI_KOR_NM",
    "MAKAREA_NM",
)


def _boundary_source_code(row: Mapping[str, Any], *, source_layer: str) -> str:
    candidates = (
        *_BOUNDARY_CODE_COLUMNS_BY_LAYER.get(source_layer, ()),
        *_BOUNDARY_CODE_COLUMNS,
    )
    for column in candidates:
        value = _clean_boundary_value(row.get(column))
        if value:
            return value
    source_row = _clean_boundary_value(row.get("__source_row"))
    return f"{source_layer}:{source_row}" if source_row else source_layer


def _boundary_source_name(row: Mapping[str, Any]) -> str:
    for column in _BOUNDARY_NAME_COLUMNS:
        value = _clean_boundary_value(row.get(column))
        if value:
            return value
    return ""


def _clean_boundary_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text_value = str(value).strip()
    if not text_value or text_value.lower() == "nan":
        return ""
    if text_value.endswith(".0") and text_value[:-2].isdigit():
        return text_value[:-2]
    return text_value


def _jsonable_mapping(row: Mapping[str, Any], *, skip: set[str] | None = None) -> dict[str, Any]:
    skipped = skip or set()
    output: dict[str, Any] = {}
    for key, value in row.items():
        if key in skipped:
            continue
        try:
            json.dumps(value)
            output[key] = value
        except TypeError:
            output[key] = str(value)
    return output
