from __future__ import annotations

# Backwards-compatible import path. The canonical application factory now
# registers chat and Access routes directly, so direct ASGI imports and the CLI
# cannot drift into different route sets.
from .api import create_app

__all__ = ["create_app"]
