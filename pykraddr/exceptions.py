"""pykraddr에서 사용하는 예외 클래스."""

from __future__ import annotations


class KrAddrError(Exception):
    """pykraddr 예외의 기준 클래스."""


class KrAddrAuthError(KrAddrError):
    """Juso 승인키가 없거나, 올바르지 않거나, 권한이 없을 때 발생한다."""


class KrAddrRateLimitError(KrAddrError):
    """Juso 서비스가 호출량 제한 때문에 요청을 거부했을 때 발생한다."""


class KrAddrRequestError(KrAddrError):
    """요청 형식이 잘못되었거나 사용 가능한 응답을 받기 전에 실패했을 때 발생한다."""


class KrAddrServerError(KrAddrError):
    """Juso 서비스가 서버 측 오류를 반환했을 때 발생한다."""


class KrAddrParseError(KrAddrError):
    """Juso API 응답이나 데이터 파일을 해석할 수 없을 때 발생한다."""


class KrAddrNoDataError(KrAddrError):
    """요청한 Juso 데이터셋이나 API 페이지에 데이터가 없을 때 발생한다."""
