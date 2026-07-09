import pytest
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from app.main import app
from app.timeutils import parse_input_datetime

client = TestClient(app)

def test_access_token_lifetime():
    # Bug 1: Access token expiry wrong
    from app.models import User
    from app.auth import create_access_token, decode_token
    user = User(id=123, org_id=1, role="member")
    token = create_access_token(user)
    payload = decode_token(token)
    lifetime_seconds = payload["exp"] - payload["iat"]
    assert lifetime_seconds == 900  # Exactly 15 minutes (900 seconds)

def test_parse_input_datetime():
    # Bug 5: timezone normalization
    # Input is +06:00 offset, so 18:00+06:00 should convert to 12:00 UTC
    dt = parse_input_datetime("2026-07-09T18:00:00+06:00")
    assert dt.hour == 12
    assert dt.tzinfo is None

    # Naive input should stay as is
    dt_naive = parse_input_datetime("2026-07-09T18:00:00")
    assert dt_naive.hour == 18
    assert dt_naive.tzinfo is None

    # Bug 6: Z offset input should convert to naive UTC
    dt_z = parse_input_datetime("2026-07-09T18:00:00Z")
    assert dt_z.hour == 18
    assert dt_z.tzinfo is None

def test_auth_token_revocation_jti():
    # Bug 2 & 3B: JWT token verification and single-use refresh token
    org_name = f"org-token-test-{datetime.now().timestamp()}"
    reg = client.post(
        "/auth/register",
        json={"org_name": org_name, "username": "bob", "password": "password123"},
    )
    assert reg.status_code == 201

    login = client.post(
        "/auth/login",
        json={"org_name": org_name, "username": "bob", "password": "password123"},
    )
    assert login.status_code == 200
    res_data = login.json()
    access_token = res_data["access_token"]
    refresh_token = res_data["refresh_token"]

    # Logout to revoke access token
    headers = {"Authorization": f"Bearer {access_token}"}
    logout = client.post("/auth/logout", headers=headers)
    assert logout.status_code == 200

    # Ensure access token is now invalid (revoked checking jti)
    sec_check = client.get("/bookings", headers=headers)
    assert sec_check.status_code == 401
    assert sec_check.json()["code"] == "UNAUTHORIZED"

    # Now refresh token usage
    refresh_res = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_res.status_code == 200
    new_refresh = refresh_res.json()["refresh_token"]

    # Attempt reuse of the same refresh token - should fail (single-use)
    refresh_reuse = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_reuse.status_code == 401
    assert refresh_reuse.json()["code"] == "UNAUTHORIZED"

def test_auth_register_username_taken():
    # Bug 3A: duplicate username within organization returns 409 USERNAME_TAKEN
    org_name = f"org-reg-test-{datetime.now().timestamp()}"
    reg1 = client.post(
        "/auth/register",
        json={"org_name": org_name, "username": "alice", "password": "password123"},
    )
    assert reg1.status_code == 201

    reg2 = client.post(
        "/auth/register",
        json={"org_name": org_name, "username": "alice", "password": "password123"},
    )
    assert reg2.status_code == 409
    assert reg2.json()["code"] == "USERNAME_TAKEN"

