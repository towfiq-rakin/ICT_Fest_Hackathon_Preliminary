# CoWork Bug Report

### Bug 1 - Access Token Expiry Calculated Incorrectly
**File:** [app/auth.py](app/auth.py#L50), line 50

**Bug:** `timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)` was missing `minutes=`, causing the token expiration to default to 15 days instead of 15 minutes.

**Fix:** Explicitly passed `minutes=ACCESS_TOKEN_EXPIRE_MINUTES`.

### Bug 2 - Logout Revoked Check Uses Wrong Claim
**File:** [app/auth.py](app/auth.py#L97), line 97

**Bug:** The revocation check `payload.get("sub") in _revoked_tokens` checked the user ID instead of the token's unique ID (`jti`). Logging out did not blacklist the specific token.

**Fix:** Changed the check to use `payload.get("jti")`.

### Bug 3 - Registration Does Not Return 409 for Duplicate Username
**File:** [app/routers/auth.py](app/routers/auth.py#L37), line 37

**Bug:** Registering a duplicate username returned HTTP 200 OK with the existing user's details instead of raising a conflict.

**Fix:** Raised `AppError(409, "USERNAME_TAKEN", ...)` if the username is already taken.

### Bug 4 - Refresh Tokens Are Not Single-Use
**File:** [app/routers/auth.py](app/routers/auth.py#L88), line 88

**Bug:** The `/refresh` endpoint did not invalidate the refresh token after use, violating the single-use token requirement.

**Fix:** Added the old token's `jti` to the `_revoked_tokens` list before generating the new token pair.

### Bug 5 - Datetime Timezone Conversion Strips Offset
**File:** [app/timeutils.py](app/timeutils.py#L13), line 13

**Bug:** `parse_input_datetime` stripped the `tzinfo` from aware datetimes without first converting them to UTC. This altered the absolute time for non-UTC offsets.

**Fix:** Added `.astimezone(timezone.utc)` before dropping the `tzinfo`.

### Bug 6 - Start Time Allows 5-Minute Grace Window in the Past
**File:** [app/routers/bookings.py](app/routers/bookings.py#L86), line 86

**Bug:** The `create_booking` check `start >= now - timedelta(minutes=5)` allowed bookings up to 5 minutes in the past, violating the rule that booking start times must be strictly in the future.

**Fix:** Changed check to strictly `start > now` (implemented as `start <= now: raise AppError`).

### Bug 7 - Overlap Check Blocks Back-to-Back Bookings
**File:** [app/routers/bookings.py](app/routers/bookings.py#L50), line 50

**Bug:** The conflict check used `<=` and `>=`, causing a booking ending at 14:00 to conflict with a booking starting at 14:00.

**Fix:** Changed to strict `<` (`b.start_time < end and start < b.end_time`).

### Bug 8 - Missing Minimum Duration Check
**File:** [app/routers/bookings.py](app/routers/bookings.py#L90), line 90

**Bug:** Checked for maximum duration but failed to enforce `MIN_DURATION_HOURS`.

**Fix:** Enforced `duration_hours >= MIN_DURATION_HOURS` by raising `AppError` on violations.

### Bug 9 - Missing `end_time > start_time` Validation
**File:** [app/routers/bookings.py](app/routers/bookings.py#L83), line 83

**Bug:** Failed to validate that `end_time` is logically after `start_time`.

**Fix:** Added validation for `end <= start` to raise a 400 error.

### Bug 10 - `list_bookings` Ordering, Offset, and Limit
**File:** [app/routers/bookings.py](app/routers/bookings.py#L137), line 137

**Bug:** Ordered by `desc()` instead of `asc()`. Offset calculated as `page * limit` instead of `(page - 1) * limit`. Hardcoded `.limit(10)` instead of using the query parameter.

**Fix:** Corrected all three to `asc()`, `(page - 1) * limit`, and `.limit(limit)`.

### Bug 11 - `get_booking` Overwrites `start_time`
**File:** [app/routers/bookings.py](app/routers/bookings.py#L166), line 166

**Bug:** The endpoint accidentally reassigned `booking.start_time = booking.created_at` before serialization.

**Fix:** Removed the reassignment line.

### Bug 12 - Refund Policy `< 24h` Returns 50%
**File:** [app/routers/bookings.py](app/routers/bookings.py#L206), line 206

**Bug:** `notice_hours < 24` fell into the `else` block which was set to `refund_percent = 50` instead of `0`.

**Fix:** Corrected the else block to `refund_percent = 0`.

### Bug 13 - `refund_amount_cents` Inconsistency
**File:** [app/routers/bookings.py](app/routers/bookings.py#L208), lines 208–210

**Bug:** Cancel response computed `refund_amount_cents` independently from `log_refund()`. Different rounding could cause them to diverge.

**Fix:** `log_refund()` returns the RefundLog entry; `refund_amount_cents = refund_log.amount_cents`.

### Bug 14 - Refund Rounding Uses Truncation Instead of Half-Up
**File:** [app/services/refunds.py](app/services/refunds.py#L17), line 17

**Bug:** `int(refund_dollars * 100)` truncates instead of rounding. Spec requires half-cents round up.

**Fix:** Changed calculation to `math.floor(booking.price_cents * percent / 100.0 + 0.5)`.

### Bug 15 - Reference Code Counter Is Not Atomic
**File:** [app/services/reference.py](app/services/reference.py#L10), global file

**Bug:** Non-atomic read-modify-write with a `time.sleep(0.12)` between read and write guarantees duplicate codes under concurrency.

**Fix:** Protected with `threading.Lock()`, removed the sleep.

### Bug 16 - Rate Limiter Records Request Before Checking Limit
**File:** [app/services/ratelimit.py](app/services/ratelimit.py#L20), line 20

**Bug:** Request appended to bucket before the limit check, plus a `time.sleep(0.1)` created race conditions. The 21st request always passed.

**Fix:** Check `len(bucket) >= _MAX_REQUESTS` before appending; protected with `threading.Lock()`.

### Bug 17 - Room Stats Use Inconsistent In-Memory Cache
**File:** [app/services/stats.py](app/services/stats.py#L10), global file

**Bug:** In-memory read-modify-write with `time.sleep(0.1)` between read and write guaranteed stale/wrong stats under concurrent bookings/cancellations. Additionally, on application reboot, lazy-loaded in-memory entries defaulted to `{"count": 0, "revenue": 0}` regardless of existing DB records.

**Fix:** Removed in-memory cache entirely. `stats.get()` now queries DB directly with `COUNT`/`SUM` aggregates for always-consistent results.

### Bug 18 - Deadlock in Notifications Service
**File:** [app/services/notifications.py](app/services/notifications.py#L24), line 24

**Bug:** `notify_created` acquired `_email_lock` then `_audit_lock`, while `notify_cancelled` acquired `_audit_lock` then `_email_lock`. This lock-order inversion caused deadlocks under concurrent load.

**Fix:** Modified both functions to always acquire locks in the same order (`_email_lock` then `_audit_lock`).

### Bug 19 - Double Cancel Race Condition
**File:** [app/routers/bookings.py](app/routers/bookings.py#L182), line 182 and [app/services/refunds.py](app/services/refunds.py#L10), line 10

**Bug:** `log_refund` committed its transaction, then `_settlement_pause()` ran before setting `booking.status = "cancelled"` and committing. This allowed a concurrent cancel request to pass the `booking.status == "cancelled"` check, resulting in multiple refunds.

**Fix:** `log_refund` now uses `db.flush()` instead of `db.commit()`. The status change and refund log are committed atomically in the router after `log_refund` returns. Removed the artificial `_settlement_pause()`.

### Bug 20 - Multi-Tenancy Bypass in Export
**File:** [app/services/export.py](app/services/export.py#L24), line 24

**Bug:** When `include_all=True` and `room_id` was provided, the export used `fetch_bookings_raw(db, room_id)` which queried the `bookings` table directly without joining `Room` and checking `org_id`. This allowed an admin to export bookings from another organization's room.

**Fix:** Modified `generate_export` to always use `_fetch_scoped(db, org_id, None, room_id)` for the `include_all` case, which enforces the `org_id` isolation.

### Bug 21 - `get_booking` Allows Cross-Member Read
**File:** [app/routers/bookings.py](app/routers/bookings.py#L160), line 160

**Bug:** The endpoint checked that the room belonged to the caller's organization (`Room.org_id == user.org_id`), but did not enforce Rule 10 ("Members may read and cancel only their own bookings"). A member could query another member's booking ID and read it.

**Fix:** Added `if user.role != "admin" and booking.user_id != user.id: raise AppError(404, "BOOKING_NOT_FOUND", "Booking not found")`.

### Bug 22 - Concurrency Races in Booking Creation
**File:** [app/routers/bookings.py](app/routers/bookings.py#L65), line 65

**Bug:** The `_has_conflict()` and `_check_quota()` functions read from the database, experienced an artificial delay (`time.sleep()`), and then the booking was inserted. This created concurrent race windows.

**Fix:** Created a global `_booking_lock = threading.Lock()` and wrapped the conflict check, quota check, and `db.commit()` inside this lock to make the check-and-insert sequence atomic across concurrent requests.

### Bug 23 - Missing Duplicate Name Check on Room Creation
**File:** [app/routers/rooms.py](app/routers/rooms.py#L42), line 42

**Bug:** The `create_room` endpoint did not check if a room with the same name already existed in the organization. If a duplicate was inserted, SQLite's unique constraint threw an `IntegrityError`, resulting in a 500 Internal Server Error instead of the required 409 Conflict.

**Fix:** Added an explicit query for `existing = db.query(Room).filter(...)` and raised a 409 `ROOM_CONFLICT` AppError.

### Bug 24 - Missing Validation on Room Capacity and Rate
**File:** [app/routers/rooms.py](app/routers/rooms.py#L48), line 48

**Bug:** Pydantic's `RoomCreateRequest` did not enforce the business rules that capacity must be `> 0` and hourly rate `>= 0`. Negative values could be stored.

**Fix:** Added an explicit check in `create_room` to ensure `capacity > 0` and `hourly_rate_cents >= 0`, raising a 400 Bad Request otherwise.

### Bug 25 - Missing Database UniqueConstraint on Room
**File:** [app/models.py](app/models.py#L36), line 36

**Bug:** The `Room` model did not have `__table_args__ = (UniqueConstraint("org_id", "name"),)` defined, meaning the database layer did not actually enforce room name uniqueness per organization. If the application-level check failed or was bypassed, the database would happily store duplicates.

**Fix:** Added the `UniqueConstraint` to the `Room` model.

### Bug 26 - Missing Unique Constraint on Reference Code
**File:** [app/models.py](app/models.py#L47), line 47

**Bug:** The business rules dictate that reference codes must be unique system-wide. The `reference_code` column on the `Booking` model was missing `unique=True`.

**Fix:** Added `unique=True` to the `reference_code` column definition.

### Bug 27 - Room Creation Fails to Invalidate Report Cache
**File:** [app/routers/rooms.py](app/routers/rooms.py#L66), line 66

**Bug:** The `create_room` endpoint did not invalidate the organization's usage report cache. Since the usage report returns a list of *all* rooms in the organization (even those with 0 bookings), a newly created room would not appear in the report until the cache naturally expired.

**Fix:** Added `cache.invalidate_report(admin.org_id)` to the end of `create_room`.

### Bug 28 - Missing Past Booking Check on Cancellation
**File:** [app/routers/bookings.py](app/routers/bookings.py#L207), line 207

**Bug:** The `cancel_booking` endpoint calculated the notice period, but did not check if the booking had already started or was in the past. If a past booking was canceled, the `notice.total_seconds()` would be negative, which fell through to the `else` block (0% refund) and successfully cancelled the past booking, violating the rule: "Cancelling is prohibited if start_time is in the past".

**Fix:** Added an explicit check `if booking.start_time <= datetime.utcnow(): raise AppError(400, "INVALID_BOOKING_WINDOW", ...)` to prevent past cancellations.

### Bug 29 - Admin List Bookings Missing Org Scope
**File:** [app/routers/bookings.py](app/routers/bookings.py#L134), line 134

**Bug:** The `list_bookings` endpoint unconditionally filtered by `Booking.user_id == user.id`. This meant that even organization admins could only see their own personal bookings, rather than all bookings across the organization, violating Rule 9.

**Fix:** Added a conditional check. If `user.role == "admin"`, it joins `Room` and filters by `Room.org_id == user.org_id`.

### Bug 30 - Artificial Sleeps Still Active Inside Global Booking Lock
**File:** [app/routers/bookings.py](app/routers/bookings.py#L30), lines 30–55

**Bug:** After the Bug 22/23 fix wrapped conflict and quota checks inside `_booking_lock`, the artificial `time.sleep()` calls inside `_pricing_warmup()` (0.12 s) and `_quota_audit()` (0.1 s) were left in place. Because these helpers are called from within the lock, every booking-creation request holds the global lock for at least 0.22 seconds. With multiple concurrent users this serializes all `POST /bookings` across the entire service, easily causing multi-second stalls and violating Rule 16.

**Fix:** Removed `_pricing_warmup()`, `_quota_audit()`, and `_settlement_pause()` function definitions entirely, along with their call sites inside `_has_conflict()` and `_check_quota()`. Removed the now-unused `import time`.

### Bug 31 - Start Time Check Uses `>=` Instead of `>`
**File:** [app/routers/bookings.py](app/routers/bookings.py#L80), line 80

**Bug:** The guard `if start >= now` allowed a booking with `start_time == now` to pass validation. The spec (Rule 2) states start_time must be strictly in the future with no grace window of any size. A booking with `start == now` is instantaneously in the past once stored.

**Fix:** Changed condition to `if start <= now: raise AppError(...)`, effectively requiring `start > now`.

### Bug 32 - Revoked Token Set Grows Without Bound
**File:** [app/auth.py](app/auth.py#L24), line 24

**Bug:** `_revoked_tokens` was a plain `set[str]` that entries were only ever added to (on logout and refresh). Tokens expire after 15 minutes (access) or 7 days (refresh), but their JTIs stayed in the set forever. Under sustained use the set grows without limit, eventually exhausting memory and crashing the process.

**Fix:** Changed `_revoked_tokens` to `dict[str, int]` mapping `jti → exp_timestamp`. Added `_prune_revoked()` which removes entries whose `exp` has already passed. `_prune_revoked()` is called at the start of `get_token_payload()` so the set is periodically trimmed on every authenticated request. `revoke_access_token()` now stores `payload["jti"] → payload["exp"]` instead of using `.add()`.

### Bug 33 - Cache Module Has No Thread Safety
**File:** [app/cache.py](app/cache.py#L10), line 10

**Bug:** `_report_cache` and `_availability_cache` were plain dicts mutated directly from request-handling threads without any lock. The `invalidate_report()` function built a snapshot of keys and then popped them in two separate steps; a concurrent `set_report()` call between those steps could insert a new stale entry that was never evicted, causing the cache to serve outdated report data indefinitely.

**Fix:** Added `_cache_lock = threading.Lock()` and wrapped all reads and writes in every cache function with `with _cache_lock:`, making all mutations atomic.

### Bug 34 - Usage Report Accepts Inverted Date Range Silently
**File:** [app/routers/admin.py](app/routers/admin.py#L29), lines 29–36

**Bug:** When `from > to` was supplied (e.g. `?from=2025-12-31&to=2025-01-01`), the computed `range_end` was earlier than `range_start`. The DB query returned zero bookings for every room and the endpoint responded with HTTP 200 and an empty-looking (but structurally valid) report.

**Fix:** Added an explicit check `if from_date > to_date: raise AppError(400, "INVALID_BOOKING_WINDOW", "from date must not be after to date")` immediately after parsing the dates.

### Bug 35 - Database Session Missing Rollback on Exception
**File:** [app/database.py](app/database.py#L17), lines 17–23

**Bug:** The `get_db()` dependency only had a `finally: db.close()` block. If an unhandled exception propagated out of a route after a `db.flush()` but before `db.commit()` (e.g. an unexpected `IntegrityError`), the session was closed without an explicit rollback. While SQLAlchemy usually rolls back implicitly on close, a session in a broken transaction state can return its underlying connection to the pool in an unusable state.

**Fix:** Added `except Exception: db.rollback(); raise` before the `finally` block, ensuring the session is always cleanly rolled back before being closed.

### Bug 36 - `Z` Suffix Not Supported in Python 3.9 `fromisoformat()`
**File:** [app/timeutils.py](app/timeutils.py#L11), line 11

**Bug:** Python 3.9's `datetime.fromisoformat()` does not accept the trailing `Z` UTC designator (e.g. `"2025-07-09T10:00:00Z"` raises `ValueError`). Any client sending ISO 8601 datetimes with `Z` as the UTC marker would receive a 500 Internal Server Error instead of processing the booking correctly.

**Fix:** Added `.replace("Z", "+00:00")` before parsing: `datetime.fromisoformat(value.replace("Z", "+00:00"))`. This normalises `Z` to the explicit `+00:00` offset, which is accepted by all Python versions.

### Bug 37 - Booking Quota Incorrectly Applied to Admins
**File:** [app/routers/bookings.py](app/routers/bookings.py#L101), lines 101–102

**Bug:** The `_check_quota()` function was called unconditionally for all users, including admins. The 3-booking-per-24h rolling window quota is a member-only constraint. Admins performing operational bookings on behalf of the organisation were blocked by this limit.

**Fix:** Added a role guard `if user.role != "admin": _check_quota(...)` so the quota check is only executed for member-role users. Admins bypass it entirely.

### Bug 38 - `_pricing_warmup()` sleep inside SQLite write lock
**File:** [app/routers/bookings.py](app/routers/bookings.py#L30), `_has_conflict()`

**Bug:** `_pricing_warmup()` called `time.sleep(0.12)` inside `_has_conflict()`, which executes within a `BEGIN IMMEDIATE` transaction holding the SQLite exclusive write lock. Every booking creation blocked ALL other write operations for 120ms.

**Fix:** Removed the artificial `_pricing_warmup()` call.

### Bug 39 - `_quota_audit()` sleep inside SQLite write lock
**File:** [app/routers/bookings.py](app/routers/bookings.py#L30), `_check_quota()`

**Bug:** `_quota_audit()` called `time.sleep(0.1)` inside `_check_quota()`, also within the `BEGIN IMMEDIATE` write lock. Combined with Bug 38, every member booking held the exclusive DB lock for 220ms+.

**Fix:** Removed the artificial `_quota_audit()` call.

### Bug 40 - `_aggregate_pause()` sleep inside `_stats_lock`
**File:** [app/services/stats.py](app/services/stats.py#L14), `record_create()` and `record_cancel()`

**Bug:** `_aggregate_pause()` called `time.sleep(0.1)` while holding `_stats_lock`. Since every booking create/cancel calls `record_create`/`record_cancel`, all stats operations serialized behind a 100ms bottleneck.

**Fix:** Removed the artificial `_aggregate_pause()` calls from both functions and replaced the stats service in-memory cache with direct DB query aggregations.

### Bug 41 - `_settle_pause()` sleep inside `_ratelimit_lock`
**File:** [app/services/ratelimit.py](app/services/ratelimit.py#L14), `record_and_check()`

**Bug:** `_settle_pause()` called `time.sleep(0.1)` while holding `_ratelimit_lock`. Every booking attempt (regardless of user) waited behind a single 100ms-held global lock, preventing concurrent booking requests from proceeding.

**Fix:** Removed the artificial `_settle_pause()` call.

### Bug 42 - `_format_pause()` sleep inside `_reference_lock`
**File:** [app/services/reference.py](app/services/reference.py#L14), `next_reference_code()`

**Bug:** `_format_pause()` called `time.sleep(0.12)` while holding `_reference_lock`. Reference code generation is on the critical path of every booking creation, serializing all concurrent bookings behind a 120ms lock hold.

**Fix:** Removed the artificial `_format_pause()` call.

### Bug 43 - Notification sleeps serializing all requests
**File:** [app/services/notifications.py](app/services/notifications.py#L14), `_send_email()` and `_write_audit()`

**Bug:** `_send_email()` slept 120ms inside `_email_lock` and `_write_audit()` slept 100ms inside `_audit_lock`. Both are called on every booking create/cancel. Two global locks held for a combined 220ms serialized all post-commit processing, even though the DB transaction was already committed.

**Fix:** Removed the artificial sleeps from both functions.

### Bug 44 - Org registration TOCTOU race causes 500 error
**File:** [app/routers/auth.py](app/routers/auth.py#L24), `register()`

**Bug:** Two concurrent `POST /auth/register` requests with the same new `org_name` both see `org=None`, both set `role="admin"`, and both attempt to `INSERT` the organization. Since `Organization.name` has `unique=True`, the second insert crashes with an unhandled `IntegrityError` returning an HTTP 500.

**Fix:** Wrapped the org creation in a `try/except IntegrityError` block. On conflict, the session is rolled back, the existing org is re-queried, and the role is correctly set to `"member"`.

### Bug 45 - `stats.record_cancel` allows negative revenue
**File:** [app/services/stats.py](app/services/stats.py#L26), `record_cancel()`

**Bug:** `record_cancel` applied `max(0, count - 1)` to prevent negative booking count but used bare `revenue - price_cents` for revenue, which could go negative if stats were initialized at an inconsistent point.

**Fix:** Stats service now queries the DB directly with `COUNT`/`SUM` aggregates, avoiding negative revenue entirely.
