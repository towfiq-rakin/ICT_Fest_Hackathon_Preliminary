import math
import time
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, engine
from app.timeutils import iso_utc
from app.services import ratelimit, stats, reference
from app import auth

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_db():
    from sqlalchemy import text
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


def _future(hours: int, tz_offset: str = None) -> str:
    dt = datetime.now(timezone.utc) + timedelta(hours=hours)
    dt = dt.replace(minute=0, second=0, microsecond=0)
    if tz_offset == "+06:00":
        # Adjust time by +6 hours to simulate local offset
        dt_local = dt.astimezone(timezone(timedelta(hours=6)))
        return dt_local.isoformat()
    return dt.isoformat()


def test_registration_duplicate_username(client):
    org = f"org-reg-{time.time()}"
    # Register admin
    reg1 = client.post(
        "/auth/register",
        json={"org_name": org, "username": "bob", "password": "password"},
    )
    assert reg1.status_code == 201
    assert reg1.json()["role"] == "admin"

    # Try duplicate username in same org
    reg2 = client.post(
        "/auth/register",
        json={"org_name": org, "username": "bob", "password": "password"},
    )
    assert reg2.status_code == 409
    assert reg2.json()["code"] == "USERNAME_TAKEN"


def test_timezone_conversion(client):
    org = f"org-tz-{time.time()}"
    reg = client.post(
        "/auth/register",
        json={"org_name": org, "username": "alice", "password": "password"},
    )
    headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'org_name': org, 'username': 'alice', 'password': 'password'}).json()['access_token']}"}

    room = client.post(
        "/rooms",
        json={"name": "Conf room", "capacity": 10, "hourly_rate_cents": 1000},
        headers=headers,
    )
    room_id = room.json()["id"]

    # Use +06:00 offset for start_time
    start_str = _future(10, tz_offset="+06:00")
    end_str = _future(12, tz_offset="+06:00")

    booking = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": start_str, "end_time": end_str},
        headers=headers,
    )
    assert booking.status_code == 201
    # Check that start_time is converted to UTC (with +00:00 or Z)
    resp = booking.json()
    assert "+00:00" in resp["start_time"] or "Z" in resp["start_time"]


def test_future_check(client):
    org = f"org-fut-{time.time()}"
    client.post(
        "/auth/register",
        json={"org_name": org, "username": "alice", "password": "password"},
    )
    headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'org_name': org, 'username': 'alice', 'password': 'password'}).json()['access_token']}"}

    room = client.post(
        "/rooms",
        json={"name": "Conf room", "capacity": 10, "hourly_rate_cents": 1000},
        headers=headers,
    )
    room_id = room.json()["id"]

    # Try booking in the past
    past_start = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    past_end = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    booking = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": past_start, "end_time": past_end},
        headers=headers,
    )
    assert booking.status_code == 400
    assert booking.json()["code"] == "INVALID_BOOKING_WINDOW"


def test_overlap_conflicts(client):
    org = f"org-overlap-{time.time()}"
    client.post(
        "/auth/register",
        json={"org_name": org, "username": "alice", "password": "password"},
    )
    headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'org_name': org, 'username': 'alice', 'password': 'password'}).json()['access_token']}"}

    room = client.post(
        "/rooms",
        json={"name": "Conf room", "capacity": 10, "hourly_rate_cents": 1000},
        headers=headers,
    )
    room_id = room.json()["id"]

    # Book 50 to 52
    b1 = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": _future(50), "end_time": _future(52)},
        headers=headers,
    )
    assert b1.status_code == 201

    # Book overlapping: 51 to 53 -> Conflict
    b2 = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": _future(51), "end_time": _future(53)},
        headers=headers,
    )
    assert b2.status_code == 409
    assert b2.json()["code"] == "ROOM_CONFLICT"

    # Book back-to-back: 48 to 50 -> Success
    b3 = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": _future(48), "end_time": _future(50)},
        headers=headers,
    )
    assert b3.status_code == 201

    # Book back-to-back: 52 to 54 -> Success
    b4 = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": _future(52), "end_time": _future(54)},
        headers=headers,
    )
    assert b4.status_code == 201


