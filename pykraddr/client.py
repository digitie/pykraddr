"""Client for Juso address search APIs."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Mapping
from typing import Any, TypeVar

from ._http import SessionLike, build_session, raise_for_http_error, response_json, without_none
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

DEFAULT_API_BASE_URL = "https://business.juso.go.kr/addrlink"
DEFAULT_ENV_NAMES = ("JUSO_CONFM_KEY", "JUSO_API_KEY", "KRADDR_CONFM_KEY")
T = TypeVar("T")


class KrAddrClient:
    """Client for non-popup Juso address APIs.

    Implemented APIs:
    - road-name address search: ``addrLinkApi.do``
    - English address search: ``addrEngApi.do``
    - coordinate search: ``addrCoordApi.do``
    - detail-address search: ``addrDetailApi.do``

    Juso's map search product is distributed as a guide/source bundle rather than
    a simple JSON/XML endpoint, so the downloadable guide is exposed by
    :meth:`download_map_api_guide`.
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
                "confm_key is required. Pass confm_key=... or set JUSO_CONFM_KEY."
            )
        self.confm_key = key
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self.session = session or build_session(retries)

    @classmethod
    def from_env(cls, name: str = "JUSO_CONFM_KEY", **kwargs: Any) -> KrAddrClient:
        key = os.getenv(name)
        if not key:
            raise KrAddrAuthError(f"{name} is not set")
        return cls(confm_key=key, **kwargs)

    def raw_endpoint(
        self,
        endpoint: str,
        params: Mapping[str, Any] | None = None,
    ) -> JusoPage[Mapping[str, Any]]:
        """Call a Juso search endpoint and return raw item mappings."""

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
        """Search Korean road-name addresses by keyword."""

        params = self._page_params(current_page, count_per_page) | {
            "keyword": _required_text(keyword, "keyword"),
            "hstryYn": _yn(history),
            "firstSort": first_sort,
            "addInfoYn": _yn(add_info),
        }
        return self._get_page("addrLinkApi.do", params, AddressSearchResult.from_api)

    def search_english(
        self,
        keyword: str,
        *,
        current_page: int = 1,
        count_per_page: int = 10,
    ) -> JusoPage[EnglishAddressSearchResult]:
        """Search English road-name addresses by keyword."""

        params = self._page_params(current_page, count_per_page) | {
            "keyword": _required_text(keyword, "keyword")
        }
        return self._get_page("addrEngApi.do", params, EnglishAddressSearchResult.from_api)

    def coordinates(
        self,
        *,
        administrative_code: str,
        road_name_code: str,
        underground_yn: str | int,
        building_main_no: str | int,
        building_sub_no: str | int = 0,
    ) -> JusoPage[AddressCoordinate]:
        """Fetch entrance coordinates for a selected road-name address."""

        params = {
            "admCd": _required_text(administrative_code, "administrative_code"),
            "rnMgtSn": _required_text(road_name_code, "road_name_code"),
            "udrtYn": str(underground_yn),
            "buldMnnm": str(building_main_no),
            "buldSlno": str(building_sub_no),
        }
        return self._get_page("addrCoordApi.do", params, AddressCoordinate.from_api)

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
        """Fetch registered detail-address dong/floor/ho rows for an address."""

        if search_type not in {"dong", "floorho"}:
            raise KrAddrRequestError('search_type must be "dong" or "floorho"')
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

    def iter_search(
        self,
        keyword: str,
        *,
        count_per_page: int = 100,
        max_pages: int | None = None,
        **kwargs: Any,
    ) -> Iterator[AddressSearchResult]:
        """Iterate all pages from :meth:`search`."""

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
        """Download the official map API guide/source ZIP.

        The current Juso map API detail page exposes ``guideMapApi.zip`` as a
        source bundle instead of documenting a JSON/XML search endpoint.
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
        raise_for_http_error(response, "map API guide download")
        path.write_bytes(bytes(response.content))
        return path

    def _page_params(self, current_page: int, count_per_page: int) -> dict[str, Any]:
        if current_page < 1:
            raise KrAddrRequestError("current_page must be >= 1")
        if not 1 <= count_per_page <= 100:
            raise KrAddrRequestError("count_per_page must be between 1 and 100")
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
        request_params: dict[str, Any] = {
            "confmKey": self.confm_key,
            "resultType": "json",
        }
        request_params.update(params)
        url = f"{self.base_url}/{endpoint.strip('/')}"
        response = self.session.get(
            url,
            params=without_none(request_params),
            timeout=self.timeout,
        )
        raise_for_http_error(response, endpoint)
        payload = response_json(response, endpoint)
        return _parse_page(payload, parser, endpoint=endpoint)


def _parse_page(
    payload: Mapping[str, Any],
    parser: Callable[[Mapping[str, Any]], T],
    *,
    endpoint: str,
) -> JusoPage[T]:
    results = payload.get("results", payload)
    if not isinstance(results, Mapping):
        raise KrAddrParseError(f"{endpoint}: results was not an object")
    common = results.get("common", {})
    if not isinstance(common, Mapping):
        raise KrAddrParseError(f"{endpoint}: common was not an object")

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


def _items(value: Any) -> list[Mapping[str, Any]]:
    if value is None or value == "":
        return []
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, list) and all(isinstance(item, Mapping) for item in value):
        return value
    raise KrAddrParseError("results.juso was not an object or list")


def _raise_for_juso_error(code: str, message: str, *, endpoint: str) -> None:
    if code in {"0", "00", ""}:
        return
    text = f"{endpoint}: Juso returned {code}: {message}".strip()
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


def _first_env(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _required_text(value: str, field: str) -> str:
    text = str(value).strip()
    if not text:
        raise KrAddrRequestError(f"{field} must not be empty")
    return text


def _yn(value: bool | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "Y" if value else "N"
    text = str(value).strip().upper()
    if text not in {"Y", "N"}:
        raise KrAddrRequestError('boolean Juso options must be True/False, "Y", or "N"')
    return text
