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
    """Raised when the AP returns a non-200 HTTP status."""

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"AP returned HTTP {status}: {body}")
