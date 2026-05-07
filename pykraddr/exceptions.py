"""Exceptions raised by pykraddr."""

from __future__ import annotations


class KrAddrError(Exception):
    """Base error for pykraddr."""


class KrAddrAuthError(KrAddrError):
    """The Juso approval key was missing, invalid, or unauthorized."""


class KrAddrRateLimitError(KrAddrError):
    """The Juso service rejected the request because of traffic limits."""


class KrAddrRequestError(KrAddrError):
    """A request was malformed or failed before a usable response was received."""


class KrAddrServerError(KrAddrError):
    """The Juso service returned a server-side error."""


class KrAddrParseError(KrAddrError):
    """A Juso API response or data file could not be parsed."""


class KrAddrNoDataError(KrAddrError):
    """The requested Juso dataset or API page did not contain data."""
