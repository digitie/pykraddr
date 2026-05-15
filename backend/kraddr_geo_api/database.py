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
PERFORMANCE_SQL = (
    "create extension if not exists pg_trgm",
    """
    create index if not exists ix_juso_road_active_mgmt
    on public.address_serving_juso_road_address (road_address_management_no)
    where is_active is true
    """,
    """
    create index if not exists ix_juso_road_legal_prefix
    on public.address_serving_juso_road_address (legal_dong_code text_pattern_ops)
    where is_active is true
    """,
    """
    create index if not exists ix_juso_road_legal_mgmt_prefix
    on public.address_serving_juso_road_address
    (legal_dong_code text_pattern_ops, road_address_management_no)
    where is_active is true
    """,
    """
    create index if not exists ix_juso_road_road_code_prefix
    on public.address_serving_juso_road_address (road_name_code text_pattern_ops)
    where is_active is true
    """,
    """
    create index if not exists ix_juso_road_mgmt_prefix
    on public.address_serving_juso_road_address (road_address_management_no text_pattern_ops)
    where is_active is true
    """,
    """
    create index if not exists ix_juso_road_postal_prefix
    on public.address_serving_juso_road_address (postal_code text_pattern_ops)
    where is_active is true
    """,
    """
    create index if not exists ix_juso_road_full_road_trgm
    on public.address_serving_juso_road_address
    using gin (lower(coalesce(full_road_address, '')) gin_trgm_ops)
    where is_active is true
    """,
    """
    create index if not exists ix_juso_road_name_trgm
    on public.address_serving_juso_road_address
    using gin (lower(coalesce(road_name, '')) gin_trgm_ops)
    where is_active is true
    """,
    """
    create index if not exists ix_juso_road_full_legal_trgm
    on public.address_serving_juso_road_address
    using gin (lower(coalesce(full_legal_dong_name, '')) gin_trgm_ops)
    where is_active is true
    """,
    """
    create index if not exists ix_juso_road_search_all_trgm
    on public.address_serving_juso_road_address
    using gin (
        (lower(coalesce(full_road_address, '') || ' ' || coalesce(full_legal_dong_name, '')))
        gin_trgm_ops
    )
    where is_active is true
    """,
    """
    create index if not exists ix_juso_road_search_all_compact_trgm
    on public.address_serving_juso_road_address
    using gin (
        (replace(
            lower(coalesce(full_road_address, '') || ' ' || coalesce(full_legal_dong_name, '')),
            ' ',
            ''
        ))
        gin_trgm_ops
    )
    where is_active is true
    """,
    """
    create index if not exists ix_juso_road_search_road_trgm
    on public.address_serving_juso_road_address
    using gin (
        (lower(coalesce(full_road_address, '') || ' ' || coalesce(road_name, '')))
        gin_trgm_ops
    )
    where is_active is true
    """,
    """
    create index if not exists ix_juso_road_search_road_compact_trgm
    on public.address_serving_juso_road_address
    using gin (
        (replace(lower(coalesce(full_road_address, '') || ' ' || coalesce(road_name, '')), ' ', ''))
        gin_trgm_ops
    )
    where is_active is true
    """,
    """
    create index if not exists ix_juso_road_search_legal_compact_trgm
    on public.address_serving_juso_road_address
    using gin ((replace(lower(coalesce(full_legal_dong_name, '')), ' ', '')) gin_trgm_ops)
    where is_active is true
    """,
    """
    create index if not exists ix_region_boundary_legal_lookup
    on public.region_serving_boundary (legal_dong_code)
    where boundary_level = 'legal_dong'
    """,
    """
    create index if not exists ix_region_boundary_sigungu_lookup
    on public.region_serving_boundary (sigungu_code)
    where boundary_level = 'sigungu'
    """,
    """
    create index if not exists ix_region_boundary_sido_lookup
    on public.region_serving_boundary (sido_code)
    where boundary_level = 'sido'
    """,
)

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
    db_engine = sa.create_engine(settings.database_url, future=True, pool_pre_ping=True)
    ensure_performance_objects(db_engine)
    return db_engine


def ensure_performance_objects(db_engine: sa.Engine | None = None) -> None:
    """주소 검색과 경계 조인을 위한 확장/인덱스를 준비한다."""

    target = db_engine or engine()
    with target.begin() as connection:
        for statement in PERFORMANCE_SQL:
            connection.execute(sa.text(statement))


