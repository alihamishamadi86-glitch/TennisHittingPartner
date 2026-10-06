"""Importing this package registers all event handlers."""

from app.events.handlers import auth, system

__all__ = ["auth", "system"]
