"""Juso API 응답과 주소 TXT 행을 표현하는 공개 모델."""

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
    """페이지 단위 Juso 검색 API 응답."""

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
class LegalDongRecord:
    """data.go.kr/code.go.kr 형식 CSV의 법정동코드 한 행."""

    legal_dong_code: str
    legal_dong_name: str
    status_name: str = ""
    previous_legal_dong_code: str | None = None
    sido_name: str | None = None
    sigungu_name: str | None = None
    eup_myeon_dong_name: str | None = None
    ri_name: str | None = None
    raw: RawRecord = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "legal_dong_code", str(self.legal_dong_code).strip())
        object.__setattr__(self, "legal_dong_name", str(self.legal_dong_name).strip())
        object.__setattr__(self, "status_name", str(self.status_name).strip())
        object.__setattr__(self, "raw", _freeze(self.raw))

    @property
    def is_active(self) -> bool:
        return self.status_name not in {"폐지", "말소", "삭제", "N", "n"}

    @property
    def sido_code(self) -> str:
        return self.legal_dong_code[:2]

    @property
    def sigungu_code(self) -> str:
        return self.legal_dong_code[:5]

    @property
    def eup_myeon_dong_code(self) -> str:
        return self.legal_dong_code[:8]

    @property
    def ri_code(self) -> str:
        return self.legal_dong_code[8:10]

    @property
    def legal_dong_level(self) -> str:
        code = self.legal_dong_code
        if len(code) != 10:
            return "unknown"
        if code[2:] == "00000000":
            return "sido"
        if code[5:] == "00000":
            return "sigungu"
        if code[8:] == "00":
            return "eup_myeon_dong"
        return "ri"


@dataclass(frozen=True, slots=True)
class AddressSearchResult:
    """도로명주소 검색 API의 한 행."""

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
    """영문주소 검색 API의 한 행."""

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
    """좌표 검색 API의 한 행."""

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
    """상세주소 검색 API의 한 행."""

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
    """business.juso.go.kr에 공지된 다운로드 가능 주소 데이터셋 파일."""

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
    """도로명주소 한글 전체분/변동분 TXT의 한 행."""

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
    """도로명주소 한글 데이터의 관련 지번 TXT 한 행."""

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
