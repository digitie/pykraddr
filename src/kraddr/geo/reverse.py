"""오프라인 주소점과 VWorld 보조 호출을 이용한 리버스 지오코딩 기능."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from types import MappingProxyType
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    MetaData,
    String,
    Table,
    create_engine,
    insert,
    text,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine, RowMapping

from .data import _content_bytes, _iter_decoded_lines, _iter_text_members, _split_line
from .exceptions import KrAddrParseError, KrAddrRequestError

ROAD_ADDRESS_POINT_TABLE = "road_address_points"

NAVIGATION_BUILDING_COLUMNS = (
    "jurisdiction_emd_code",
    "sido_name",
    "sigungu_name",
    "eup_myeon_dong_name",
    "road_name_code",
    "road_name",
    "underground_yn",
    "building_main_no",
    "building_sub_no",
    "postal_code",
    "building_management_number",
    "sigungu_building_name",
    "building_use",
    "administrative_dong_code",
    "administrative_dong_name",
    "ground_floor_count",
    "underground_floor_count",
    "apartment_kind_code",
    "building_count",
    "detail_building_name",
    "building_name_history",
    "detail_building_name_history",
    "residential_yn",
    "building_center_x",
    "building_center_y",
    "entrance_x",
    "entrance_y",
    "sido_name_en",
    "sigungu_name_en",
    "eup_myeon_dong_name_en",
    "road_name_en",
    "eup_myeon_dong_type",
    "change_reason_code",
)


def _freeze(raw: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(raw or {}))


@dataclass(frozen=True, slots=True)
class ReverseGeocodeResult:
    """리버스 지오코딩 주소 결과 한 건."""

    address_type: str
    road_address: str | None = None
    parcel_address: str | None = None
    postal_code: str | None = None
    legal_dong_code: str | None = None
    road_name_code: str | None = None
    building_management_number: str | None = None
    building_name: str | None = None
    x: float | None = None
    y: float | None = None
    crs: str = "EPSG:4326"
    distance_m: float | None = None
    source: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw", _freeze(self.raw))

    @property
    def formatted_address(self) -> str | None:
        return self.road_address or self.parcel_address


@dataclass(frozen=True, slots=True)
class NavigationBuildingRecord:
    """Juso 내비게이션용DB 건물정보 TXT의 건물 행 한 건."""

    jurisdiction_emd_code: str
    sido_name: str
    sigungu_name: str
    eup_myeon_dong_name: str
    road_name_code: str
    road_name: str
    underground_yn: str
    building_main_no: str
    building_sub_no: str
    postal_code: str
    building_management_number: str
    sigungu_building_name: str
    building_use: str
    administrative_dong_code: str
    administrative_dong_name: str
    ground_floor_count: str
    underground_floor_count: str
    apartment_kind_code: str
    building_count: str
    detail_building_name: str
    building_name_history: str
    detail_building_name_history: str
    residential_yn: str
    building_center_x: str
    building_center_y: str
    entrance_x: str
    entrance_y: str
    sido_name_en: str
    sigungu_name_en: str
    eup_myeon_dong_name_en: str
    road_name_en: str
    eup_myeon_dong_type: str
    change_reason_code: str
    source_member: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw", _freeze(self.raw))

    @property
    def legal_dong_code(self) -> str:
        return self.jurisdiction_emd_code

    @property
    def is_deleted(self) -> bool:
        return self.change_reason_code == "63"

    @property
    def building_number(self) -> str:
        main = _strip_number(self.building_main_no)
        sub = _strip_number(self.building_sub_no)
        return main if sub in {"", "0"} else f"{main}-{sub}"

    @property
    def building_name(self) -> str:
        return self.sigungu_building_name or self.detail_building_name

    @property
    def road_address(self) -> str:
        parts = [self.sido_name, self.sigungu_name]
        if self.eup_myeon_dong_type == "0":
            parts.append(self.eup_myeon_dong_name)
        parts.extend([self.road_name, self.building_number])
        address = " ".join(part for part in parts if part)
        if self.building_name:
            return f"{address} ({self.building_name})"
        return address

    def point_xy(self, *, prefer_entrance: bool = True) -> tuple[float, float] | None:
        entrance = _xy(self.entrance_x, self.entrance_y)
        center = _xy(self.building_center_x, self.building_center_y)
        if prefer_entrance:
            return entrance or center
        return center or entrance


@dataclass(frozen=True, slots=True)
class AddressPointLoadResult:
    """주소점 적재 결과 요약."""

    loaded: int = 0
    skipped: int = 0
    deleted: int = 0


class RoadAddressPointStore:
    """오프라인 도로명주소 리버스 지오코딩용 PostGIS 저장소.

    주 입력원은 Juso 내비게이션용DB 건물정보 TXT다. 이 자료에는 건물 단위
    도로명주소 속성과 GRS80 UTM-K 좌표가 포함된다.
    """

    def __init__(
        self,
        url_or_engine: str | Engine,
        *,
        schema: str | None = "public",
        srid: int = 5179,
        echo: bool = False,
    ) -> None:
        self.schema = schema
        self.srid = srid
        if isinstance(url_or_engine, Engine):
            self.engine = url_or_engine
        else:
            self.engine = create_engine(url_or_engine, future=True, echo=echo)
        self.metadata = make_address_point_metadata(schema=schema, srid=srid)
        self.table = self.metadata.tables[_table_key(ROAD_ADDRESS_POINT_TABLE, schema)]
        self.create_schema()

    def close(self) -> None:
        self.engine.dispose()

    def __enter__(self) -> RoadAddressPointStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def create_schema(self) -> None:
        with self.engine.begin() as connection:
            if self.schema and self.schema != "public":
                connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_quote_ident(self.schema)}"))
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        self.metadata.create_all(self.engine)

    def reset(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(f"TRUNCATE TABLE {_qualified_name(ROAD_ADDRESS_POINT_TABLE, self.schema)}")
            )

    def load_navigation_building_archive(
        self,
        path: str | Path | bytes,
        *,
        replace: bool = True,
        batch_size: int = 10_000,
        source: str | None = None,
    ) -> AddressPointLoadResult:
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
        replace: bool = True,
        batch_size: int = 10_000,
        source: str = "",
    ) -> AddressPointLoadResult:
        if replace:
            self.reset()
        return self._upsert_navigation_records(records, batch_size=batch_size, source=source)

    def apply_navigation_building_changes(
        self,
        records: Iterable[NavigationBuildingRecord],
        *,
        batch_size: int = 10_000,
        source: str = "",
    ) -> AddressPointLoadResult:
        loaded = 0
        skipped = 0
        deleted = 0
        upserts: list[NavigationBuildingRecord] = []
        deletes: list[str] = []
        for record in records:
            if record.is_deleted:
                deletes.append(record.building_management_number)
                if len(deletes) >= batch_size:
                    deleted += self._delete_management_numbers(deletes)
                    deletes = []
                continue
            upserts.append(record)
            if len(upserts) >= batch_size:
                result = self._upsert_navigation_records(
                    upserts,
                    batch_size=batch_size,
                    source=source,
                )
                loaded += result.loaded
                skipped += result.skipped
                upserts = []
        if upserts:
            result = self._upsert_navigation_records(upserts, batch_size=batch_size, source=source)
            loaded += result.loaded
            skipped += result.skipped
        if deletes:
            deleted += self._delete_management_numbers(deletes)
        return AddressPointLoadResult(loaded=loaded, skipped=skipped, deleted=deleted)

    def nearest_road_address(
        self,
        *,
        lon: float,
        lat: float,
        max_distance_m: float | None = 50.0,
    ) -> ReverseGeocodeResult | None:
        """WGS84 경위도 좌표에 가장 가까운 오프라인 도로명주소를 찾는다."""

        return self.nearest_road_address_xy(
            x=lon,
            y=lat,
            input_srid=4326,
            max_distance_m=max_distance_m,
        )

    def nearest_road_address_xy(
        self,
        *,
        x: float,
        y: float,
        input_srid: int,
        max_distance_m: float | None = 50.0,
    ) -> ReverseGeocodeResult | None:
        query_geom = "ST_SetSRID(ST_MakePoint(:x, :y), :input_srid)"
        if input_srid != self.srid:
            query_geom = f"ST_Transform({query_geom}, :srid)"
        table = _qualified_name(ROAD_ADDRESS_POINT_TABLE, self.schema)
        distance_filter = ""
        if max_distance_m is not None:
            distance_filter = "WHERE ST_DWithin(p.geom, q.geom, :max_distance_m)"
        statement = text(
            f"""
            WITH q AS (SELECT {query_geom} AS geom)
            SELECT
                p.*,
                ST_Distance(p.geom, q.geom) AS distance_m
            FROM {table} AS p, q
            {distance_filter}
            ORDER BY p.geom <-> q.geom
            LIMIT 1
            """
        )
        params = {
            "x": x,
            "y": y,
            "input_srid": input_srid,
            "srid": self.srid,
            "max_distance_m": max_distance_m,
        }
        with self.engine.connect() as connection:
            row = connection.execute(statement, params).mappings().first()
        return _offline_result(row) if row is not None else None

    def _upsert_navigation_records(
        self,
        records: Iterable[NavigationBuildingRecord],
        *,
        batch_size: int,
        source: str,
    ) -> AddressPointLoadResult:
        loaded = 0
        skipped = 0
        batch: list[dict[str, Any]] = []
        for record in records:
            row = _address_point_row(record, source=source, srid=self.srid)
            if row is None:
                skipped += 1
                continue
            batch.append(row)
            if len(batch) >= batch_size:
                loaded += self._upsert_rows(batch)
                batch = []
        if batch:
            loaded += self._upsert_rows(batch)
        return AddressPointLoadResult(loaded=loaded, skipped=skipped)

    def _upsert_rows(self, rows: Sequence[dict[str, Any]]) -> int:
        if not rows:
            return 0
        with self.engine.begin() as connection:
            if self.engine.dialect.name == "postgresql":
                statement = pg_insert(self.table).values(list(rows))
                update_values = {
                    column.name: getattr(statement.excluded, column.name)
                    for column in self.table.columns
                    if column.name != "building_management_number"
                }
                connection.execute(
                    statement.on_conflict_do_update(
                        index_elements=[self.table.c.building_management_number],
                        set_=update_values,
                    )
                )
            else:
                connection.execute(insert(self.table), list(rows))
        return len(rows)

    def _delete_management_numbers(self, values: Sequence[str]) -> int:
        if not values:
            return 0
        with self.engine.begin() as connection:
            connection.execute(
                self.table.delete().where(self.table.c.building_management_number.in_(values))
            )
        return len(values)


class VWorldReverseGeocoder:
    """선택 의존성인 ``python-vworld-api`` 패키지를 사용하는 리버스 지오코더."""

    def __init__(
        self,
        client: Any | None = None,
        *,
        api_key: str | None = None,
        domain: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        if client is not None:
            self.client = client
            return
        try:
            VworldClient = _vworld_client_class()
        except ImportError as exc:
            raise KrAddrRequestError(
                "VWorld 리버스 지오코딩에는 python-vworld-api가 필요합니다. "
                "https://github.com/digitie/python-vworld-api 에서 설치하세요."
            ) from exc
        self.client = VworldClient(api_key=api_key, domain=domain, timeout=timeout)

    @classmethod
    def from_env(cls, **kwargs: Any) -> VWorldReverseGeocoder:
        try:
            VworldClient = _vworld_client_class()
        except ImportError as exc:
            raise KrAddrRequestError(
                "VWorld 리버스 지오코딩에는 python-vworld-api가 필요합니다. "
                "https://github.com/digitie/python-vworld-api 에서 설치하세요."
            ) from exc
        return cls(client=VworldClient.from_env(**kwargs))

    @classmethod
    def from_env_file(cls, path: str | Path = ".env", **kwargs: Any) -> VWorldReverseGeocoder:
        try:
            VworldClient = _vworld_client_class()
        except ImportError as exc:
            raise KrAddrRequestError(
                "VWorld 리버스 지오코딩에는 python-vworld-api가 필요합니다. "
                "https://github.com/digitie/python-vworld-api 에서 설치하세요."
            ) from exc
        return cls(client=VworldClient.from_env_file(path, **kwargs))

    def reverse_geocode(
        self,
        *,
        lon: float,
        lat: float,
        type: str = "both",
        zipcode: bool = True,
        simple: bool = False,
        crs: str = "EPSG:4326",
    ) -> tuple[ReverseGeocodeResult, ...]:
        payload = self.client.reverse_geocode_latlon(
            lat,
            lon,
            type=type,
            zipcode=zipcode,
            simple=simple,
            crs=crs,
        )
        return tuple(
            _vworld_result(row, lon=lon, lat=lat, crs=crs)
            for row in _vworld_rows(payload)
        )

    def reverse_road_address(
        self,
        *,
        lon: float,
        lat: float,
        zipcode: bool = True,
        simple: bool = False,
        crs: str = "EPSG:4326",
    ) -> ReverseGeocodeResult | None:
        results = self.reverse_geocode(
            lon=lon,
            lat=lat,
            type="both",
            zipcode=zipcode,
            simple=simple,
            crs=crs,
        )
        for result in results:
            if result.road_address:
                return result
        return results[0] if results else None


class ReverseGeocoder:
    """오프라인 조회를 우선하고 필요하면 VWorld API로 보완하는 리버스 지오코더."""

    def __init__(
        self,
        *,
        offline_store: RoadAddressPointStore | None = None,
        vworld: VWorldReverseGeocoder | None = None,
        max_offline_distance_m: float | None = 50.0,
    ) -> None:
        self.offline_store = offline_store
        self.vworld = vworld
        self.max_offline_distance_m = max_offline_distance_m

    def reverse_road_address(self, *, lon: float, lat: float) -> ReverseGeocodeResult | None:
        if self.offline_store is not None:
            result = self.offline_store.nearest_road_address(
                lon=lon,
                lat=lat,
                max_distance_m=self.max_offline_distance_m,
            )
            if result is not None:
                return result
        if self.vworld is not None:
            return self.vworld.reverse_road_address(lon=lon, lat=lat)
        return None


def iter_navigation_building_records(
    path: str | Path | bytes,
    *,
    encoding: str | None = None,
) -> Iterator[NavigationBuildingRecord]:
    """TXT 또는 ZIP 바이트에서 Juso 내비게이션용DB 건물정보 레코드를 스트리밍한다."""

    for member in _iter_text_members(_content_bytes(path)):
        for line in _iter_decoded_lines(member.content, encoding=encoding):
            if not line.strip():
                continue
            parts = _split_line(line)
            if _is_no_data_parts(parts):
                continue
            if len(parts) < len(NAVIGATION_BUILDING_COLUMNS):
                continue
            values = parts[: len(NAVIGATION_BUILDING_COLUMNS)]
            yield NavigationBuildingRecord(
                **dict(zip(NAVIGATION_BUILDING_COLUMNS, values, strict=True)),
                source_member=member.name,
                raw={"source_member": member.name},
            )


def load_navigation_building_records(
    path: str | Path | bytes,
    *,
    encoding: str | None = None,
) -> list[NavigationBuildingRecord]:
    """TXT 또는 ZIP 바이트에서 내비게이션용DB 건물정보 레코드를 모두 읽어온다."""

    return list(iter_navigation_building_records(path, encoding=encoding))


def make_address_point_metadata(*, schema: str | None = "public", srid: int = 5179) -> MetaData:
    metadata = MetaData(schema=schema)
    Table(
        ROAD_ADDRESS_POINT_TABLE,
        metadata,
        Column("building_management_number", String(30), primary_key=True),
        Column("legal_dong_code", String(10), nullable=False),
        Column("sido_name", String(40), nullable=False, default=""),
        Column("sigungu_name", String(40), nullable=False, default=""),
        Column("eup_myeon_dong_name", String(40), nullable=False, default=""),
        Column("road_name_code", String(12), nullable=False),
        Column("road_name", String(80), nullable=False, default=""),
        Column("underground_yn", String(1), nullable=False),
        Column("building_main_no", String(5), nullable=False),
        Column("building_sub_no", String(5), nullable=False),
        Column("postal_code", String(5), nullable=False, default=""),
        Column("road_address", String(300), nullable=False, default=""),
        Column("building_name", String(200), nullable=False, default=""),
        Column("x", Float, nullable=False),
        Column("y", Float, nullable=False),
        Column("coordinate_source", String(30), nullable=False),
        Column("change_reason_code", String(2), nullable=False, default=""),
        Column("source", String(300), nullable=False, default=""),
        Column("loaded_at", DateTime(timezone=True), nullable=False),
        Column("geom", _point_geometry_type(srid), nullable=False),
        Index("ix_road_address_points_legal_dong", "legal_dong_code"),
        Index("ix_road_address_points_road_lookup", "road_name_code", "building_main_no"),
        Index("ix_road_address_points_source", "coordinate_source"),
    )
    return metadata


def _address_point_row(
    record: NavigationBuildingRecord,
    *,
    source: str,
    srid: int,
) -> dict[str, Any] | None:
    xy = record.point_xy()
    if xy is None or not record.building_management_number or record.is_deleted:
        return None
    x, y = xy
    return {
        "building_management_number": record.building_management_number,
        "legal_dong_code": record.legal_dong_code,
        "sido_name": record.sido_name,
        "sigungu_name": record.sigungu_name,
        "eup_myeon_dong_name": record.eup_myeon_dong_name,
        "road_name_code": record.road_name_code,
        "road_name": record.road_name,
        "underground_yn": record.underground_yn,
        "building_main_no": record.building_main_no,
        "building_sub_no": record.building_sub_no,
        "postal_code": record.postal_code,
        "road_address": record.road_address,
        "building_name": record.building_name,
        "x": x,
        "y": y,
        "coordinate_source": "entrance" if _xy(record.entrance_x, record.entrance_y) else "center",
        "change_reason_code": record.change_reason_code,
        "source": source,
        "loaded_at": datetime.now(UTC),
        "geom": _point_element(x, y, srid),
    }


def _offline_result(row: RowMapping) -> ReverseGeocodeResult:
    return ReverseGeocodeResult(
        address_type="road",
        road_address=str(row["road_address"]),
        postal_code=str(row["postal_code"] or "") or None,
        legal_dong_code=str(row["legal_dong_code"]),
        road_name_code=str(row["road_name_code"]),
        building_management_number=str(row["building_management_number"]),
        building_name=str(row["building_name"] or "") or None,
        x=float(row["x"]),
        y=float(row["y"]),
        crs="EPSG:5179",
        distance_m=float(row["distance_m"]) if row.get("distance_m") is not None else None,
        source="juso_navigation_db",
        raw=dict(row),
    )


def _vworld_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    root = payload.get("response", payload)
    if not isinstance(root, Mapping):
        raise KrAddrParseError("VWorld 응답 최상위 값이 객체가 아닙니다")
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
    raise KrAddrParseError("VWorld response.result가 객체 또는 목록이 아닙니다")


def _vworld_result(
    row: Mapping[str, Any],
    *,
    lon: float,
    lat: float,
    crs: str,
) -> ReverseGeocodeResult:
    raw_address = row.get("address")
    address: Mapping[str, Any] = raw_address if isinstance(raw_address, Mapping) else {}
    address_type = (_text(row, "type") or _text(row, "category") or "").lower()
    text_value = _text(row, "text")
    road_address = _text(row, "roadAddr") or _text(address, "road")
    parcel_address = _text(row, "jibunAddr") or _text(address, "parcel")
    if address_type == "road" and road_address is None:
        road_address = text_value
    elif address_type == "parcel" and parcel_address is None:
        parcel_address = text_value
    elif road_address is None and parcel_address is None:
        road_address = text_value
    return ReverseGeocodeResult(
        address_type=address_type or ("road" if road_address else "parcel"),
        road_address=road_address,
        parcel_address=parcel_address,
        postal_code=_text(row, "zipcode") or _text(row, "zipNo") or _text(address, "zipcode"),
        x=lon,
        y=lat,
        crs=crs,
        source="vworld",
        raw=row,
    )


def _point_geometry_type(srid: int) -> Any:
    try:
        from geoalchemy2 import Geometry
    except ImportError as exc:
        raise RuntimeError("오프라인 리버스 지오코딩에는 geoalchemy2가 필요합니다") from exc
    return Geometry("POINT", srid=srid, spatial_index=True)


def _point_element(x: float, y: float, srid: int) -> Any:
    try:
        from geoalchemy2 import WKTElement
    except ImportError as exc:
        raise RuntimeError("오프라인 리버스 지오코딩에는 geoalchemy2가 필요합니다") from exc
    return WKTElement(f"POINT({x} {y})", srid=srid)


def _vworld_client_class() -> Any:
    module: Any = import_module("vworld")
    return module.VworldClient


def _xy(x: str, y: str) -> tuple[float, float] | None:
    x_value = _float_or_none(x)
    y_value = _float_or_none(y)
    if x_value is None or y_value is None:
        return None
    return (x_value, y_value)


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


def _text(raw: Mapping[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _is_no_data_parts(parts: list[str]) -> bool:
    return len(parts) == 1 and parts[0].strip().lower().replace(" ", "") in {"nodata", "no_data"}


def _source_name(path: str | Path | bytes) -> str:
    if isinstance(path, bytes):
        return "bytes"
    return str(path)


def _table_key(name: str, schema: str | None) -> str:
    return f"{schema}.{name}" if schema else name


def _qualified_name(name: str, schema: str | None) -> str:
    return f"{_quote_ident(schema)}.{_quote_ident(name)}" if schema else _quote_ident(name)


def _quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'
