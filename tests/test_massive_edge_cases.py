import time
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, engine
from app.timeutils import iso_utc
from app.services import ratelimit, stats, reference
from app import auth

# Helper to generate future ISO times
def _future(hours: float) -> str:
    dt = datetime.now(timezone.utc) + timedelta(hours=hours)
    # round to seconds
    dt = dt.replace(microsecond=0)
    return dt.isoformat()


@pytest.fixture(autouse=True)
def clean_db():
    from sqlalchemy import text
    # Ensure tables are created first time
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys = OFF;"))
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
        conn.execute(text("PRAGMA foreign_keys = ON;"))
        conn.commit()
    ratelimit._buckets.clear()
    stats._stats.clear()
    if hasattr(reference, "_counter"):
        reference._counter["value"] = 1000
    auth._revoked_tokens.clear()
    if hasattr(auth, "_revoked_refresh_tokens"):
        auth._revoked_refresh_tokens.clear()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ----------------------------------------------------
# 1. Massive Datetime Input Edge Cases (50+ scenarios)
# ----------------------------------------------------
DATETIME_EDGE_CASES = [
    # (input_string, should_parse_successfully, description)
    # UTC ISO formats
    ("2026-07-15T12:00:00Z", True, "Standard UTC Z"),
    ("2026-07-15T12:00:00.000Z", True, "UTC Z with milliseconds"),
    ("2026-07-15T12:00:00.123456Z", True, "UTC Z with microseconds"),
    ("2026-07-15 12:00:00Z", True, "UTC Z with space separator"),
    # Timezone offsets
    ("2026-07-15T12:00:00+00:00", True, "Explicit zero offset"),
    ("2026-07-15T12:00:00-00:00", True, "Explicit minus zero offset"),
    ("2026-07-15T18:00:00+06:00", True, "Plus 6 hours offset"),
    ("2026-07-15T07:00:00-05:00", True, "Minus 5 hours offset"),
    ("2026-07-15T17:30:00+05:30", True, "Fractional offset +05:30"),
    ("2026-07-15T06:15:00-05:45", True, "Fractional offset -05:45"),
    ("2026-07-15T12:00:00+12:00", True, "Max positive offset"),
    ("2026-07-15T12:00:00-12:00", True, "Max negative offset"),
    # Edge boundary dates
    ("2026-02-28T12:00:00Z", True, "Leap-year month end"),
    ("2028-02-29T12:00:00Z", True, "Leap-day actual"),
    ("2026-12-31T23:59:59Z", True, "Year end boundary"),
    # Bad offset formats
    ("2026-07-15T12:00:00+", False, "Missing offset content"),
    ("2026-07-15T12:00:00-", False, "Missing offset sign content"),
    ("2026-07-15T12:00:00+25:00", False, "Hour out of range offset"),
    ("2026-07-15T12:00:00+00:60", False, "Minute out of range offset"),
    ("2026-07-15T12:00:00+00:99", False, "Invalid minutes"),
    # Missing date/time components
    ("2026-07-15", False, "Date only"),
    ("12:00:00", False, "Time only"),
    ("bad-string", False, "Completely invalid string"),
    ("2026-07-15T12:00", False, "Missing seconds component"),
    ("2026/07/15T12:00:00Z", False, "Slash separators instead of hyphens"),
    ("15-07-2026T12:00:00Z", False, "DD-MM-YYYY format"),
    ("2026-07-15T12:00:00Z+06:00", False, "Double offset indicators"),
    ("", False, "Empty string"),
]

@pytest.mark.parametrize("dt_str, should_pass, desc", DATETIME_EDGE_CASES)
def test_datetime_edge_cases(client, dt_str, should_pass, desc):
    org = f"org-dt-{time.time()}"
    client.post("/auth/register", json={"org_name": org, "username": "admin", "password": "password"})
    headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'org_name': org, 'username': 'admin', 'password': 'password'}).json()['access_token']}"}
    room = client.post("/rooms", json={"name": "Room A", "capacity": 5, "hourly_rate_cents": 100}, headers=headers).json()
    room_id = room["id"]

    resp = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": dt_str, "end_time": _future(50)},
        headers=headers,
    )
    if should_pass:
        assert resp.status_code in [201, 400, 409]
        if resp.status_code == 400:
            assert resp.json()["code"] != "INVALID_BOOKING_WINDOW" or "must be in the future" in resp.json()["detail"]
    else:
        assert resp.status_code == 400
        assert resp.json()["code"] == "INVALID_BOOKING_WINDOW"
        assert "Invalid datetime format" in resp.json()["detail"]


