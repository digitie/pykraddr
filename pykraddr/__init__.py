"""한국 주소 정보 API와 데이터 적재를 다루는 공개 진입점."""

from __future__ import annotations

from .client import KrAddrClient
from .data import (
    ROAD_NAME_KOREAN_DETAIL_SN,
    RoadNameAddressDataClient,
    archive_standard_date,
    iter_related_jibun_records,
    iter_road_name_address_records,
    load_related_jibun_records,
    load_road_name_address_records,
)
from .exceptions import (
    KrAddrAuthError,
    KrAddrError,
    KrAddrNoDataError,
    KrAddrParseError,
    KrAddrRateLimitError,
    KrAddrRequestError,
    KrAddrServerError,
)
from .legal_dong import (
    DATA_GO_KR_LEGAL_DONG_PAGE_URL,
    DataGoKrLegalDongClient,
    iter_legal_dong_records,
    load_legal_dong_records,
    records_from_openapi_rows,
)
from .models import (
    AddressCoordinate,
    AddressSearchResult,
    DatasetFile,
    DetailAddress,
    EnglishAddressSearchResult,
    JusoPage,
    LegalDongRecord,
    RelatedJibunRecord,
    RoadNameAddressKoreanRecord,
)
from .postgis import BoundaryLoadResult, PostGISLegalDongStore, make_postgis_metadata
from .reverse import (
    AddressPointLoadResult,
    NavigationBuildingRecord,
    ReverseGeocoder,
    ReverseGeocodeResult,
    RoadAddressPointStore,
    VWorldReverseGeocoder,
    iter_navigation_building_records,
    load_navigation_building_records,
    make_address_point_metadata,
)
from .store import RoadNameAddressStore

JusoClient = KrAddrClient

__all__ = [
    "AddressCoordinate",
    "AddressPointLoadResult",
    "AddressSearchResult",
    "BoundaryLoadResult",
    "DATA_GO_KR_LEGAL_DONG_PAGE_URL",
    "DataGoKrLegalDongClient",
    "DatasetFile",
    "DetailAddress",
    "EnglishAddressSearchResult",
    "JusoClient",
    "JusoPage",
    "KrAddrAuthError",
    "KrAddrClient",
    "KrAddrError",
    "KrAddrNoDataError",
    "KrAddrParseError",
    "KrAddrRateLimitError",
    "KrAddrRequestError",
    "KrAddrServerError",
    "LegalDongRecord",
    "NavigationBuildingRecord",
    "ROAD_NAME_KOREAN_DETAIL_SN",
    "RelatedJibunRecord",
    "ReverseGeocodeResult",
    "ReverseGeocoder",
    "RoadNameAddressDataClient",
    "RoadNameAddressKoreanRecord",
    "RoadNameAddressStore",
    "RoadAddressPointStore",
    "PostGISLegalDongStore",
    "VWorldReverseGeocoder",
    "archive_standard_date",
    "iter_related_jibun_records",
    "iter_legal_dong_records",
    "iter_navigation_building_records",
    "iter_road_name_address_records",
    "load_legal_dong_records",
    "load_navigation_building_records",
    "load_related_jibun_records",
    "load_road_name_address_records",
    "make_postgis_metadata",
    "make_address_point_metadata",
    "records_from_openapi_rows",
]