def test_quota_limits(client):
    org = f"org-quota-{time.time()}"
    client.post(
        "/auth/register",
        json={"org_name": org, "username": "admin", "password": "password"},
    )
    # Register member
    client.post(
        "/auth/register",
        json={"org_name": org, "username": "alice", "password": "password"},
    )
    admin_headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'org_name': org, 'username': 'admin', 'password': 'password'}).json()['access_token']}"}
    headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'org_name': org, 'username': 'alice', 'password': 'password'}).json()['access_token']}"}

    room = client.post(
        "/rooms",
        json={"name": "Conf room", "capacity": 10, "hourly_rate_cents": 1000},
        headers=admin_headers,
    )
    room_id = room.json()["id"]

    # Book 3 slots in next 24h
    for i in range(1, 4):
        b = client.post(
            "/bookings",
            json={"room_id": room_id, "start_time": _future(i * 3), "end_time": _future(i * 3 + 1)},
            headers=headers,
        )
        assert b.status_code == 201

    # Try booking 4th -> Quota exceeded
    b4 = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": _future(15), "end_time": _future(16)},
        headers=headers,
    )
    assert b4.status_code == 409
    assert b4.json()["code"] == "QUOTA_EXCEEDED"


def test_rate_limiting(client):
    org = f"org-rate-{time.time()}"
    client.post(
        "/auth/register",
        json={"org_name": org, "username": "alice", "password": "password"},
    )
    headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'org_name': org, 'username': 'alice', 'password': 'password'}).json()['access_token']}"}

    # Under our code ratelimit check runs fast but settles.
    # Send 21 requests. 21st should return 429
    for i in range(20):
        # We can just send invalid booking window to trigger quick checks (all requests count)
        resp = client.post(
            "/bookings",
            json={"room_id": 9999, "start_time": "invalid", "end_time": "invalid"},
            headers=headers,
        )
        # Any response is fine as long as it registers, but rate limit will hit eventually
        if resp.status_code == 429:
            assert resp.json()["code"] == "RATE_LIMITED"
            return

    # If it didn't hit yet, 21st MUST hit
    resp = client.post(
        "/bookings",
        json={"room_id": 9999, "start_time": "invalid", "end_time": "invalid"},
        headers=headers,
    )
    assert resp.status_code == 429
    assert resp.json()["code"] == "RATE_LIMITED"


def test_refund_notice_and_rounding(client):
    org = f"org-refund-{time.time()}"
    client.post(
        "/auth/register",
        json={"org_name": org, "username": "alice", "password": "password"},
    )
    headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'org_name': org, 'username': 'alice', 'password': 'password'}).json()['access_token']}"}

    # Room with hourly rate of 1001 cents so we test 50% rounding up of 1001 = 501
    room = client.post(
        "/rooms",
        json={"name": "Conf room", "capacity": 10, "hourly_rate_cents": 1001},
        headers=headers,
    )
    room_id = room.json()["id"]

    # 1. 100% refund (notice >= 48 hours)
    b1 = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": _future(50), "end_time": _future(51)},
        headers=headers,
    ).json()
    cancel1 = client.post(f"/bookings/{b1['id']}/cancel", headers=headers)
    assert cancel1.status_code == 200
    assert cancel1.json()["refund_percent"] == 100
    assert cancel1.json()["refund_amount_cents"] == 1001

    # 2. 50% refund (24 <= notice < 48 hours)
    b2 = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": _future(30), "end_time": _future(31)},
        headers=headers,
    ).json()
    cancel2 = client.post(f"/bookings/{b2['id']}/cancel", headers=headers)
    assert cancel2.status_code == 200
    assert cancel2.json()["refund_percent"] == 50
    # 50% of 1001 = 500.5. Rounds to 501 half-up!
    assert cancel2.json()["refund_amount_cents"] == 501

    # 3. 0% refund (notice < 24 hours)
    b3 = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": _future(5), "end_time": _future(6)},
        headers=headers,
    ).json()
    cancel3 = client.post(f"/bookings/{b3['id']}/cancel", headers=headers)
    assert cancel3.status_code == 200
    assert cancel3.json()["refund_percent"] == 0
    assert cancel3.json()["refund_amount_cents"] == 0

    # 4. Invalidation and log check
    get_b2 = client.get(f"/bookings/{b2['id']}", headers=headers)
    assert len(get_b2.json()["refunds"]) == 1
    assert get_b2.json()["refunds"][0]["amount_cents"] == 501

    # 5. Already cancelled
    cancel_again = client.post(f"/bookings/{b2['id']}/cancel", headers=headers)
    assert cancel_again.status_code == 409
    assert cancel_again.json()["code"] == "ALREADY_CANCELLED"


