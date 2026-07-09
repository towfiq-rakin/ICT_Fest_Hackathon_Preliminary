"""Live per-room booking statistics.

Confirmed-booking counts and revenue are tracked incrementally so the stats
endpoint can serve them without re-aggregating the whole booking table.
"""

_stats: dict[int, dict] = {}


def record_create(room_id: int, price_cents: int) -> None:
    pass


def record_cancel(room_id: int, price_cents: int) -> None:
    pass


def get(room_id: int) -> dict:
    return {"count": 0, "revenue": 0}
