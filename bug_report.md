# bug_report.md

## 1. app/timeutils.py

- **Location:** `parse_input_datetime` function.
- **Bug:** Uses `dt.replace(tzinfo=None)` directly, which discards the timezone offset instead of converting the time value to UTC first.
- [x] **Solved:** Normalizes datetime using `.astimezone(timezone.utc)` before stripping the timezone info.
- [x] **Bug 5 (Timezone offset parsing wrong):** Normalized offset datetimes to UTC.
- [x] **Bug 6 (`Z` datetime support missing risk):** Added support to convert trailing `Z` timezone indicator to `+00:00` before parsing.

---

## 2. app/auth.py

- **Location:** `get_token_payload` function.
- **Bug:** Checks if the user ID (`payload.get("sub")`) is inside `_revoked_tokens`, but the logout function stores the token ID (`payload["jti"]`) instead. This makes token revocation completely ineffective.
- [x] **Solved:** Checks token revocation by checking the `jti` claim against `_revoked_tokens` and provides clean helpers.
- [x] **Bug 1 (Access token expiry wrong):** Corrected access token expiration duration calculation from 900 minutes to 15 minutes (900 seconds).
- [x] **Bug 2 (Logout revocation broken):** Switched revocation checks to token `jti` to immediately reject logged-out access tokens.

---

## 3. app/routers/auth.py

- **Location:** `/auth/register` and `/auth/refresh` endpoints.
- **Bug A:** `/auth/register` returns existing user details with a `201` status code instead of triggering a `409 USERNAME_TAKEN` error when a username is duplicated within an organization.
  - [x] **Solved:** Added `AppError(409, "USERNAME_TAKEN", ...)` check for duplicate username registrations.
- **Bug B:** `/auth/refresh` decodes refresh tokens but fails to track or blacklist their `jti` identifiers, allowing single-use refresh tokens to be reused infinitely.
  - [x] **Solved:** Blacklists the refresh token's `jti` upon use to enforce single-use logic.
- **Bug C:** Concurrent `/auth/refresh` requests could both pass the `is_token_revoked()` check before either request revoked the same `jti`.
  - [x] **Solved:** Added atomic `revoke_token_once()` helper guarded by a lock; now only one concurrent refresh can consume a token.
- [x] **Bug 3 (Refresh token reusable):** Enforced single-use refresh tokens via used-list verification.
- [x] **Bug 4 (Duplicate username returned success):** Fixed conflict behavior by raising `USERNAME_TAKEN` on registration collision.

---

## 4. app/routers/bookings.py

- **Location:** Various booking logic operations.
- **Bug A (`_has_conflict`):** Uses inclusive inequalities (`<=` and `>=`), which blocks valid back-to-back room bookings.
  - [x] **Solved:** Replaced with strict inequalities (`<` and `<`).
- **Bug B (`create_booking`):** Implements an intentional 5-minute past window grace period (`now - timedelta(seconds=300)`), allowing users to make historical bookings.
  - [x] **Solved:** Prohibited historical bookings with `start <= now`.
- **Bug C (`create_booking`):** Lacks verification boundaries for minimum durations or configurations where `end_time <= start_time`.
  - [x] **Solved:** Added validations for `end_time <= start_time` and duration out of range `[MIN_DURATION_HOURS, MAX_DURATION_HOURS]`.
- **Bug D (`list_bookings`):** Sorts queries by `start_time.desc()` instead of ascending. Additionally, it uses an incorrect offset math formula (`page * limit` which skips page 1 entirely) and hardcodes a sizing ceiling of `.limit(10)`.
  - [x] **Solved:** Fixed sorting order (ascending), offset calculation `(page - 1) * limit`, and replaced the hardcoded limit with the dynamic query `limit`.
- **Bug E (`get_booking`):** Overwrites the actual booking `start_time` payload value with the booking's creation timestamp (`booking.created_at`) right before returning the response.
  - [x] **Solved:** Removed the overriding line so the actual `start_time` is returned.
- **Bug F (`cancel_booking`):** Notice window check uses `notice_hours > 48` (skipping exactly 48 hours) and returns a 50% refund for notice durations under 24 hours instead of a 0% refund.
  - [x] **Solved:** Corrected notice comparison to `notice_hours >= 48` and set refund percent to 0% for notice durations under 24 hours.
- **Bug G (`cancel_booking`):** Utilizes standard Python Banker's Rounding via `round()`, creating a data calculation mismatch against `log_refund` which completely truncates figures using `int()`.
  - [x] **Solved:** Used `int()` truncation for `refund_amount_cents` calculation to match the database entries created by `log_refund`.
- **Bug H (`create_booking` & `cancel_booking`):** Missing critical live cache invalidation handlers—`create_booking` does not clear stale admin reports and `cancel_booking` does not clear room availability busy slots.
  - [x] **Solved:** Integrated `cache.invalidate_report(user.org_id)` on creation and `cache.invalidate_availability(...)` on cancellation.