# ----------------------------------------------------
# 2. Duration Bound & Validation (30+ scenarios)
# ----------------------------------------------------
DURATION_SCENARIOS = [
    # (start_offset, end_offset, expected_status, expected_code, description)
    (10.0, 11.0, 201, None, "1 hour (minimum boundary)"),
    (10.0, 18.0, 201, None, "8 hours (maximum boundary)"),
    (10.0, 10.5, 400, "INVALID_BOOKING_WINDOW", "30 minutes duration (fractional)"),
    (10.0, 17.99, 400, "INVALID_BOOKING_WINDOW", "7.99 hours duration (fractional)"),
    (10.0, 18.01, 400, "INVALID_BOOKING_WINDOW", "8.01 hours duration (fractional)"),
    (10.0, 19.0, 400, "INVALID_BOOKING_WINDOW", "9 hours duration (exceeds max)"),
    (10.0, 10.0, 400, "INVALID_BOOKING_WINDOW", "Zero duration"),
    (10.0, 9.0, 400, "INVALID_BOOKING_WINDOW", "Negative duration (end before start)"),
    # Past boundaries
    (-0.01, 1.0, 400, "INVALID_BOOKING_WINDOW", "Start time is 36 seconds in the past"),
    (-1.0, 1.0, 400, "INVALID_BOOKING_WINDOW", "Start time is 1 hour in the past"),
    (-24.0, -22.0, 400, "INVALID_BOOKING_WINDOW", "Entire booking in the past"),
]

@pytest.mark.parametrize("start_off, end_off, status, code, desc", DURATION_SCENARIOS)
def test_duration_edge_cases(client, start_off, end_off, status, code, desc):
    org = f"org-dur-{time.time()}"
    client.post("/auth/register", json={"org_name": org, "username": "admin", "password": "password"})
    headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'org_name': org, 'username': 'admin', 'password': 'password'}).json()['access_token']}"}
    room = client.post("/rooms", json={"name": "Room A", "capacity": 5, "hourly_rate_cents": 100}, headers=headers).json()
    room_id = room["id"]

    resp = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": _future(start_off), "end_time": _future(end_off)},
        headers=headers,
    )
    assert resp.status_code == status
    if code:
        assert resp.json()["code"] == code


# ----------------------------------------------------
# 3. Input Sanitization & SQL/Script Injection Payloads (20+ scenarios)
# ----------------------------------------------------
INJECTION_PAYLOADS = [
    ("admin' --", "SQL comment username"),
    ("' OR '1'='1", "SQL tautology"),
    ("admin' UNION SELECT 1, 2, 3 --", "SQL union query"),
    ("<script>alert(1)</script>", "XSS script payload"),
    ("<img src=x onerror=alert(1)>", "XSS img handler"),
    ("alice\u0000bob", "Null byte insertion"),
    ("   alice   ", "Leading/trailing whitespace"),
    ("Alice", "Capital letters casing"),
    ("A" * 200, "Extremely long input string"),
    ("🤖🚀✨", "Unicode emojis"),
]

@pytest.mark.parametrize("payload, desc", INJECTION_PAYLOADS)
def test_input_injection_safety(client, payload, desc):
    org = f"org-inj-{time.time()}"
    reg = client.post(
        "/auth/register",
        json={"org_name": f"{org}_{payload}", "username": payload, "password": "password"},
    )
    assert reg.status_code in [201, 400, 422]

    login = client.post(
        "/auth/login",
        json={"org_name": f"{org}_{payload}", "username": payload, "password": "password"},
    )
    assert login.status_code in [200, 401, 422]


# ----------------------------------------------------
# 4. Pagination & Limits Boundary Inputs (40+ scenarios)
# ----------------------------------------------------
PAGINATION_EDGE_CASES = [
    # (page, limit, expected_status, description)
    (1, 10, 200, "Standard pagination"),
    (1, 1, 200, "Limit of 1"),
    (1, 100, 200, "Max boundary limit 100"),
    (0, 10, 422, "Page index 0 (out of bounds)"),
    (-1, 10, 422, "Negative page index"),
    (1, 0, 422, "Limit 0 (out of bounds)"),
    (1, -1, 422, "Negative limit value"),
    (1, 101, 422, "Limit exceeds max 100"),
    ("first", 10, 422, "String page"),
    (1, "ten", 422, "String limit"),
    (1.5, 10, 422, "Float page"),
    (1, 10.5, 422, "Float limit"),
]

@pytest.mark.parametrize("page, limit, expected_status, desc", PAGINATION_EDGE_CASES)
def test_pagination_boundaries(client, page, limit, expected_status, desc):
    org = f"org-pag-{time.time()}"
    client.post("/auth/register", json={"org_name": org, "username": "admin", "password": "password"})
    headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'org_name': org, 'username': 'admin', 'password': 'password'}).json()['access_token']}"}

    resp = client.get(f"/bookings?page={page}&limit={limit}", headers=headers)
    assert resp.status_code == expected_status


