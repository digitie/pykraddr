"""Juso 주소 검색 API 클라이언트."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

from ._http import SessionLike, build_session, raise_for_http_error, response_json, without_none
from .exceptions import (
    KrAddrAuthError,
    KrAddrRequestError,
)
from .models import (
    AddressCoordinate,
    AddressSearchResult,
    DetailAddress,
    EnglishAddressSearchResult,
    JusoPage,
)
from .parser import parse_page

if TYPE_CHECKING:
    from .debug import DebugRun

DEFAULT_API_BASE_URL = "https://business.juso.go.kr/addrlink"
DEFAULT_ENV_NAMES = ("JUSO_CONFM_KEY", "JUSO_API_KEY", "KRADDR_CONFM_KEY")
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class _ApiExchange:
    request: dict[str, Any]
    response: dict[str, Any]
    body: Mapping[str, Any]


class KrAddrClient:
    """팝업을 제외한 Juso 주소 API 클라이언트.

    구현된 API:
    - 도로명주소 검색: ``addrLinkApi.do``
    - 영문주소 검색: ``addrEngApi.do``
    - 좌표 검색: ``addrCoordApi.do``
    - 상세주소 검색: ``addrDetailApi.do``

    Juso 지도 검색 상품은 단순 JSON/XML 엔드포인트가 아니라
    가이드/소스 묶음으로 배포되므로, 다운로드 헬퍼만 제공한다.
    """

    def __init__(
        self,
        confm_key: str | None = None,
        *,
        timeout: float = 10.0,
        retries: int = 3,
        base_url: str = DEFAULT_API_BASE_URL,
        session: SessionLike | None = None,
    ) -> None:
        key = confm_key or _first_env(DEFAULT_ENV_NAMES)
        if not key:
            raise KrAddrAuthError(
                "confm_key가 필요합니다. confm_key=...를 넘기거나 JUSO_CONFM_KEY를 설정하세요."
            )
        self.confm_key = key
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self.session = session or build_session(retries)

    @classmethod
    def from_env(cls, name: str = "JUSO_CONFM_KEY", **kwargs: Any) -> KrAddrClient:
        key = os.getenv(name)
        if not key:
            raise KrAddrAuthError(f"{name} 환경 변수가 설정되어 있지 않습니다")
        return cls(confm_key=key, **kwargs)

    def raw_endpoint(
        self,
        endpoint: str,
        params: Mapping[str, Any] | None = None,
    ) -> JusoPage[Mapping[str, Any]]:
        """Juso 검색 엔드포인트를 호출하고 원본 항목 매핑을 반환한다."""

        return self._get_page(endpoint, params or {}, lambda row: row)

    def search(
        self,
        keyword: str,
        *,
        current_page: int = 1,
        count_per_page: int = 10,
        history: bool | str | None = None,
        first_sort: str | None = None,
        add_info: bool | str | None = None,
    ) -> JusoPage[AddressSearchResult]:
        """키워드로 한글 도로명주소를 검색한다."""

        params = self._page_params(current_page, count_per_page) | {
            "keyword": _required_text(keyword, "keyword"),
            "hstryYn": _yn(history),
            "firstSort": first_sort,
            "addInfoYn": _yn(add_info),
        }
        return self._get_page("addrLinkApi.do", params, AddressSearchResult.from_api)

    def debug_search(
        self,
        keyword: str,
        *,
        current_page: int = 1,
        count_per_page: int = 10,
        history: bool | str | None = None,
        first_sort: str | None = None,
        add_info: bool | str | None = None,
    ) -> DebugRun:
        """검색 호출을 실행하고 fixture 저장에 쓸 디버그 실행 결과를 반환한다."""

        from .debug import debug_search

        return debug_search(
            self,
            keyword,
            current_page=current_page,
            count_per_page=count_per_page,
            history=history,
            first_sort=first_sort,
            add_info=add_info,
        )

    def search_english(
        self,
        keyword: str,
        *,
        current_page: int = 1,
        count_per_page: int = 10,
    ) -> JusoPage[EnglishAddressSearchResult]:
        """키워드로 영문 도로명주소를 검색한다."""

        params = self._page_params(current_page, count_per_page) | {
            "keyword": _required_text(keyword, "keyword")
        }
        return self._get_page("addrEngApi.do", params, EnglishAddressSearchResult.from_api)

    def debug_search_english(
        self,
        keyword: str,
        *,
        current_page: int = 1,
        count_per_page: int = 10,
    ) -> DebugRun:
        """영문주소 검색 호출을 디버그 실행 결과로 반환한다."""

        from .debug import debug_search_english

        return debug_search_english(
            self,
            keyword,
            current_page=current_page,
            count_per_page=count_per_page,
        )

    def coordinates(
        self,
        *,
        administrative_code: str,
        road_name_code: str,
        underground_yn: str | int,
        building_main_no: str | int,
        building_sub_no: str | int = 0,
    ) -> JusoPage[AddressCoordinate]:
        """선택한 도로명주소의 출입구 좌표를 조회한다."""

        params = {
            "admCd": _required_text(administrative_code, "administrative_code"),
            "rnMgtSn": _required_text(road_name_code, "road_name_code"),
            "udrtYn": str(underground_yn),
            "buldMnnm": str(building_main_no),
            "buldSlno": str(building_sub_no),
        }
        return self._get_page("addrCoordApi.do", params, AddressCoordinate.from_api)

    def debug_coordinates(
        self,
        *,
        administrative_code: str,
        road_name_code: str,
        underground_yn: str | int,
        building_main_no: str | int,
        building_sub_no: str | int = 0,
    ) -> DebugRun:
        """좌표 검색 호출을 디버그 실행 결과로 반환한다."""

        from .debug import debug_coordinates

        return debug_coordinates(
            self,
            administrative_code=administrative_code,
            road_name_code=road_name_code,
            underground_yn=underground_yn,
            building_main_no=building_main_no,
            building_sub_no=building_sub_no,
        )

    def detail_addresses(
        self,
        *,
        administrative_code: str,
        road_name_code: str,
        underground_yn: str | int,
        building_main_no: str | int,
        building_sub_no: str | int = 0,
        search_type: str = "dong",
        dong_name: str | None = None,
    ) -> JusoPage[DetailAddress]:
        """주소에 등록된 상세주소 동/층/호 정보를 조회한다."""

        if search_type not in {"dong", "floorho"}:
            raise KrAddrRequestError('search_type은 "dong" 또는 "floorho"이어야 합니다')
        params = {
            "admCd": _required_text(administrative_code, "administrative_code"),
            "rnMgtSn": _required_text(road_name_code, "road_name_code"),
            "udrtYn": str(underground_yn),
            "buldMnnm": str(building_main_no),
            "buldSlno": str(building_sub_no),
            "searchType": search_type,
            "dongNm": dong_name,
        }
        return self._get_page("addrDetailApi.do", params, DetailAddress.from_api)

    def debug_detail_addresses(
        self,
        *,
        administrative_code: str,
        road_name_code: str,
        underground_yn: str | int,
        building_main_no: str | int,
        building_sub_no: str | int = 0,
        search_type: str = "dong",
        dong_name: str | None = None,
    ) -> DebugRun:
        """상세주소 검색 호출을 디버그 실행 결과로 반환한다."""

        from .debug import debug_detail_addresses

        return debug_detail_addresses(
            self,
            administrative_code=administrative_code,
            road_name_code=road_name_code,
            underground_yn=underground_yn,
            building_main_no=building_main_no,
            building_sub_no=building_sub_no,
            search_type=search_type,
            dong_name=dong_name,
        )

    def iter_search(
        self,
        keyword: str,
        *,
        count_per_page: int = 100,
        max_pages: int | None = None,
        **kwargs: Any,
    ) -> Iterator[AddressSearchResult]:
        """``search``의 모든 페이지를 순회한다."""

        page_no = 1
        pages = 0
        while True:
            page = self.search(
                keyword,
                current_page=page_no,
                count_per_page=count_per_page,
                **kwargs,
            )
            yield from page.items
            pages += 1
            if not page.has_next_page:
                return
            if max_pages is not None and pages >= max_pages:
                return
            page_no = page.next_page or page_no + 1

    def download_map_api_guide(self, output_path: str | os.PathLike[str]) -> os.PathLike[str]:
        """공식 지도 API 가이드/소스 ZIP을 내려받는다.

        현재 Juso 지도 API 상세 페이지는 JSON/XML 검색 엔드포인트가 아니라
        ``guideMapApi.zip`` 소스 묶음을 제공한다.
        """

        from pathlib import Path

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        url = "https://business.juso.go.kr/api/jst/download"
        params = {
            "fileName": "guideMapApi.zip",
            "realFileName": "guideMapApi.zip",
            "regYmd": "2021",
        }
        response = self.session.get(url, params=params, timeout=self.timeout)
        raise_for_http_error(response, "지도 API 가이드 다운로드")
        path.write_bytes(bytes(response.content))
        return path

    def _page_params(self, current_page: int, count_per_page: int) -> dict[str, Any]:
        if current_page < 1:
            raise KrAddrRequestError("current_page는 1 이상이어야 합니다")
        if not 1 <= count_per_page <= 100:
            raise KrAddrRequestError("count_per_page는 1 이상 100 이하이어야 합니다")
        return {
            "currentPage": current_page,
            "countPerPage": count_per_page,
        }

    def _get_page(
        self,
        endpoint: str,
        params: Mapping[str, Any],
        parser: Callable[[Mapping[str, Any]], T],
    ) -> JusoPage[T]:
        exchange = self._request_json(endpoint, params)
        return parse_page(exchange.body, parser, endpoint=endpoint)

    def _request_json(self, endpoint: str, params: Mapping[str, Any]) -> _ApiExchange:
        request_params: dict[str, Any] = {
            "confmKey": self.confm_key,
            "resultType": "json",
        }
        request_params.update(params)
        url = f"{self.base_url}/{endpoint.strip('/')}"
        clean_params = without_none(request_params)
        response = self.session.get(
            url,
            params=clean_params,
            timeout=self.timeout,
        )
        raise_for_http_error(response, endpoint)
        payload = response_json(response, endpoint)
        return _ApiExchange(
            request={
                "method": "GET",
                "url": url,
                "query": clean_params,
            },
            response={
                "status_code": int(response.status_code),
                "headers": dict(response.headers or {}),
                "body": payload,
            },
            body=payload,
        )


def _first_env(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _required_text(value: str, field: str) -> str:
    text = str(value).strip()
    if not text:
        raise KrAddrRequestError(f"{field}는 비어 있을 수 없습니다")
    return text


def _yn(value: bool | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "Y" if value else "N"
    text = str(value).strip().upper()
    if text not in {"Y", "N"}:
        raise KrAddrRequestError('Juso 불리언 옵션은 True/False, "Y", "N" 중 하나여야 합니다')
    return text
