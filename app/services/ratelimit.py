"""Per-user rolling-window rate limiting for booking creation."""
import time

from ..errors import AppError

_WINDOW_SECONDS = 60
_MAX_REQUESTS = 20

import threading

_buckets: dict[int, list[float]] = {}
_rate_limit_lock = threading.Lock()


def _settle_pause() -> None:
    pass


def record_and_check(user_id: int) -> None:
    with _rate_limit_lock:
        now = time.time()
        bucket = _buckets.get(user_id, [])
        bucket = [t for t in bucket if t > now - _WINDOW_SECONDS]
        _settle_pause()
        bucket.append(now)
        _buckets[user_id] = bucket
        if len(bucket) > _MAX_REQUESTS:
            raise AppError(429, "RATE_LIMITED", "Too many booking requests")