- [x] **Bug 7 (Invalid datetime format):** Caught datetimes parsing `ValueError` and returned a clean `400` status code.
- [x] **Bug 8 (Past start grace window):** Restricted start time to future-only (`start <= now`).
- [x] **Bug 9 (End before start):** Added explicit checks to reject `end_time <= start_time`.
- [x] **Bug 10 (Zero-hour booking):** Enforced duration bound check `[1, 8]` hours.
- [x] **Bug 11 (Back-to-back conflicts):** Fixed slot overlap checking to support back-to-back bookings.
- [x] **Bug 12 (Conflict check loaded all bookings):** Optimized query to check slot conflicts at DB level instead of filtering in Python.
- [x] **Bug 13 & 14 (Concurrent creation races):** Wrapped booking verification and insertion inside a global thread lock.
- [x] **Bug 15 (Artificial booking sleeps):** Removed sleeps from booking check, quota verification, and cancellation.
- [x] **Bug 19 (Booking list sort wrong):** Sorted by `start_time ASC, id ASC`.
- [x] **Bug 20 & 21 (Booking pagination offsets and limits):** Fixed pagination offsets to `(page - 1) * limit` and mapped requested limit limits.
- [x] **Bug 22 (Member viewing another member's details):** Enforced ownership controls on detail checks for regular members.
- [x] **Bug 23 (Booking detail start time overwrite):** Removed overwrite of `start_time` in serialized output.
- [x] **Bug 24 (Cancellation refund boundary):** Compared timedelta objects using `>= timedelta(hours=48)` to correctly handle edge boundaries.
- [x] **Bug 25 (Notice under 24 hours refund):** Set refund percent to 0% for cancellations under 24 hours notice.
- [x] **Bug 26 (Refund rounding math):** Mapped cent calculations using `Decimal` and `ROUND_HALF_UP` for precision half-up rounding.
- [x] **Bug 30 (Concurrent cancel race):** Prevented status races on cancellation using a cancellation lock.
- [x] **Bug 39 (Concurrent cancel stale ORM object):** Moved booking lookup inside the cancellation lock so later requests see the committed `cancelled` status and return `409 ALREADY_CANCELLED` instead of causing duplicate refund-log `500` errors.
- [x] **Bug 31 & 32 (Cache invalidations on creation/cancellation):** Synchronously cleared respective report and availability caches.

---

## 5. app/services/export.py

- **Location:** `generate_export` function.
- **Bug:** When `include_all` evaluates to true with a specified `room_id`, it executes an un-scoped data query across the database. This enables organization cross-read exposures that break multi-tenancy isolation policies.
- [x] **Solved:** Routed export queries to `_fetch_scoped(...)` to ensure multi-tenancy organization filtering is strictly applied.
- [x] **Bug 38 (CSV export cross-org leak):** Applied org filter restrictions to `include_all=True` queries.

---

## 6. app/services/notifications.py

- **Location:** `notify_created` and `notify_cancelled` functions.
- **Bug:** `notify_created` requests locks in the sequence of `_email_lock` $\rightarrow$ `_audit_lock`, while `notify_cancelled` requests them as `_audit_lock` $\rightarrow$ `_email_lock`. Executing these concurrently triggers thread deadlocks.
- [x] **Solved:** Standardized lock order to `_email_lock` then `_audit_lock` in both notification functions to prevent deadlocks.

---

## 7. Shared Memory Concurrency & State Management

- **Location:** `stats.py`, `ratelimit.py`, and `reference.py` in `app/services/`
- **Bug:** Global variables (`_stats`, `_buckets`, and `_counter`) are modified across worker threads amidst arbitrary `time.sleep` intervals without synchronization mutexes or lock locks, yielding race conditions that drop count updates, leak rate boundaries, or generate identical reference strings.
- [x] **Solved:** Wrapped modifications of `_stats`, `_buckets`, and `_counter` with corresponding thread locks (`_stats_lock`, `_rate_limit_lock`, `_counter_lock`) to guarantee race-free thread safety.
- [x] **Bug 16 & 17 (Reference counter races & restarts):** Replaced seq-counter with random, secure UUID-backed reference codes.
- [x] **Bug 18 (No DB uniqueness on reference codes):** Added unique constraint on booking database table.
- [x] **Bug 27 (Refund float math):** Updated `log_refund` and calculation sequences to use pre-calculated cent integers.
- [x] **Bug 28 (Refund log atomicity):** Removed commit/refresh triggers from sub-helpers to ensure cancellation and refunds are atomic in a single database transaction.
- [x] **Bug 29 (Refund log uniqueness):** Placed unique constraints on the `booking_id` field in the database.
- [x] **Bug 33 (Usage report cache invalidation on room creation):** Cleared organization reports cache inside `create_room` route.
- [x] **Bug 34 & 35 (Stale stats cache & race):** Deprecated stats cache updates and dynamically aggregate room booking statistics directly from the database query.
- [x] **Bug 36 & 37 (Rate limiter races and sleeps):** Locked limiter state changes and removed liveness blocking sleeps.
- [x] **Bug 39 (CSV export missing room ownership validation):** Added validation check in `/admin/export` to verify the requested room ID belongs to the administrator's organization, returning a 404 instead of a 200 with an empty file when cross-org resource IDs are accessed.

