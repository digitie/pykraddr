"""SQLite/SpatiaLite-backed address and geocoding queries."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import sqlalchemy as sa

from kraddr.geo import SpatialiteAddressStore

from .config import load_settings


@lru_cache(maxsize=1)
def store() -> SpatialiteAddressStore:
    settings = load_settings()
    return SpatialiteAddressStore(
        settings.spatialite_path,
        load_spatialite=True,
        vworld_api_key=settings.vworld_api_key,
        vworld_domain=settings.vworld_domain,
    )


def health() -> dict[str, Any]:
    """Return the backend and geocoding database status."""

    current = store()
    with current.engine.connect() as connection:
        boundary_count = int(
            connection.scalar(sa.text("select count(*) from juso_boundary_polygons")) or 0
        )
        sources = connection.execute(
            sa.text(
                """
                select source_dataset, count(*) as row_count
                from juso_address_points
                group by source_dataset
                order by source_dataset
                """
            )
        ).mappings().all()
    return {
        "ok": True,
        "mode": "sqlite_spatialite",
        "spatialite_path": str(load_settings().spatialite_path),
        "address_point_count": current.count_points(),
        "boundary_count": boundary_count,
        "sources": [dict(row) for row in sources],
        "spatialite_enabled": current.spatialite_enabled,
        "sqlalchemy": sa.__version__,
    }


def list_addresses(
    *,
    query: str = "",
    scope: str = "all",
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """Return address point candidates in the same shape used by the web UI."""

    normalized_page = max(page, 1)
    normalized_page_size = max(1, min(page_size, 100))
    offset = (normalized_page - 1) * normalized_page_size
    current = store()
    with current.engine.connect() as connection:
        if query.strip():
            rows, total, has_next = _search_address_rows(
                connection,
                query=query,
                scope=scope,
                page_size=normalized_page_size,
                offset=offset,
            )
        else:
            params = {"limit": normalized_page_size + 1, "offset": offset}
            rows = connection.execute(
                sa.text(
                    """
                    select *
                    from juso_address_points
                    order by
                        source_priority,
                        road_name_code,
                        building_main_no,
                        building_sub_no,
                        point_id
                    limit :limit offset :offset
                    """
                ),
                params,
            ).mappings().all()
            has_next = len(rows) > normalized_page_size
            rows = rows[:normalized_page_size]
            total = int(
                connection.scalar(sa.text("select count(*) from juso_address_points")) or 0
            )
    return {
        "items": [_row_to_address(row) for row in rows],
        "page": normalized_page,
        "page_size": normalized_page_size,
        "total": total,
        "has_next": has_next,
    }


def geocode(
    *,
    query: str = "",
    road_name_code: str | None = None,
    legal_dong_code: str | None = None,
    underground_yn: str | None = None,
    building_main_no: str | int | None = None,
    building_sub_no: str | int | None = None,
    crs: str = "EPSG:4326",
    limit: int = 10,
) -> dict[str, Any]:
    candidates = store().get_coord(
        {
            "query": query or None,
            "rnMgtSn": road_name_code,
            "admCd": legal_dong_code,
            "udrtYn": underground_yn,
            "buldMnnm": building_main_no,
            "buldSlno": building_sub_no,
            "crs": crs,
            "limit": limit,
        }
    )
    return {
        "items": [item.model_dump(mode="json") for item in candidates],
        "total": len(candidates),
    }


def reverse_geocode(
    *,
    x: float,
    y: float,
    crs: str = "EPSG:4326",
    max_distance_m: float = 50.0,
) -> dict[str, Any]:
    candidate = store().get_address(
        {
            "x": x,
            "y": y,
            "crs": crs,
            "max_distance_m": max_distance_m,
        }
    )
    return {"item": candidate.model_dump(mode="json") if candidate else None}


def lookup_postal_code(zipcode: str, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
    candidates = store().lookup_postal_code({"zipNo": zipcode, "limit": limit, "offset": offset})
    return {
        "items": [item.model_dump(mode="json") for item in candidates],
        "total": len(candidates),
    }


_SEARCH_INDEXES = {
    "road_name": "ix_juso_points_road_name",
    "road_address": "ix_juso_points_road_address",
    "parcel_address": "ix_juso_points_parcel_address",
    "building_name": "ix_juso_points_building_name",
    "legal_dong_code": "ix_juso_points_legal_dong",
    "road_name_code": "ix_juso_points_road_lookup",
    "building_management_number": "ix_juso_points_building_mgmt",
    "postal_code": "ix_juso_points_postal_lookup",
}

_SEARCH_COLUMNS_BY_SCOPE = {
    "road": ("road_name", "road_address"),
    "jibun": ("parcel_address", "legal_dong_code"),
    "code": (
        "legal_dong_code",
        "road_name_code",
        "building_management_number",
        "postal_code",
    ),
    "all": (
        "road_name",
        "road_address",
        "parcel_address",
        "building_name",
        "legal_dong_code",
        "road_name_code",
        "building_management_number",
        "postal_code",
    ),
}
_FTS_COLUMNS_BY_SCOPE = {
    "road": ("road_name", "road_address"),
    "jibun": ("parcel_address",),
    "all": ("road_name", "road_address", "parcel_address", "building_name"),
}
_FTS_MIN_QUERY_LENGTH = 3


def _search_address_rows(
    connection: sa.Connection,
    *,
    query: str,
    scope: str,
    page_size: int,
    offset: int,
) -> tuple[list[sa.RowMapping], int, bool]:
    value = query.strip()
    if (
        scope in _FTS_COLUMNS_BY_SCOPE
        and len(value) >= _FTS_MIN_QUERY_LENGTH
        and _has_ready_fts_index(connection)
    ):
        fts_rows, fts_total, fts_has_next = _search_address_rows_fts(
            connection,
            query=value,
            scope=scope,
            page_size=page_size,
            offset=offset,
        )
        if fts_rows:
            return fts_rows, fts_total, fts_has_next

    prefix_end = _prefix_end(value)
    columns = _SEARCH_COLUMNS_BY_SCOPE.get(scope, _SEARCH_COLUMNS_BY_SCOPE["all"])
    rowid_queries = [
        f"""
        select rowid
        from juso_address_points indexed by {_SEARCH_INDEXES[column]}
        where {column} >= :prefix_start and {column} < :prefix_end
        """
        for column in columns
    ]
    rows = connection.execute(
        sa.text(
            f"""
            with candidate_rowids(rowid) as (
                {" union ".join(rowid_queries)}
            )
            select p.*
            from juso_address_points as p
            join candidate_rowids as c on p.rowid = c.rowid
            order by
                p.source_priority,
                p.road_name_code,
                p.building_main_no,
                p.building_sub_no,
                p.point_id
            limit :limit offset :offset
            """
        ),
        {
            "prefix_start": value,
            "prefix_end": prefix_end,
            "limit": page_size + 1,
            "offset": offset,
        },
    ).mappings().all()
    has_next = len(rows) > page_size
    rows = rows[:page_size]
    total = offset + len(rows) + (1 if has_next else 0)
    return list(rows), total, has_next


def _search_address_rows_fts(
    connection: sa.Connection,
    *,
    query: str,
    scope: str,
    page_size: int,
    offset: int,
) -> tuple[list[sa.RowMapping], int, bool]:
    match_query = _fts_match_query(query, scope=scope)
    rows = connection.execute(
        sa.text(
            """
            with candidate_rowids(rowid) as (
                select rowid
                from juso_address_fts
                where juso_address_fts match :match_query
            )
            select p.*
            from juso_address_points as p
            join candidate_rowids as c on p.rowid = c.rowid
            order by
                p.source_priority,
                p.road_name_code,
                p.building_main_no,
                p.building_sub_no,
                p.point_id
            limit :limit offset :offset
            """
        ),
        {"match_query": match_query, "limit": page_size + 1, "offset": offset},
    ).mappings().all()
    total = int(
        connection.scalar(
            sa.text(
                """
                select count(*)
                from juso_address_fts
                where juso_address_fts match :match_query
                """
            ),
            {"match_query": match_query},
        )
        or 0
    )
    has_next = offset + page_size < total
    rows = rows[:page_size]
    return list(rows), total, has_next


def _has_ready_fts_index(connection: sa.Connection) -> bool:
    exists = connection.scalar(
        sa.text("select 1 from sqlite_master where type = 'table' and name = 'juso_address_fts'")
    )
    if not exists:
        return False
    ready = connection.scalar(
        sa.text(
            """
            select 1
            from juso_spatial_metadata
            where key = 'address_search_index_ready'
            limit 1
            """
        )
    )
    return bool(ready)


def _fts_match_query(query: str, *, scope: str) -> str:
    escaped = query.replace('"', '""')
    phrase = f'"{escaped}"'
    columns = _FTS_COLUMNS_BY_SCOPE.get(scope)
    if not columns:
        return phrase
    return f"{{{' '.join(columns)}}} : {phrase}"


def _prefix_end(value: str) -> str:
    return f"{value[:-1]}{chr(ord(value[-1]) + 1)}"


def _row_to_address(row: sa.RowMapping) -> dict[str, Any]:
    lon, lat = _to_wgs84(row["x"], row["y"])
    return {
        "id": row["point_id"],
        "title": row["road_address"] or row["parcel_address"] or row["point_id"],
        "category": "road",
        "roadAddress": row["road_address"] or "",
        "jibunAddress": row["parcel_address"] or "",
        "postalCode": row["postal_code"] or "",
        "legalDongCode": row["legal_dong_code"] or "",
        "roadNameCode": row["road_name_code"] or "",
        "pnu": "",
        "coordinate": {"lat": lat, "lng": lon},
        "boundary": [],
        "radiusMeters": 40 if row["source_dataset"] == "location_summary" else 80,
        "updatedAt": "",
        "tags": [
            tag
            for tag in [row["sido_name"], row["sigungu_name"], row["source_dataset"]]
            if tag
        ],
        "boundaryName": "",
        "boundaryLevel": "",
        "coordinateSource": row["source_dataset"] or row["source"] or "sqlite_spatialite",
    }


def _to_wgs84(x: Any, y: Any) -> tuple[float, float]:
    try:
        transformer = _wgs84_transformer()
    except ImportError:
        return float(x), float(y)
    lon, lat = transformer.transform(float(x), float(y))
    return float(lon), float(lat)


@lru_cache(maxsize=1)
def _wgs84_transformer() -> Any:
    from pyproj import Transformer

    return Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
