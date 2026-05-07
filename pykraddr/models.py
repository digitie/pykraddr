"""Public models for Juso API responses and address TXT rows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType
from typing import Any, Generic, TypeVar

T = TypeVar("T")
RawRecord = Mapping[str, Any]


def _freeze(raw: Mapping[str, Any] | None) -> RawRecord:
    if raw is None:
        return MappingProxyType({})
    return MappingProxyType(dict(raw))


def _text(raw: Mapping[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int(raw: Mapping[str, Any], key: str) -> int | None:
    text = _text(raw, key)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _float(raw: Mapping[str, Any], key: str) -> float | None:
    text = _text(raw, key)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class JusoPage(Generic[T]):
    """A paginated Juso search API response."""

    items: tuple[T, ...]
    total_count: int
    current_page: int
    count_per_page: int
    error_code: str = "0"
    error_message: str = "정상"
    raw: RawRecord = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw", _freeze(self.raw))

    @property
    def is_empty(self) -> bool:
        return not self.items

    @property
    def has_next_page(self) -> bool:
        if self.count_per_page <= 0:
            return False
        return self.current_page * self.count_per_page < self.total_count

    @property
    def next_page(self) -> int | None:
        return self.current_page + 1 if self.has_next_page else None


@dataclass(frozen=True, slots=True)
class AddressSearchResult:
    """One row from the road-name address search API."""

    road_address: str | None
    road_address_part1: str | None
    road_address_part2: str | None
    jibun_address: str | None
    english_address: str | None
    zip_code: str | None
    administrative_code: str | None
    road_name_code: str | None
    building_management_number: str | None
    road_name: str | None
    building_name: str | None
    sido_name: str | None
    sigungu_name: str | None
    eup_myeon_dong_name: str | None
    legal_ri_name: str | None
    underground_yn: str | None
    building_main_no: int | None
    building_sub_no: int | None
    mountain_yn: str | None
    lot_main_no: int | None
    lot_sub_no: int | None
    eup_myeon_dong_serial_no: str | None
    history_yn: str | None = None
    related_jibun: str | None = None
    administrative_dong_name: str | None = None
    raw: RawRecord = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw", _freeze(self.raw))

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> AddressSearchResult:
        return cls(
            road_address=_text(raw, "roadAddr"),
            road_address_part1=_text(raw, "roadAddrPart1"),
            road_address_part2=_text(raw, "roadAddrPart2"),
            jibun_address=_text(raw, "jibunAddr"),
            english_address=_text(raw, "engAddr"),
            zip_code=_text(raw, "zipNo"),
            administrative_code=_text(raw, "admCd"),
            road_name_code=_text(raw, "rnMgtSn"),
            building_management_number=_text(raw, "bdMgtSn"),
            road_name=_text(raw, "rn"),
            building_name=_text(raw, "bdNm"),
            sido_name=_text(raw, "siNm"),
            sigungu_name=_text(raw, "sggNm"),
            eup_myeon_dong_name=_text(raw, "emdNm"),
            legal_ri_name=_text(raw, "liNm"),
            underground_yn=_text(raw, "udrtYn"),
            building_main_no=_int(raw, "buldMnnm"),
            building_sub_no=_int(raw, "buldSlno"),
            mountain_yn=_text(raw, "mtYn"),
            lot_main_no=_int(raw, "lnbrMnnm"),
            lot_sub_no=_int(raw, "lnbrSlno"),
            eup_myeon_dong_serial_no=_text(raw, "emdNo"),
            history_yn=_text(raw, "hstryYn") or _text(raw, "hstryYN"),
            related_jibun=_text(raw, "relJibun"),
            administrative_dong_name=_text(raw, "hemdNm"),
            raw=raw,
        )


@dataclass(frozen=True, slots=True)
class EnglishAddressSearchResult:
    """One row from the English address search API."""

    road_address: str | None
    jibun_address: str | None
    zip_code: str | None
    administrative_code: str | None
    road_name_code: str | None
    road_name: str | None
    sido_name: str | None
    sigungu_name: str | None
    eup_myeon_dong_name: str | None
    legal_ri_name: str | None
    underground_yn: str | None
    building_main_no: int | None
    building_sub_no: int | None
    building_kind_code: str | None
    raw: RawRecord = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw", _freeze(self.raw))

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> EnglishAddressSearchResult:
        return cls(
            road_address=_text(raw, "roadAddr"),
            jibun_address=_text(raw, "jibunAddr"),
            zip_code=_text(raw, "zipNo"),
            administrative_code=_text(raw, "admCd"),
            road_name_code=_text(raw, "rnMgtSn"),
            road_name=_text(raw, "rn"),
            sido_name=_text(raw, "siNm"),
            sigungu_name=_text(raw, "sggNm"),
            eup_myeon_dong_name=_text(raw, "emdNm"),
            legal_ri_name=_text(raw, "liNm"),
            underground_yn=_text(raw, "udrtYn"),
            building_main_no=_int(raw, "buldMnnm"),
            building_sub_no=_int(raw, "buldSlno"),
            building_kind_code=_text(raw, "bdKdcd"),
            raw=raw,
        )


@dataclass(frozen=True, slots=True)
class AddressCoordinate:
    """One row from the coordinate search API."""

    administrative_code: str | None
    road_name_code: str | None
    building_management_number: str | None
    underground_yn: str | None
    building_main_no: int | None
    building_sub_no: int | None
    x: float | None
    y: float | None
    building_name: str | None
    raw: RawRecord = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw", _freeze(self.raw))

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> AddressCoordinate:
        return cls(
            administrative_code=_text(raw, "admCd"),
            road_name_code=_text(raw, "rnMgtSn"),
            building_management_number=_text(raw, "bdMgtSn"),
            underground_yn=_text(raw, "udrtYn"),
            building_main_no=_int(raw, "buldMnnm"),
            building_sub_no=_int(raw, "buldSlno"),
            x=_float(raw, "entX"),
            y=_float(raw, "entY"),
            building_name=_text(raw, "bdNm"),
            raw=raw,
        )


@dataclass(frozen=True, slots=True)
class DetailAddress:
    """One row from the detail-address search API."""

    administrative_code: str | None
    road_name_code: str | None
    underground_yn: str | None
    building_main_no: int | None
    building_sub_no: int | None
    dong_name: str | None
    floor_name: str | None
    ho_name: str | None
    raw: RawRecord = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw", _freeze(self.raw))

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> DetailAddress:
        return cls(
            administrative_code=_text(raw, "admCd"),
            road_name_code=_text(raw, "rnMgtSn"),
            underground_yn=_text(raw, "udrtYn"),
            building_main_no=_int(raw, "buldMnnm"),
            building_sub_no=_int(raw, "buldSlno"),
            dong_name=_text(raw, "dongNm"),
            floor_name=_text(raw, "floorNm"),
            ho_name=_text(raw, "hoNm"),
            raw=raw,
        )


@dataclass(frozen=True, slots=True)
class DatasetFile:
    """One downloadable address dataset file advertised by business.juso.go.kr."""

    data_detail_sn: str
    data_kind_code: str
    data_kind_name: str
    period: str
    standard_date: str
    request_type: str
    file_name: str
    real_file_name: str
    registry_year: str
    city_province_code: str | None = None
    file_sn: str = "0"
    attachment_no: str = "0"
    raw: RawRecord = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw", _freeze(self.raw))

    @property
    def is_daily(self) -> bool:
        return self.period == "daily"

    @property
    def is_monthly(self) -> bool:
        return self.period in {"monthly_full", "monthly_change"}


@dataclass(frozen=True, slots=True)
class RoadNameAddressKoreanRecord:
    """A row from road-name address Korean master/change TXT files."""

    road_address_management_number: str
    legal_dong_code: str
    sido_name: str
    sigungu_name: str
    legal_eup_myeon_dong_name: str
    legal_ri_name: str
    mountain_yn: str
    lot_main_no: str
    lot_sub_no: str
    road_name_code: str
    road_name: str
    underground_yn: str
    building_main_no: str
    building_sub_no: str
    administrative_dong_code: str
    administrative_dong_name: str
    postal_code: str
    previous_road_name_address: str
    effective_date: str
    apartment_yn: str
    change_reason_code: str
    building_register_name: str
    sigungu_building_name: str
    remark: str

    @property
    def primary_key(self) -> tuple[str, str, str, str, str]:
        return (
            self.road_address_management_number,
            self.road_name_code,
            self.underground_yn,
            self.building_main_no,
            self.building_sub_no,
        )

    @property
    def effective_date_value(self) -> date | None:
        if len(self.effective_date) != 8 or not self.effective_date.isdigit():
            return None
        return date(
            int(self.effective_date[:4]),
            int(self.effective_date[4:6]),
            int(self.effective_date[6:8]),
        )


@dataclass(frozen=True, slots=True)
class RelatedJibunRecord:
    """A row from related-jibun TXT files for road-name address Korean data."""

    road_address_management_number: str
    legal_dong_code: str
    sido_name: str
    sigungu_name: str
    legal_eup_myeon_dong_name: str
    legal_ri_name: str
    mountain_yn: str
    lot_main_no: str
    lot_sub_no: str
    road_name_code: str
    underground_yn: str
    building_main_no: str
    building_sub_no: str
    change_reason_code: str

    @property
    def primary_key(self) -> tuple[str, str, str, str, str]:
        return (
            self.road_address_management_number,
            self.legal_dong_code,
            self.mountain_yn,
            self.lot_main_no,
            self.lot_sub_no,
        )
