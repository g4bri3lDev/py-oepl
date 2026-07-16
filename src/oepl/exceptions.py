"""Exceptions for the oepl library."""

from __future__ import annotations


class OEPLError(Exception):
    """Base exception for all oepl errors."""


class OEPLConnectionError(OEPLError):
    """Raised when a connection to the AP cannot be established."""


class OEPLTimeoutError(OEPLError):
    """Raised when a request to the AP times out."""


class OEPLNotFoundError(OEPLError):
    """Raised when the AP returns HTTP 404."""


class OEPLResponseError(OEPLError):
    """Raised when the AP reports a request failure.

    Covers both a non-200 HTTP status, and the AP's alternate failure mode
    of HTTP 200 with a body that (once stripped) starts with "Error"/"error"
    — some firmware handlers (e.g. ``/save_cfg`` with an unknown MAC) report
    failures this way instead of via the HTTP status code.
    """

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"AP returned HTTP {status}: {body}")