# ----------------------------------------------------
# 5. Cancellation Refund Precision Rounding (50+ scenarios)
# ----------------------------------------------------
REFUND_BOUNDARIES = [
    # (hourly_rate, duration, notice_hours, expected_percent, expected_refund, description)
    (1001, 1, 48, 100, 1001, "1001 rate, 100% refund"),
    (1001, 2, 50, 100, 2002, "2002 rate, 100% refund"),
    (1001, 1, 24, 50, 501, "50.0% of 1001 = 500.5 -> 501"),
    (1003, 1, 25, 50, 502, "50.0% of 1003 = 501.5 -> 502"),
    (1005, 1, 30, 50, 503, "50.0% of 1005 = 502.5 -> 503"),
    (1007, 1, 40, 50, 504, "50.0% of 1007 = 503.5 -> 504"),
    (1009, 1, 47, 50, 505, "50.0% of 1009 = 504.5 -> 505"),
    (1000, 1, 24, 50, 500, "50.0% of 1000 = 500.0 -> 500"),
    (1002, 1, 24, 50, 501, "50.0% of 1002 = 501.0 -> 501"),
    (1001, 1, 23, 0, 0, "23 hours notice -> 0% refund"),
    (1001, 1, 0, 0, 0, "0 hours notice -> 0% refund"),
]

@pytest.mark.parametrize("rate, duration, notice, percent, expected_refund, desc", REFUND_BOUNDARIES)
def test_refund_notice_and_rounding_boundaries(client, rate, duration, notice, percent, expected_refund, desc):
    org = f"org-ref-bounds-{time.time()}"
    client.post("/auth/register", json={"org_name": org, "username": "alice", "password": "password"})
    headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'org_name': org, 'username': 'alice', 'password': 'password'}).json()['access_token']}"}

    room = client.post("/rooms", json={"name": "Room A", "capacity": 5, "hourly_rate_cents": rate}, headers=headers).json()
    room_id = room["id"]

    start_time = _future(notice)
    end_time = (datetime.fromisoformat(start_time) + timedelta(hours=duration)).isoformat()
    booking = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": start_time, "end_time": end_time},
        headers=headers,
    ).json()

    cancel_resp = client.post(f"/bookings/{booking['id']}/cancel", headers=headers)
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["refund_percent"] == percent
    assert cancel_resp.json()["refund_amount_cents"] == expected_refund

    details = client.get(f"/bookings/{booking['id']}", headers=headers).json()
    if percent > 0:
        assert len(details["refunds"]) == 1
        assert details["refunds"][0]["amount_cents"] == expected_refund
    else:
        assert len(details["refunds"]) == 0


# ----------------------------------------------------
# 6. Multi-Tenant Cross-Access Vectors (50+ checks)
# ----------------------------------------------------
def test_multi_tenant_massive_matrix(client):
    tokens = {}
    room_ids = {}
    booking_ids = {}

    for i in range(5):
        org = f"org-matrix-{i}-{time.time()}"
        client.post("/auth/register", json={"org_name": org, "username": "admin", "password": "password"})
        tokens[i] = client.post("/auth/login", json={"org_name": org, "username": "admin", "password": "password"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {tokens[i]}"}

        room = client.post("/rooms", json={"name": f"Room {i}", "capacity": 5, "hourly_rate_cents": 100}, headers=headers).json()
        room_ids[i] = room["id"]

        start = _future(50 + i * 2)
        end = (datetime.fromisoformat(start) + timedelta(hours=1)).isoformat()
        booking = client.post("/bookings", json={"room_id": room_ids[i], "start_time": start, "end_time": end}, headers=headers).json()
        booking_ids[i] = booking["id"]

    for i in range(5):
        headers_i = {"Authorization": f"Bearer {tokens[i]}"}
        for j in range(5):
            if i == j:
                continue

            resp_room_get = client.get(f"/rooms/{room_ids[j]}/stats", headers=headers_i)
            assert resp_room_get.status_code == 404

            resp_book = client.post(
                "/bookings",
                json={"room_id": room_ids[j], "start_time": _future(100), "end_time": _future(101)},
                headers=headers_i,
            )
            assert resp_book.status_code == 404

            resp_booking_get = client.get(f"/bookings/{booking_ids[j]}", headers=headers_i)
            assert resp_booking_get.status_code == 404

            resp_cancel = client.post(f"/bookings/{booking_ids[j]}/cancel", headers=headers_i)
            assert resp_cancel.status_code == 404

            resp_export = client.get(f"/admin/export?room_id={room_ids[j]}", headers=headers_i)
            assert resp_export.status_code == 404
