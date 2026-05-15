"""파싱된 kraddr.geo 모델을 비교와 표시에 좋은 결과로 가공한다."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any

from .models import (
    AddressCoordinate,
    AddressSearchResult,
    DetailAddress,
    EnglishAddressSearchResult,
    JusoPage,
)


def process_search_response(page: JusoPage[AddressSearchResult]) -> dict[str, Any]:
    """도로명주소 검색 결과를 fixture snapshot에 적합한 dict로 바꾼다."""

    return _page_dict(page, _public_dataclass_dict)


def process_english_search_response(
    page: JusoPage[EnglishAddressSearchResult],
) -> dict[str, Any]:
    """영문주소 검색 결과를 fixture snapshot에 적합한 dict로 바꾼다."""

    return _page_dict(page, _public_dataclass_dict)


def process_coordinates_response(page: JusoPage[AddressCoordinate]) -> dict[str, Any]:
    """좌표 검색 결과를 fixture snapshot에 적합한 dict로 바꾼다."""

    return _page_dict(page, _public_dataclass_dict)


def process_detail_addresses_response(page: JusoPage[DetailAddress]) -> dict[str, Any]:
    """상세주소 검색 결과를 fixture snapshot에 적합한 dict로 바꾼다."""

    return _page_dict(page, _public_dataclass_dict)


def _page_dict(page: JusoPage[Any], item_processor: Any) -> dict[str, Any]:
    return {
        "total_count": page.total_count,
        "current_page": page.current_page,
        "count_per_page": page.count_per_page,
        "error_code": page.error_code,
        "error_message": page.error_message,
        "items": [item_processor(item) for item in page.items],
    }


def _public_dataclass_dict(value: Any) -> dict[str, Any]:
    if not is_dataclass(value) or isinstance(value, type):
        raise TypeError(f"dataclass 인스턴스가 필요합니다: {type(value)!r}")
    return {
        field.name: getattr(value, field.name)
        for field in fields(value)
        if field.name != "raw"
    }