def test_bookings_duration_bounds_and_conflicts():
    # Setup user & room
    org_name = f"org-bookings-test-{datetime.now().timestamp()}"
    reg = client.post(
        "/auth/register",
        json={"org_name": org_name, "username": "alice", "password": "password123"},
    )
    token = client.post(
        "/auth/login",
        json={"org_name": org_name, "username": "alice", "password": "password123"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    room = client.post(
        "/rooms",
        json={"name": "Conference Room", "capacity": 10, "hourly_rate_cents": 2000},
        headers=headers,
    )
    room_id = room.json()["id"]

    # Bug 7: Invalid datetime string returns 400
    res_bad_dt = client.post(
        "/bookings",
        json={
            "room_id": room_id,
            "start_time": "invalid-datetime-string",
            "end_time": "invalid-datetime-string"
        },
        headers=headers,
    )
    assert res_bad_dt.status_code == 400
    assert res_bad_dt.json()["code"] == "INVALID_BOOKING_WINDOW"

    # Bug 4C: end_time <= start_time
    t_start = (datetime.now(timezone.utc) + timedelta(hours=5)).replace(minute=0, second=0, microsecond=0)
    res_invalid_time = client.post(
        "/bookings",
        json={
            "room_id": room_id,
            "start_time": t_start.isoformat(),
            "end_time": (t_start - timedelta(hours=1)).isoformat()
        },
        headers=headers,
    )
    assert res_invalid_time.status_code == 400

    # Bug 4C: duration too short (0 hours)
    res_zero_duration = client.post(
        "/bookings",
        json={
            "room_id": room_id,
            "start_time": t_start.isoformat(),
            "end_time": t_start.isoformat()
        },
        headers=headers,
    )
    assert res_zero_duration.status_code == 400

    # Bug 4C: duration too long (9 hours, limit is 8)
    res_long_duration = client.post(
        "/bookings",
        json={
            "room_id": room_id,
            "start_time": t_start.isoformat(),
            "end_time": (t_start + timedelta(hours=9)).isoformat()
        },
        headers=headers,
    )
    assert res_long_duration.status_code == 400

    # Bug 4B: Booking in the past (historical)
    t_past = (datetime.now(timezone.utc) - timedelta(hours=5)).replace(minute=0, second=0, microsecond=0)
    res_past = client.post(
        "/bookings",
        json={
            "room_id": room_id,
            "start_time": t_past.isoformat(),
            "end_time": (t_past + timedelta(hours=2)).isoformat()
        },
        headers=headers,
    )
    assert res_past.status_code == 400

    # Successful booking (1) - 50 to 52 hours in future
    t1_start = (datetime.now(timezone.utc) + timedelta(hours=50)).replace(minute=0, second=0, microsecond=0)
    t1_end = t1_start + timedelta(hours=2)
    b1 = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": t1_start.isoformat(), "end_time": t1_end.isoformat()},
        headers=headers,
    )
    assert b1.status_code == 201
    b1_id = b1.json()["id"]

    # Bug 16 & 17: UUID-backed reference code validation
    ref = b1.json()["reference_code"]
    assert ref.startswith("CW-")
    assert len(ref) == 11

    # Bug 4A & 11: Back-to-back bookings should be allowed (non-overlapping boundaries)
    # Booking (2) from t1_end to t1_end + 2 hours
    t2_start = t1_end
    t2_end = t2_start + timedelta(hours=2)
    b2 = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": t2_start.isoformat(), "end_time": t2_end.isoformat()},
        headers=headers,
    )
    assert b2.status_code == 201

    # Bookings that overlap should conflict (e.g. t1_start + 1 to t1_end + 1)
    b_conflict = client.post(
        "/bookings",
        json={
            "room_id": room_id,
            "start_time": (t1_start + timedelta(hours=1)).isoformat(),
            "end_time": (t1_end + timedelta(hours=1)).isoformat()
        },
        headers=headers,
    )
    assert b_conflict.status_code == 409

    # Bug 4D: Booking listing sorting, pagination and limit
    # We should have at least two bookings. Let's retrieve them.
    listing = client.get("/bookings?page=1&limit=2", headers=headers)
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert len(items) <= 2
    # Ensure they are sorted ascending by start_time
    assert parse_input_datetime(items[0]["start_time"]) < parse_input_datetime(items[1]["start_time"])

    # Bug 4E: Detail booking does not overwrite start_time
    detail = client.get(f"/bookings/{b1_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["start_time"] == t1_start.replace(tzinfo=None).isoformat() + "+00:00"

    # Bug 4F, 4G: Cancellation notice and rounding
    # Booking is 50 hours in future, notice hours >= 48, refund should be 100%
    cancel = client.post(f"/bookings/{b1_id}/cancel", headers=headers)
    assert cancel.status_code == 200
    assert cancel.json()["refund_percent"] == 100
    assert cancel.json()["refund_amount_cents"] == b1.json()["price_cents"]

    # Booking 2 is 52 hours in future. Let's create a booking closer in future, e.g. 23 hours in future
    t3_start = (datetime.now(timezone.utc) + timedelta(hours=23)).replace(minute=0, second=0, microsecond=0)
    b3 = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": t3_start.isoformat(), "end_time": (t3_start + timedelta(hours=2)).isoformat()},
        headers=headers,
    )
    assert b3.status_code == 201
    b3_id = b3.json()["id"]

    # Cancel b3, notice is 23 hours (<24 hours), refund should be 0%
    cancel3 = client.post(f"/bookings/{b3_id}/cancel", headers=headers)
    assert cancel3.status_code == 200
    assert cancel3.json()["refund_percent"] == 0
    assert cancel3.json()["refund_amount_cents"] == 0

