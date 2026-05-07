"""HTTP helpers for Juso APIs."""

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
    """Build a requests session with conservative retries for idempotent calls."""

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
    """Map HTTP status codes to pykraddr exceptions."""

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
    """Return a JSON object, forcing UTF-8 for current Juso SPA endpoints."""

    if response.encoding is None or response.encoding.lower() in {"iso-8859-1", "latin-1"}:
        response.encoding = "utf-8"
    try:
        payload = response.json()
    except ValueError as exc:
        raise KrAddrParseError(f"{context}: response was not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise KrAddrParseError(f"{context}: JSON root was not an object")
    return payload


def without_none(params: Mapping[str, Any]) -> dict[str, Any]:
    """Return params with None values removed."""

    return {key: value for key, value in params.items() if value is not None}
