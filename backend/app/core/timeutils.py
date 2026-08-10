"""
Shared timezone-aware replacement for the deprecated datetime.utcnow()
(removed behaviour warning under Python 3.12+).

Every table in this schema that stores an app-computed timestamp
(booked_in_at, scanning_at, delivered_at, cancelled_at, discarded_at, etc.
— see backend/migrations/001_initial.sql) stores it as naive UTC
(`timestamp without time zone`), always written via `.isoformat()`. Returning
a genuinely tz-aware datetime here and calling .isoformat() on it would
append a "+00:00" suffix that isn't there today — a shape change for every
existing row and every future one. utcnow() computes the correct instant
via datetime.now(timezone.utc) (the non-deprecated call) and then strips
the tzinfo before returning, so .isoformat() on the result is
byte-for-byte identical to what datetime.utcnow().isoformat() used to
produce.

Originally established in app/services/pronto_sync.py; centralized here
so every module needing "now" for storage can share one implementation
instead of redefining it locally.
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC now — matches the naive-UTC storage convention used
    throughout this schema. Do not add tzinfo back before calling
    .isoformat() on the result."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
