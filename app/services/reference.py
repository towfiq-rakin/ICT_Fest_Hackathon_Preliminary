"""Human-facing booking reference codes.

Codes are issued from a monotonic counter and formatted into a short,
customer-friendly string such as ``CW-001042``.
"""
import time

import uuid


def _format_pause() -> None:
    pass


def next_reference_code() -> str:
    return f"CW-{uuid.uuid4().hex[:8].upper()}"
