"""Importing this package registers all event handlers."""

from app.events.handlers import auth, bookings, club_contacts, clubs, partners, payments, system

__all__ = ["auth", "bookings", "club_contacts", "clubs", "partners", "payments", "system"]
