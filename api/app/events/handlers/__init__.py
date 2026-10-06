"""Importing this package registers all event handlers."""

from app.events.handlers import auth, partners, system

__all__ = ["auth", "partners", "system"]
