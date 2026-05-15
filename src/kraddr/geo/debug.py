"""fixture 생성 UI와 외부 도구가 쓰는 디버그 실행 헬퍼."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from typing import Any

from .client import KrAddrClient, _required_text, _yn
from .parser import (
    parse_coordinates_response,
    parse_detail_addresses_response,
    parse_english_search_response,
    parse_search_response,
)
from .processor import (
    process_coordinates_response,
    process_detail_addresses_response,
    process_english_search_response,
    process_search_response,
)

SENSITIVE_KEYS = {
    "authorization",
    "x-api-key",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "confmkey",
    "confm_key",
    "servicekey",
    "service_key",
}


@dataclass(slots=True)
class DebugRun:
    """한 번의 라이브러리 함수 실행과 그 중간 산출물을 담는다."""

    function: str
    input: dict[str, Any]
    request: dict[str, Any]
    response: dict[str, Any]
    parsed: Any
    processed: Any
    trace: list[str]
    error: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def debug_search(
    client: KrAddrClient,
    keyword: str,
    *,
    current_page: int = 1,
    count_per_page: int = 10,
    history: bool | str | None = None,
    first_sort: str | None = None,
    add_info: bool | str | None = None,
) -> DebugRun:
    """도로명주소 검색을 실행하고 원본/파싱/가공 결과를 함께 반환한다."""

    input_data = {
        "keyword": keyword,
        "current_page": current_page,
        "count_per_page": count_per_page,
        "history": history,
        "first_sort": first_sort,
        "add_info": add_info,
    }
    try:
        params = client._page_params(current_page, count_per_page) | {
            "keyword": _required_text(keyword, "keyword"),
            "hstryYn": _yn(history),
            "firstSort": first_sort,
            "addInfoYn": _yn(add_info),
        }
    except Exception as exc:
        return _error_run(
            function="search",
            input_data=input_data,
            trace=["input validation failed"],
            error=exc,
        )
    return _debug_page(
        client,
        function="search",
        endpoint="addrLinkApi.do",
        input_data=input_data,
        params=params,
        parser=parse_search_response,
        processor=process_search_response,
    )


def debug_search_english(
    client: KrAddrClient,
    keyword: str,
    *,
    current_page: int = 1,
    count_per_page: int = 10,
) -> DebugRun:
    """영문주소 검색을 실행하고 원본/파싱/가공 결과를 함께 반환한다."""

    input_data = {
        "keyword": keyword,
        "current_page": current_page,
        "count_per_page": count_per_page,
    }
    try:
        params = client._page_params(current_page, count_per_page) | {
            "keyword": _required_text(keyword, "keyword")
        }
    except Exception as exc:
        return _error_run(
            function="search_english",
            input_data=input_data,
            trace=["input validation failed"],
            error=exc,
        )
    return _debug_page(
        client,
        function="search_english",
        endpoint="addrEngApi.do",
        input_data=input_data,
        params=params,
        parser=parse_english_search_response,
        processor=process_english_search_response,
    )


def debug_coordinates(
    client: KrAddrClient,
    *,
    administrative_code: str,
    road_name_code: str,
    underground_yn: str | int,
    building_main_no: str | int,
    building_sub_no: str | int = 0,
) -> DebugRun:
    """좌표 검색을 실행하고 원본/파싱/가공 결과를 함께 반환한다."""

    input_data = {
        "administrative_code": administrative_code,
        "road_name_code": road_name_code,
        "underground_yn": underground_yn,
        "building_main_no": building_main_no,
        "building_sub_no": building_sub_no,
    }
    try:
        params = {
            "admCd": _required_text(administrative_code, "administrative_code"),
            "rnMgtSn": _required_text(road_name_code, "road_name_code"),
            "udrtYn": str(underground_yn),
            "buldMnnm": str(building_main_no),
            "buldSlno": str(building_sub_no),
        }
    except Exception as exc:
        return _error_run(
            function="coordinates",
            input_data=input_data,
            trace=["input validation failed"],
            error=exc,
        )
    return _debug_page(
        client,
        function="coordinates",
        endpoint="addrCoordApi.do",
        input_data=input_data,
        params=params,
        parser=parse_coordinates_response,
        processor=process_coordinates_response,
    )


def debug_detail_addresses(
    client: KrAddrClient,
    *,
    administrative_code: str,
    road_name_code: str,
    underground_yn: str | int,
    building_main_no: str | int,
    building_sub_no: str | int = 0,
    search_type: str = "dong",
    dong_name: str | None = None,
) -> DebugRun:
    """상세주소 검색을 실행하고 원본/파싱/가공 결과를 함께 반환한다."""

    input_data = {
        "administrative_code": administrative_code,
        "road_name_code": road_name_code,
        "underground_yn": underground_yn,
        "building_main_no": building_main_no,
        "building_sub_no": building_sub_no,
        "search_type": search_type,
        "dong_name": dong_name,
    }
    if search_type not in {"dong", "floorho"}:
        return _error_run(
            function="detail_addresses",
            input_data=input_data,
            trace=["input validation failed"],
            error=ValueError('search_type은 "dong" 또는 "floorho"이어야 합니다'),
        )
    try:
        params = {
            "admCd": _required_text(administrative_code, "administrative_code"),
            "rnMgtSn": _required_text(road_name_code, "road_name_code"),
            "udrtYn": str(underground_yn),
            "buldMnnm": str(building_main_no),
            "buldSlno": str(building_sub_no),
            "searchType": search_type,
            "dongNm": dong_name,
        }
    except Exception as exc:
        return _error_run(
            function="detail_addresses",
            input_data=input_data,
            trace=["input validation failed"],
            error=exc,
        )
    return _debug_page(
        client,
        function="detail_addresses",
        endpoint="addrDetailApi.do",
        input_data=input_data,
        params=params,
        parser=parse_detail_addresses_response,
        processor=process_detail_addresses_response,
    )


def jsonable(value: Any) -> Any:
    """dataclass, Pydantic v2 모델, tuple 등을 JSON 저장 가능한 값으로 바꾼다."""

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    return value


def redact_sensitive(value: Any) -> Any:
    """API 키와 토큰 계열 값을 재귀적으로 마스킹한다."""

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            if text_key.lower() in SENSITIVE_KEYS:
                result[text_key] = "<REDACTED>"
            else:
                result[text_key] = redact_sensitive(item)
        return result
    if isinstance(value, (list, tuple, set)):
        return [redact_sensitive(item) for item in value]
    return value


def _debug_page(
    client: KrAddrClient,
    *,
    function: str,
    endpoint: str,
    input_data: dict[str, Any],
    params: Mapping[str, Any],
    parser: Any,
    processor: Any,
) -> DebugRun:
    exchange = None
    trace = [
        f"{function}: build request params",
        f"{function}: GET {endpoint}",
    ]
    try:
        exchange = client._request_json(endpoint, params)
        trace.append(f"{function}: parse raw response")
        parsed = parser(exchange.body)
        trace.append(f"{function}: process parsed result")
        processed = processor(parsed)
        return DebugRun(
            function=function,
            input=redact_sensitive(jsonable(input_data)),
            request=redact_sensitive(jsonable(exchange.request)),
            response=redact_sensitive(jsonable(exchange.response)),
            parsed=parsed,
            processed=processed,
            trace=trace,
        )
    except Exception as exc:
        trace.append(f"{function}: error")
        return DebugRun(
            function=function,
            input=redact_sensitive(jsonable(input_data)),
            request=redact_sensitive(jsonable(exchange.request)) if exchange else {},
            response=redact_sensitive(jsonable(exchange.response)) if exchange else {},
            parsed=None,
            processed=None,
            trace=trace,
            error=_error_dict(exc),
        )


def _error_run(
    *,
    function: str,
    input_data: dict[str, Any],
    trace: list[str],
    error: Exception,
) -> DebugRun:
    return DebugRun(
        function=function,
        input=redact_sensitive(jsonable(input_data)),
        request={},
        response={},
        parsed=None,
        processed=None,
        trace=trace,
        error=_error_dict(error),
    )


def _error_dict(error: Exception) -> dict[str, Any]:
    return {
        "type": type(error).__name__,
        "module": type(error).__module__,
        "message": str(error),
    }
