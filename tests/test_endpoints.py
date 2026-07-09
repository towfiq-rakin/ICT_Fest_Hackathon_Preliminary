import time
import math
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
        dt_local = dt.astimezone(timezone(timedelta(hours=6)))
        return dt_local.isoformat()
    return dt.isoformat()


# ----------------------------------------------------
# 1. Health Endpoint Tests
# ----------------------------------------------------
def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ----------------------------------------------------
# 2. Auth Endpoint Tests
# ----------------------------------------------------
def test_auth_flows(client):
    org = f"org-auth-{time.time()}"
    # Register Admin
    reg = client.post(
        "/auth/register",
        json={"org_name": org, "username": "bob", "password": "password"},
    )
    assert reg.status_code == 201
    assert reg.json()["role"] == "admin"

    # Register Member (second user)
    reg_member = client.post(
        "/auth/register",
        json={"org_name": org, "username": "alice", "password": "password"},
    )
    assert reg_member.status_code == 201
    assert reg_member.json()["role"] == "member"

    # Duplicate username check
    dup = client.post(
        "/auth/register",
        json={"org_name": org, "username": "bob", "password": "password"},
    )
    assert dup.status_code == 409
    assert dup.json()["code"] == "USERNAME_TAKEN"

    # Login Happy Path
    login_resp = client.post(
        "/auth/login",
        json={"org_name": org, "username": "bob", "password": "password"},
    )
    assert login_resp.status_code == 200
    tokens = login_resp.json()
    assert "access_token" in tokens
    assert "refresh_token" in tokens
    assert tokens["token_type"] == "bearer"

    # Login Invalid Credentials
    bad_login = client.post(
        "/auth/login",
        json={"org_name": org, "username": "bob", "password": "wrongpassword"},
    )
    assert bad_login.status_code == 401
    assert bad_login.json()["code"] == "INVALID_CREDENTIALS"

    # Token Refresh Happy Path
    refresh_resp = client.post(
        "/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refresh_resp.status_code == 200
    new_tokens = refresh_resp.json()
    assert "access_token" in new_tokens

    # Refresh Token Reuse Check (Single-use policy)
    reuse_resp = client.post(
        "/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert reuse_resp.status_code == 401
    assert reuse_resp.json()["code"] == "UNAUTHORIZED"

    # Logout Happy Path
    logout_resp = client.post(
        "/auth/logout",
        headers={"Authorization": f"Bearer {new_tokens['access_token']}"},
    )
    assert logout_resp.status_code == 200
    assert logout_resp.json() == {"status": "ok"}

    # Unauthorized access after logout
    check_auth = client.get(
        "/rooms",
        headers={"Authorization": f"Bearer {new_tokens['access_token']}"},
    )
    assert check_auth.status_code == 401
    assert check_auth.json()["code"] == "UNAUTHORIZED"


# ----------------------------------------------------
# 3. Rooms Endpoint Tests
# ----------------------------------------------------
def test_rooms_endpoints(client):
    org = f"org-rooms-{time.time()}"
    client.post(
        "/auth/register",
        json={"org_name": org, "username": "bob", "password": "password"},
    )
    client.post(
        "/auth/register",
        json={"org_name": org, "username": "alice", "password": "password"},
    )

    admin_token = client.post("/auth/login", json={"org_name": org, "username": "bob", "password": "password"}).json()["access_token"]
    member_token = client.post("/auth/login", json={"org_name": org, "username": "alice", "password": "password"}).json()["access_token"]

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    member_headers = {"Authorization": f"Bearer {member_token}"}

    # Create Room by Member -> 403 Forbidden
    resp = client.post(
        "/rooms",
        json={"name": "Forbidden Room", "capacity": 5, "hourly_rate_cents": 500},
        headers=member_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN"

    # Create Room by Admin -> 201 Created
    room_resp = client.post(
        "/rooms",
        json={"name": "Boardroom", "capacity": 12, "hourly_rate_cents": 1500},
        headers=admin_headers,
    )
    assert room_resp.status_code == 201
    room = room_resp.json()
    assert room["name"] == "Boardroom"
    assert room["capacity"] == 12
    assert room["hourly_rate_cents"] == 1500
    room_id = room["id"]

    # List Rooms
    rooms_list = client.get("/rooms", headers=member_headers)
    assert rooms_list.status_code == 200
    assert len(rooms_list.json()) == 1
    assert rooms_list.json()[0]["id"] == room_id

    # Get Availability Happy Path
    avail = client.get(f"/rooms/{room_id}/availability?date=2026-07-10", headers=member_headers)
    assert avail.status_code == 200
    assert avail.json()["busy"] == []

    # Get Availability Invalid Date -> 400
    bad_avail = client.get(f"/rooms/{room_id}/availability?date=2026-07/10", headers=member_headers)
    assert bad_avail.status_code == 400
    assert bad_avail.json()["code"] == "INVALID_BOOKING_WINDOW"

    # Get Room Stats Happy Path
    stats_resp = client.get(f"/rooms/{room_id}/stats", headers=member_headers)
    assert stats_resp.status_code == 200
    assert stats_resp.json() == {
        "room_id": room_id,
        "total_confirmed_bookings": 0,
        "total_revenue_cents": 0,
    }


# ----------------------------------------------------
# 4. Bookings Endpoint Tests
# ----------------------------------------------------
def test_bookings_endpoints(client):
    org = f"org-bookings-{time.time()}"
    client.post(
        "/auth/register",
        json={"org_name": org, "username": "bob", "password": "password"},
    )
    headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'org_name': org, 'username': 'bob', 'password': 'password'}).json()['access_token']}"}

    room = client.post(
        "/rooms",
        json={"name": "Meeting Room", "capacity": 6, "hourly_rate_cents": 1000},
        headers=headers,
    ).json()
    room_id = room["id"]

    # Book with Non-whole Hours Duration -> 400
    start = _future(10)
    # 1.5 hours
    end_half = (datetime.fromisoformat(start) + timedelta(minutes=90)).isoformat()
    resp = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": start, "end_time": end_half},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_BOOKING_WINDOW"

    # Book with Duration > 8 Hours -> 400
    end_long = (datetime.fromisoformat(start) + timedelta(hours=9)).isoformat()
    resp = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": start, "end_time": end_long},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_BOOKING_WINDOW"

    # Book with End Time <= Start Time -> 400
    end_early = (datetime.fromisoformat(start) - timedelta(hours=1)).isoformat()
    resp = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": start, "end_time": end_early},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_BOOKING_WINDOW"

    # Book with invalid date format -> 400
    resp = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": "invalid", "end_time": "invalid"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_BOOKING_WINDOW"

    # Book Happy Path (2 hours)
    end_ok = (datetime.fromisoformat(start) + timedelta(hours=2)).isoformat()
    booking = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": start, "end_time": end_ok},
        headers=headers,
    )
    assert booking.status_code == 201
    b_data = booking.json()
    assert b_data["price_cents"] == 2000
    booking_id = b_data["id"]

    # Get Single Booking Details
    get_b = client.get(f"/bookings/{booking_id}", headers=headers)
    assert get_b.status_code == 200
    assert get_b.json()["id"] == booking_id
    assert get_b.json()["price_cents"] == 2000

    # Get Single Booking Not Found -> 404
    get_b_fail = client.get("/bookings/9999", headers=headers)
    assert get_b_fail.status_code == 404
    assert get_b_fail.json()["code"] == "BOOKING_NOT_FOUND"