def test_token_invalidation_and_refresh_reuse(client):
    org = f"org-tok-{time.time()}"
    client.post(
        "/auth/register",
        json={"org_name": org, "username": "alice", "password": "password"},
    )
    login = client.post(
        "/auth/login",
        json={"org_name": org, "username": "alice", "password": "password"},
    ).json()

    access_token = login["access_token"]
    refresh_token = login["refresh_token"]

    headers = {"Authorization": f"Bearer {access_token}"}
    # Check simple auth works
    assert client.get("/rooms", headers=headers).status_code == 200

    # Logout
    logout = client.post("/auth/logout", headers=headers)
    assert logout.status_code == 200

    # Subsequent use of access token -> 401
    assert client.get("/rooms", headers=headers).status_code == 401

    # Refresh token works once
    ref1 = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert ref1.status_code == 200
    new_refresh = ref1.json()["refresh_token"]

    # Refresh token reuse -> 401
    ref2 = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert ref2.status_code == 401

    # New refresh token works once
    ref3 = client.post("/auth/refresh", json={"refresh_token": new_refresh})
    assert ref3.status_code == 200


def test_multi_tenancy_isolation(client):
    orgA = f"orgA-{time.time()}"
    orgB = f"orgB-{time.time()}"

    client.post("/auth/register", json={"org_name": orgA, "username": "admin", "password": "password"})
    client.post("/auth/register", json={"org_name": orgB, "username": "admin", "password": "password"})

    tokenA = client.post("/auth/login", json={"org_name": orgA, "username": "admin", "password": "password"}).json()["access_token"]
    tokenB = client.post("/auth/login", json={"org_name": orgB, "username": "admin", "password": "password"}).json()["access_token"]

    headersA = {"Authorization": f"Bearer {tokenA}"}
    headersB = {"Authorization": f"Bearer {tokenB}"}

    # Admin A creates Room A
    roomA = client.post("/rooms", json={"name": "Room A", "capacity": 5, "hourly_rate_cents": 100}, headers=headersA).json()
    roomA_id = roomA["id"]

    # Admin B lists rooms, should not see Room A
    listB = client.get("/rooms", headers=headersB).json()
    assert not any(r["id"] == roomA_id for r in listB)

    # Admin B tries to create booking in Room A -> 404 ROOM_NOT_FOUND
    b = client.post("/bookings", json={"room_id": roomA_id, "start_time": _future(10), "end_time": _future(11)}, headers=headersB)
    assert b.status_code == 404

    # Admin B tries to get Room A detail/availability -> 404
    av = client.get(f"/rooms/{roomA_id}/availability?date=2026-07-10", headers=headersB)
    assert av.status_code == 404


def test_pagination_and_ordering(client):
    org = f"org-pag-{time.time()}"
    client.post(
        "/auth/register",
        json={"org_name": org, "username": "alice", "password": "password"},
    )
    headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'org_name': org, 'username': 'alice', 'password': 'password'}).json()['access_token']}"}

    room = client.post(
        "/rooms",
        json={"name": "Conf room", "capacity": 10, "hourly_rate_cents": 1000},
        headers=headers,
    )
    room_id = room.json()["id"]

    # Create bookings out of order (chronologically)
    # B1 at +60h
    # B2 at +50h
    # B3 at +70h
    b1 = client.post("/bookings", json={"room_id": room_id, "start_time": _future(60), "end_time": _future(61)}, headers=headers).json()
    b2 = client.post("/bookings", json={"room_id": room_id, "start_time": _future(50), "end_time": _future(51)}, headers=headers).json()
    b3 = client.post("/bookings", json={"room_id": room_id, "start_time": _future(70), "end_time": _future(71)}, headers=headers).json()

    # List bookings paginated
    listing = client.get("/bookings?page=1&limit=2", headers=headers).json()
    assert listing["total"] == 3
    # Sorted ascending by start_time: b2 (+50h), then b1 (+60h)
    assert listing["items"][0]["id"] == b2["id"]
    assert listing["items"][1]["id"] == b1["id"]

    # Page 2 should have b3 (+70h)
    listing2 = client.get("/bookings?page=2&limit=2", headers=headers).json()
    assert len(listing2["items"]) == 1
    assert listing2["items"][0]["id"] == b3["id"]
