"""Importing this package registers all event handlers."""

from app.events.handlers import auth, clubs, partners, system

__all__ = ["auth", "clubs", "partners", "system"]