# ----------------------------------------------------
# 5. Admin Usage Report and Export Tests
# ----------------------------------------------------
def test_admin_report_and_export(client):
    org = f"org-admin-{time.time()}"
    client.post(
        "/auth/register",
        json={"org_name": org, "username": "bob", "password": "password"},
    )
    headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'org_name': org, 'username': 'bob', 'password': 'password'}).json()['access_token']}"}

    room = client.post(
        "/rooms",
        json={"name": "Exclusive Lounge", "capacity": 8, "hourly_rate_cents": 2500},
        headers=headers,
    ).json()
    room_id = room["id"]

    # Create Booking
    start = _future(10)
    end = (datetime.fromisoformat(start) + timedelta(hours=2)).isoformat()
    client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": start, "end_time": end},
        headers=headers,
    )

    # Fetch Usage Report Happy Path
    today_str = datetime.utcnow().date().isoformat()
    tomorrow_str = (datetime.utcnow() + timedelta(days=2)).date().isoformat()
    report = client.get(f"/admin/usage-report?from={today_str}&to={tomorrow_str}", headers=headers)
    assert report.status_code == 200
    r_data = report.json()
    assert r_data["from"] == today_str
    assert r_data["to"] == tomorrow_str
    assert len(r_data["rooms"]) == 1
    assert r_data["rooms"][0]["room_id"] == room_id
    assert r_data["rooms"][0]["confirmed_bookings"] == 1
    assert r_data["rooms"][0]["revenue_cents"] == 5000

    # Fetch Usage Report Invalid Date Range -> 400
    bad_report = client.get(f"/admin/usage-report?from=bad&to=bad", headers=headers)
    assert bad_report.status_code == 400
    assert bad_report.json()["code"] == "INVALID_BOOKING_WINDOW"

    # Export CSV Happy Path
    export_resp = client.get("/admin/export", headers=headers)
    assert export_resp.status_code == 200
    assert "text/csv" in export_resp.headers["content-type"]
    csv_content = export_resp.text
    assert "id,reference_code,room_id,user_id,start_time,end_time,status,price_cents" in csv_content
    assert str(room_id) in csv_content

    # Export CSV Invalid Room ID (cross-tenant simulation) -> 404
    export_fail = client.get(f"/admin/export?room_id=9999", headers=headers)
    assert export_fail.status_code == 404
    assert export_fail.json()["code"] == "ROOM_NOT_FOUND"
