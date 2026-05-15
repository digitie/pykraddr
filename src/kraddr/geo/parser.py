"""Juso 원본 응답을 kraddr.geo 모델로 변환하는 파서."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from .exceptions import (
    KrAddrAuthError,
    KrAddrParseError,
    KrAddrRateLimitError,
    KrAddrRequestError,
    KrAddrServerError,
)
from .models import (
    AddressCoordinate,
    AddressSearchResult,
    DetailAddress,
    EnglishAddressSearchResult,
    JusoPage,
)

T = TypeVar("T")


def parse_page(
    payload: Mapping[str, Any],
    parser: Callable[[Mapping[str, Any]], T],
    *,
    endpoint: str,
) -> JusoPage[T]:
    """Juso 공통 페이지 응답을 모델 페이지로 변환한다."""

    results = payload.get("results", payload)
    if not isinstance(results, Mapping):
        raise KrAddrParseError(f"{endpoint}: results가 객체가 아닙니다")
    common = results.get("common", {})
    if not isinstance(common, Mapping):
        raise KrAddrParseError(f"{endpoint}: common이 객체가 아닙니다")

    error_code = str(common.get("errorCode", "0")).strip() or "0"
    error_message = str(common.get("errorMessage", "")).strip()
    _raise_for_juso_error(error_code, error_message, endpoint=endpoint)

    rows = _items(results.get("juso"))
    return JusoPage(
        items=tuple(parser(row) for row in rows),
        total_count=_int_value(common.get("totalCount")),
        current_page=_int_value(common.get("currentPage"), default=1),
        count_per_page=_int_value(common.get("countPerPage"), default=len(rows) or 10),
        error_code=error_code,
        error_message=error_message or "정상",
        raw=payload,
    )


def parse_search_response(payload: Mapping[str, Any]) -> JusoPage[AddressSearchResult]:
    """도로명주소 검색 원본 응답을 파싱한다."""

    return parse_page(payload, AddressSearchResult.from_api, endpoint="addrLinkApi.do")


def parse_english_search_response(
    payload: Mapping[str, Any],
) -> JusoPage[EnglishAddressSearchResult]:
    """영문주소 검색 원본 응답을 파싱한다."""

    return parse_page(payload, EnglishAddressSearchResult.from_api, endpoint="addrEngApi.do")


def parse_coordinates_response(payload: Mapping[str, Any]) -> JusoPage[AddressCoordinate]:
    """좌표 검색 원본 응답을 파싱한다."""

    return parse_page(payload, AddressCoordinate.from_api, endpoint="addrCoordApi.do")


def parse_detail_addresses_response(payload: Mapping[str, Any]) -> JusoPage[DetailAddress]:
    """상세주소 검색 원본 응답을 파싱한다."""

    return parse_page(payload, DetailAddress.from_api, endpoint="addrDetailApi.do")


def _items(value: Any) -> list[Mapping[str, Any]]:
    if value is None or value == "":
        return []
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, list) and all(isinstance(item, Mapping) for item in value):
        return value
    raise KrAddrParseError("results.juso가 객체 또는 목록이 아닙니다")


def _raise_for_juso_error(code: str, message: str, *, endpoint: str) -> None:
    if code in {"0", "00", ""}:
        return
    text = f"{endpoint}: Juso가 오류 코드 {code}를 반환했습니다: {message}".strip()
    if code == "-999":
        raise KrAddrServerError(text)
    if code in {"E0001", "E0005"}:
        raise KrAddrAuthError(text)
    if code in {"E0007", "E0008"}:
        raise KrAddrRateLimitError(text)
    raise KrAddrRequestError(text)


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default
