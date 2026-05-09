"""Juso API 호출에 쓰는 HTTP 보조 함수."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, cast

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .exceptions import (
    KrAddrAuthError,
    KrAddrParseError,
    KrAddrRateLimitError,
    KrAddrRequestError,
    KrAddrServerError,
)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; pykraddr/0.1; +https://business.juso.go.kr)"
)
TRANSIENT_STATUSES = {429, 500, 502, 503, 504}


class ResponseLike(Protocol):
    status_code: int
    text: str
    content: bytes
    headers: Mapping[str, str]
    encoding: str | None

    def json(self) -> Any: ...


class SessionLike(Protocol):
    headers: Any

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        stream: bool = False,
    ) -> ResponseLike: ...

    def post(
        self,
        url: str,
        *,
        json: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ResponseLike: ...


def build_session(retries: int = 3) -> SessionLike:
    """멱등 호출에 보수적인 재시도를 적용한 requests 세션을 만든다."""

    session = requests.Session()
    session.headers.update({"User-Agent": DEFAULT_USER_AGENT})
    if retries <= 0:
        return cast(SessionLike, session)

    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        backoff_factor=0.3,
        status_forcelist=tuple(sorted(TRANSIENT_STATUSES)),
        allowed_methods=frozenset({"GET", "POST"}),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return cast(SessionLike, session)


def raise_for_http_error(response: ResponseLike, context: str) -> None:
    """HTTP 상태 코드를 pykraddr 예외로 변환한다."""

    status = int(response.status_code)
    text = response.text[:300]
    if status in {401, 403}:
        raise KrAddrAuthError(f"{context}: HTTP {status}: {text}")
    if status == 429:
        raise KrAddrRateLimitError(f"{context}: HTTP {status}: {text}")
    if 400 <= status < 500:
        raise KrAddrRequestError(f"{context}: HTTP {status}: {text}")
    if 500 <= status < 600:
        raise KrAddrServerError(f"{context}: HTTP {status}: {text}")


def response_json(response: ResponseLike, context: str) -> Mapping[str, Any]:
    """현재 Juso SPA 엔드포인트에 맞춰 UTF-8을 보정한 JSON 객체를 반환한다."""

    if response.encoding is None or response.encoding.lower() in {"iso-8859-1", "latin-1"}:
        response.encoding = "utf-8"
    try:
        payload = response.json()
    except ValueError as exc:
        raise KrAddrParseError(f"{context}: 응답이 올바른 JSON이 아닙니다") from exc
    if not isinstance(payload, Mapping):
        raise KrAddrParseError(f"{context}: JSON 최상위 값이 객체가 아닙니다")
    return payload


def without_none(params: Mapping[str, Any]) -> dict[str, Any]:
    """값이 None인 항목을 제거한 요청 파라미터를 반환한다."""

    return {key: value for key, value in params.items() if value is not None}