def test_member_ownership():
    # Bug 22: Member ownership check in booking details & cancel
    org_name = f"org-owner-test-{datetime.now().timestamp()}"
    client.post("/auth/register", json={"org_name": org_name, "username": "alice", "password": "password123"})
    token_a = client.post("/auth/login", json={"org_name": org_name, "username": "alice", "password": "password123"}).json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    client.post("/auth/register", json={"org_name": org_name, "username": "bob", "password": "password123"})
    token_b = client.post("/auth/login", json={"org_name": org_name, "username": "bob", "password": "password123"}).json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    room = client.post("/rooms", json={"name": "Room A", "capacity": 5, "hourly_rate_cents": 1000}, headers=headers_a).json()["id"]
    t_start = (datetime.now(timezone.utc) + timedelta(hours=10)).replace(minute=0, second=0, microsecond=0)
    booking = client.post("/bookings", json={"room_id": room, "start_time": t_start.isoformat(), "end_time": (t_start+timedelta(hours=2)).isoformat()}, headers=headers_a).json()
    b_id = booking["id"]

    # Member B tries to view member A's booking (same org, not admin) - should fail with 404
    view_res = client.get(f"/bookings/{b_id}", headers=headers_b)
    assert view_res.status_code == 404

    # Member B tries to cancel member A's booking - should fail with 404
    cancel_res = client.post(f"/bookings/{b_id}/cancel", headers=headers_b)
    assert cancel_res.status_code == 404

def test_export_security():
    # Bug 5 & 38: Export isolates data by organization
    org_a = f"org-exp-a-{datetime.now().timestamp()}"
    client.post("/auth/register", json={"org_name": org_a, "username": "admin_a", "password": "password123"})
    token_a = client.post("/auth/login", json={"org_name": org_a, "username": "admin_a", "password": "password123"}).json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    room_a = client.post("/rooms", json={"name": "Room A", "capacity": 5, "hourly_rate_cents": 1000}, headers=headers_a).json()["id"]
    t_start = (datetime.now(timezone.utc) + timedelta(hours=10)).replace(minute=0, second=0, microsecond=0)
    client.post("/bookings", json={"room_id": room_a, "start_time": t_start.isoformat(), "end_time": (t_start+timedelta(hours=2)).isoformat()}, headers=headers_a)

    org_b = f"org-exp-b-{datetime.now().timestamp()}"
    client.post("/auth/register", json={"org_name": org_b, "username": "admin_b", "password": "password123"})
    token_b = client.post("/auth/login", json={"org_name": org_b, "username": "admin_b", "password": "password123"}).json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # User B tries to export room A's bookings (should be empty because room A belongs to Org A)
    export_res = client.get(f"/admin/export?room_id={room_a}&include_all=true", headers=headers_b)
    assert export_res.status_code == 200
    lines = export_res.text.strip().split("\n")
    assert len(lines) == 1
    assert lines[0].startswith("id,reference_code")
