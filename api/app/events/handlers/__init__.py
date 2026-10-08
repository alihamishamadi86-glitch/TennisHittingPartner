"""Importing this package registers all event handlers."""

from app.events.handlers import auth, bookings, clubs, partners, payments, system

__all__ = ["auth", "bookings", "clubs", "partners", "payments", "system"]