def health() -> dict[str, Any]:
    """데이터베이스와 GIS 라이브러리 상태를 확인한다."""

    with engine().connect() as connection:
        postgis_version = connection.scalar(sa.text("select postgis_full_version()"))
        boundary_count = connection.scalar(
            sa.text("select count(*) from public.region_serving_boundary")
        )
    return {
        "ok": True,
        "postgis": postgis_version,
        "road_address_count": active_road_address_count(),
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

    region_ranges: list[tuple[str, str]] = []
    if query.strip():
        with engine().connect() as connection:
            region_ranges = _region_code_ranges(connection, query=query, scope=scope)
    where_sql, params = _where_clause(
        query=query,
        scope=scope,
        region_ranges=region_ranges,
    )
    params.update({"limit": normalized_page_size + 1, "offset": offset})
    order_sql = (
        "r.legal_dong_code, r.road_address_management_no"
        if region_ranges
        else "r.road_address_management_no"
    )

    items_sql = sa.text(
        f"""
        with page_rows as (
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
                r.full_road_address
            from public.address_serving_juso_road_address as r
            where {where_sql}
            order by {order_sql}
            limit :limit offset :offset
        )
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
        from page_rows as r
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
        order by {order_sql}
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
        fetched_rows = connection.execute(items_sql, params).mappings().all()
        rows = fetched_rows[:normalized_page_size]
        has_next = len(fetched_rows) > normalized_page_size
        total, total_is_estimate = _total_for_query(
            connection,
            query=query,
            offset=offset,
            row_count=len(rows),
            has_next=has_next,
            count_sql=count_sql,
            params=params,
        )

    return {
        "items": [_row_to_address(row) for row in rows],
        "page": normalized_page,
        "page_size": normalized_page_size,
        "total": total,
        "total_is_estimate": total_is_estimate,
        "has_next": has_next,
    }


@lru_cache(maxsize=1)
def active_road_address_count() -> int:
    """초기 전체 목록 표시용 활성 주소 건수를 프로세스 안에서 캐시한다."""

    with engine().connect() as connection:
        return int(
            connection.scalar(
                sa.text(
                    """
                    select count(*)
                    from public.address_serving_juso_road_address
                    where is_active is true
                    """
                )
            )
            or 0
        )


def _total_for_query(
    connection: sa.Connection,
    *,
    query: str,
    offset: int,
    row_count: int,
    has_next: bool,
    count_sql: sa.TextClause,
    params: dict[str, Any],
) -> tuple[int, bool]:
    """검색 중에는 비싼 전체 count 대신 페이지 탐색에 필요한 하한값을 반환한다."""

    if query.strip():
        return offset + row_count + (1 if has_next else 0), has_next
    if where_sql_is_active_only(query):
        return active_road_address_count(), False
    return int(connection.scalar(count_sql, params) or 0), False


def where_sql_is_active_only(query: str) -> bool:
    return not query.strip()


def _where_clause(
    *,
    query: str,
    scope: str,
    region_ranges: list[tuple[str, str]] | None = None,
) -> tuple[str, dict[str, Any]]:
    conditions = ["r.is_active is true"]
    params: dict[str, Any] = {}
    value = query.strip()
    if not value:
        return " and ".join(conditions), params

    if region_ranges:
        conditions.append(_region_range_clause(region_ranges, params))
        return " and ".join(conditions), params

    like = f"%{_escape_like(value.lower())}%"
    compact_value = _compact_search_value(value)
    params["like"] = like
    if _use_compact_search(compact_value):
        params["compact_like"] = f"%{_escape_like(compact_value)}%"
    if _use_code_prefix_search(value):
        params["prefix"] = f"{_escape_like(value)}%"

    if scope == "road":
        predicates = [
            _road_search_expression() + " like :like escape '\\'",
        ]
        if "compact_like" in params:
            predicates.append(_road_compact_search_expression() + " like :compact_like escape '\\'")
        conditions.append(_or_clause(predicates))
    elif scope == "jibun":
        predicates = [
            "lower(coalesce(r.full_legal_dong_name, '')) like :like escape '\\'",
        ]
        if "compact_like" in params:
            predicates.append(
                "replace(lower(coalesce(r.full_legal_dong_name, '')), ' ', '') "
                "like :compact_like escape '\\'"
            )
        if "prefix" in params:
            predicates.append("r.legal_dong_code like :prefix escape '\\'")
        conditions.append(_or_clause(predicates))
    elif scope == "code":
        if "prefix" not in params:
            conditions.append("false")
        else:
            conditions.append(_code_prefix_clause())
    else:
        predicates = [
            _all_search_expression() + " like :like escape '\\'",
        ]
        if "compact_like" in params:
            predicates.append(_all_compact_search_expression() + " like :compact_like escape '\\'")
        if "prefix" in params:
            predicates.extend(
                [
                    "r.legal_dong_code like :prefix escape '\\'",
                    "r.road_name_code like :prefix escape '\\'",
                    "r.road_address_management_no like :prefix escape '\\'",
                    "r.postal_code like :prefix escape '\\'",
                ]
            )
        conditions.append(_or_clause(predicates))
    return " and ".join(conditions), params


def _region_code_ranges(
    connection: sa.Connection,
    *,
    query: str,
    scope: str,
) -> list[tuple[str, str]]:
    value = query.strip()
    compact_value = _compact_search_value(value)
    if (
        scope not in {"all", "jibun"}
        or len(compact_value) < 2
        or _use_code_prefix_search(value)
        or not _looks_like_region_query(compact_value)
    ):
        return []

    rows = connection.execute(
        sa.text(
            """
            select
                boundary_level,
                sido_code,
                sigungu_code,
                legal_dong_code
            from public.region_serving_boundary
            where
                lower(coalesce(full_region_name, '')) like :like escape '\\'
                or replace(lower(coalesce(full_region_name, '')), ' ', '')
                    like :compact_like escape '\\'
                or lower(coalesce(region_name, '')) like :like escape '\\'
            order by
                case boundary_level
                    when 'sido' then 1
                    when 'sigungu' then 2
                    else 3
                end,
                length(coalesce(full_region_name, ''))
            limit 20
            """
        ),
        {
            "like": f"%{_escape_like(value.lower())}%",
            "compact_like": f"%{_escape_like(compact_value)}%",
        },
    ).mappings().all()
    if not rows:
        return []

    top_rank = _boundary_rank(str(rows[0]["boundary_level"] or ""))
    top_rows = [
        row for row in rows if _boundary_rank(str(row["boundary_level"] or "")) == top_rank
    ]
    if top_rank != 1 and (len(compact_value) < 5 or len(top_rows) > 10):
        return []

    prefixes = [_region_prefix(row) for row in top_rows]
    unique_prefixes = sorted({prefix for prefix in prefixes if prefix})
    return [(prefix, _next_text_prefix(prefix)) for prefix in unique_prefixes]


def _boundary_rank(boundary_level: str) -> int:
    if boundary_level == "sido":
        return 1
    if boundary_level == "sigungu":
        return 2
    return 3


def _region_prefix(row: sa.RowMapping) -> str:
    boundary_level = str(row["boundary_level"] or "")
    if boundary_level == "sido":
        return str(row["sido_code"] or "")[:2]
    if boundary_level == "sigungu":
        return str(row["sigungu_code"] or "")[:5]
    return str(row["legal_dong_code"] or "")[:10]


def _region_range_clause(ranges: list[tuple[str, str]], params: dict[str, Any]) -> str:
    predicates: list[str] = []
    for index, (start, end) in enumerate(ranges):
        start_key = f"region_start_{index}"
        end_key = f"region_end_{index}"
        params[start_key] = start
        params[end_key] = end
        predicates.append(
            f"(r.legal_dong_code >= :{start_key} and r.legal_dong_code < :{end_key})"
        )
    return _or_clause(predicates)


def _next_text_prefix(value: str) -> str:
    return value[:-1] + chr(ord(value[-1]) + 1)


def _all_search_expression() -> str:
    return "lower(coalesce(r.full_road_address, '') || ' ' || coalesce(r.full_legal_dong_name, ''))"


def _all_compact_search_expression() -> str:
    return (
        "replace(lower(coalesce(r.full_road_address, '') || ' ' || "
        "coalesce(r.full_legal_dong_name, '')), ' ', '')"
    )


def _road_search_expression() -> str:
    return "lower(coalesce(r.full_road_address, '') || ' ' || coalesce(r.road_name, ''))"


def _road_compact_search_expression() -> str:
    return (
        "replace(lower(coalesce(r.full_road_address, '') || ' ' || "
        "coalesce(r.road_name, '')), ' ', '')"
    )


def _code_prefix_clause() -> str:
    return _or_clause(
        [
            "r.legal_dong_code like :prefix escape '\\'",
            "r.road_name_code like :prefix escape '\\'",
            "r.road_address_management_no like :prefix escape '\\'",
            "r.postal_code like :prefix escape '\\'",
        ]
    )


def _or_clause(predicates: list[str]) -> str:
    return "(\n                " + "\n                or ".join(predicates) + "\n            )"


def _compact_search_value(value: str) -> str:
    return "".join(value.lower().split())


def _looks_like_region_query(compact_value: str) -> bool:
    if len(compact_value) <= 2:
        return True
    return any(
        hint in compact_value
        for hint in (
            "특별시",
            "광역시",
            "특별자치",
            "자치도",
            "자치시",
            "시",
            "군",
            "구",
            "읍",
            "면",
            "동",
            "리",
        )
    )


def _use_compact_search(compact_value: str) -> bool:
    return len(compact_value) >= 4


def _use_code_prefix_search(value: str) -> bool:
    return any(character.isdigit() for character in value)


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
        "tags": [
            tag
            for tag in [row["sido_name"], row["sigungu_name"], row["boundary_level"]]
            if tag
        ],
        "boundaryName": row["boundary_name"] or "",
        "boundaryLevel": row["boundary_level"] or "",
        "coordinateSource": (
            "postgis_boundary" if lat is not None and lng is not None else "fallback"
        ),
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
