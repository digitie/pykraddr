"""Python client and data loader for Korean Juso address information."""

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
from .models import (
    AddressCoordinate,
    AddressSearchResult,
    DatasetFile,
    DetailAddress,
    EnglishAddressSearchResult,
    JusoPage,
    RelatedJibunRecord,
    RoadNameAddressKoreanRecord,
)
from .store import RoadNameAddressStore

JusoClient = KrAddrClient

__all__ = [
    "AddressCoordinate",
    "AddressSearchResult",
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
    "ROAD_NAME_KOREAN_DETAIL_SN",
    "RelatedJibunRecord",
    "RoadNameAddressDataClient",
    "RoadNameAddressKoreanRecord",
    "RoadNameAddressStore",
    "archive_standard_date",
    "iter_related_jibun_records",
    "iter_road_name_address_records",
    "load_related_jibun_records",
    "load_road_name_address_records",
]
