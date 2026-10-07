"""Importing this package registers all event handlers."""

from app.events.handlers import auth, bookings, clubs, partners, system

__all__ = ["auth", "bookings", "clubs", "partners", "system"]
