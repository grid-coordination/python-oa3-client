"""BlClient — Business Logic client for program/event management."""

from __future__ import annotations

from openadr3_client.base import BaseClient


class BlClient(BaseClient):
    """OpenADR 3 Business Logic client.

    Thin wrapper over BaseClient that sets client_type to "bl".
    BL clients create and manage programs and events — no VEN
    registration or notification concepts.

    All OpenADRClient methods are available via __getattr__ delegation.
    """

    _client_type = "bl"
