"""PostgreSQL/PostGIS 데이터베이스 접근 계층."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import geopandas as gpd
import sqlalchemy as sa
from geoalchemy2 import Geometry
from shapely.geometry import MultiPolygon, Polygon, shape

from .config import load_settings


metadata = sa.MetaData()

road_address_table = sa.Table(
    "address_serving_juso_road_address",
    metadata,
    sa.Column("road_address_management_no", sa.String, primary_key=True),
    sa.Column("legal_dong_code", sa.String),
    sa.Column("road_name_code", sa.String),
    sa.Column("sido_name", sa.String),
    sa.Column("sigungu_name", sa.String),
    sa.Column("legal_eupmyeondong_name", sa.String),
    sa.Column("legal_ri_name", sa.String),
    sa.Column("road_name", sa.String),
    sa.Column("mountain_yn", sa.String),
    sa.Column("jibun_main_no", sa.String),
    sa.Column("jibun_sub_no", sa.String),
    sa.Column("underground_yn", sa.String),
    sa.Column("building_main_no", sa.String),
    sa.Column("building_sub_no", sa.String),
    sa.Column("postal_code", sa.String),
    sa.Column("full_legal_dong_name", sa.String),
    sa.Column("full_road_address", sa.String),
    sa.Column("is_active", sa.Boolean),
)

boundary_table = sa.Table(
    "region_serving_boundary",
    metadata,
    sa.Column("boundary_level", sa.String),
    sa.Column("region_code", sa.String),
    sa.Column("region_name", sa.String),
    sa.Column("sido_code", sa.String),
    sa.Column("sigungu_code", sa.String),
    sa.Column("legal_dong_code", sa.String),
    sa.Column("full_region_name", sa.String),
    sa.Column("geom", Geometry("MULTIPOLYGON", srid=4326)),
)


@lru_cache(maxsize=1)
def engine() -> sa.Engine:
    """SQLAlchemy 2 엔진을 한 번만 만든다."""

    settings = load_settings()
    return sa.create_engine(settings.database_url, future=True, pool_pre_ping=True)


def health() -> dict[str, Any]:
    """데이터베이스와 GIS 라이브러리 상태를 확인한다."""

    with engine().connect() as connection:
        postgis_version = connection.scalar(sa.text("select postgis_full_version()"))
        road_count = connection.scalar(
            sa.text(
                """
                select count(*)
                from public.address_serving_juso_road_address
                where is_active is true
                """
            )
        )
        boundary_count = connection.scalar(sa.text("select count(*) from public.region_serving_boundary"))
    return {
        "ok": True,
        "postgis": postgis_version,
        "road_address_count": int(road_count or 0),
        "boundary_count": int(boundary_count or 0),
        "sqlalchemy": sa.__version__,
        "geopandas": gpd.__version__,
    }


def list_addresses(
    *,
    query: str = "",
    scope: str = "all",
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """도로명주소 목록을 PostGIS 경계 중심점과 함께 조회한다."""

    normalized_page = max(page, 1)
    normalized_page_size = max(1, min(page_size, 100))
    offset = (normalized_page - 1) * normalized_page_size
    where_sql, params = _where_clause(query=query, scope=scope)
    params.update({"limit": normalized_page_size, "offset": offset})

    items_sql = sa.text(
        f"""
        select
            r.road_address_management_no,
            r.legal_dong_code,
            r.road_name_code,
            r.sido_name,
            r.sigungu_name,
            r.legal_eupmyeondong_name,
            r.legal_ri_name,
            r.road_name,
            r.mountain_yn,
            r.jibun_main_no,
            r.jibun_sub_no,
            r.underground_yn,
            r.building_main_no,
            r.building_sub_no,
            r.postal_code,
            r.full_legal_dong_name,
            r.full_road_address,
            b.boundary_level,
            b.full_region_name as boundary_name,
            st_x(st_pointonsurface(b.geom)) as lng,
            st_y(st_pointonsurface(b.geom)) as lat,
            st_asgeojson(st_simplifypreservetopology(b.geom, 0.001), 5) as boundary_geojson
        from public.address_serving_juso_road_address as r
        left join lateral (
            select *
            from public.region_serving_boundary as b
            where
                (
                    b.boundary_level = 'legal_dong'
                    and b.legal_dong_code = r.legal_dong_code
                )
                or (
                    b.boundary_level = 'sigungu'
                    and b.sigungu_code = substring(r.legal_dong_code from 1 for 5)
                )
                or (
                    b.boundary_level = 'sido'
                    and b.sido_code = substring(r.legal_dong_code from 1 for 2)
                )
            order by
                case b.boundary_level
                    when 'legal_dong' then 1
                    when 'sigungu' then 2
                    else 3
                end
            limit 1
        ) as b on true
        where {where_sql}
        order by r.road_address_management_no
        limit :limit offset :offset
        """
    )
    count_sql = sa.text(
        f"""
        select count(*)
        from public.address_serving_juso_road_address as r
        where {where_sql}
        """
    )

    with engine().connect() as connection:
        rows = connection.execute(items_sql, params).mappings().all()
        total = int(connection.scalar(count_sql, params) or 0)

    return {
        "items": [_row_to_address(row) for row in rows],
        "page": normalized_page,
        "page_size": normalized_page_size,
        "total": total,
        "has_next": offset + normalized_page_size < total,
    }


def _where_clause(*, query: str, scope: str) -> tuple[str, dict[str, Any]]:
    conditions = ["r.is_active is true"]
    params: dict[str, Any] = {}
    value = query.strip()
    if not value:
        return " and ".join(conditions), params

    like = f"%{_escape_like(value.lower())}%"
    prefix = f"{_escape_like(value)}%"
    params.update({"like": like, "prefix": prefix})
    if scope == "road":
        conditions.append(
            """
            (
                lower(coalesce(r.full_road_address, '')) like :like escape '\\'
                or lower(coalesce(r.road_name, '')) like :like escape '\\'
            )
            """
        )
    elif scope == "jibun":
        conditions.append(
            """
            (
                lower(coalesce(r.full_legal_dong_name, '')) like :like escape '\\'
                or coalesce(r.legal_dong_code, '') like :prefix escape '\\'
            )
            """
        )
    elif scope == "code":
        conditions.append(
            """
            (
                coalesce(r.legal_dong_code, '') like :prefix escape '\\'
                or coalesce(r.road_name_code, '') like :prefix escape '\\'
                or coalesce(r.road_address_management_no, '') like :prefix escape '\\'
                or coalesce(r.postal_code, '') like :prefix escape '\\'
            )
            """
        )
    else:
        conditions.append(
            """
            (
                lower(coalesce(r.full_road_address, '')) like :like escape '\\'
                or lower(coalesce(r.full_legal_dong_name, '')) like :like escape '\\'
                or coalesce(r.legal_dong_code, '') like :prefix escape '\\'
                or coalesce(r.road_name_code, '') like :prefix escape '\\'
                or coalesce(r.road_address_management_no, '') like :prefix escape '\\'
                or coalesce(r.postal_code, '') like :prefix escape '\\'
            )
            """
        )
    return " and ".join(conditions), params


def _row_to_address(row: sa.RowMapping) -> dict[str, Any]:
    legal_name = _join(
        row["sido_name"],
        row["sigungu_name"],
        row["legal_eupmyeondong_name"],
        row["legal_ri_name"],
    )
    jibun = _jibun_text(
        legal_name,
        row["mountain_yn"],
        row["jibun_main_no"],
        row["jibun_sub_no"],
    )
    boundary = _boundary_points(row["boundary_geojson"])
    lat = row["lat"]
    lng = row["lng"]
    return {
        "id": row["road_address_management_no"],
        "title": row["full_road_address"] or jibun or row["road_address_management_no"],
        "category": "road",
        "roadAddress": row["full_road_address"] or "",
        "jibunAddress": jibun,
        "postalCode": row["postal_code"] or "",
        "legalDongCode": row["legal_dong_code"] or "",
        "roadNameCode": row["road_name_code"] or "",
        "pnu": _pnu(row),
        "coordinate": {
            "lat": float(lat) if lat is not None else 37.5665,
            "lng": float(lng) if lng is not None else 126.978,
        },
        "boundary": boundary,
        "radiusMeters": 150,
        "updatedAt": "",
        "tags": [tag for tag in [row["sido_name"], row["sigungu_name"], row["boundary_level"]] if tag],
        "boundaryName": row["boundary_name"] or "",
        "boundaryLevel": row["boundary_level"] or "",
        "coordinateSource": "postgis_boundary" if lat is not None and lng is not None else "fallback",
    }


def _boundary_points(value: Any) -> list[dict[str, float]]:
    if not value:
        return []
    geometry = shape(json.loads(str(value)))
    polygon: Polygon | None = None
    if isinstance(geometry, Polygon):
        polygon = geometry
    elif isinstance(geometry, MultiPolygon):
        polygon = max(geometry.geoms, key=lambda item: item.area)
    if polygon is None:
        return []
    return [{"lng": float(x), "lat": float(y)} for x, y in polygon.exterior.coords]


def _pnu(row: sa.RowMapping) -> str:
    legal_dong_code = str(row["legal_dong_code"] or "")
    mountain_yn = str(row["mountain_yn"] or "0")[:1]
    main_no = str(row["jibun_main_no"] or "0").zfill(4)
    sub_no = str(row["jibun_sub_no"] or "0").zfill(4)
    return legal_dong_code + mountain_yn + main_no + sub_no


def _jibun_text(
    legal_name: str,
    mountain_yn: Any,
    main_no: Any,
    sub_no: Any,
) -> str:
    main_text = str(main_no or "0").lstrip("0") or "0"
    sub_text = str(sub_no or "0").lstrip("0") or "0"
    lot = main_text if sub_text == "0" else f"{main_text}-{sub_text}"
    if str(mountain_yn or "0") == "1":
        lot = f"산 {lot}"
    return _join(legal_name, lot)


def _join(*values: Any) -> str:
    return " ".join(str(value).strip() for value in values if str(value or "").strip())


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
