# bug_report.md

## 1. app/timeutils.py

- **Location:** `parse_input_datetime` function.
- **Bug:** Uses `dt.replace(tzinfo=None)` directly, which discards the timezone offset instead of converting the time value to UTC first.
- [x] **Solved:** Normalizes datetime using `.astimezone(timezone.utc)` before stripping the timezone info.

## 2. app/auth.py

- **Location:** `get_token_payload` function.
- **Bug:** Checks if the user ID (`payload.get("sub")`) is inside `_revoked_tokens`, but the logout function stores the token ID (`payload["jti"]`) instead. This makes token revocation completely ineffective.
- [x] **Solved:** Checks token revocation by checking the `jti` claim against `_revoked_tokens` and provides clean helpers.

## 3. app/routers/auth.py

- **Location:** `/auth/register` and `/auth/refresh` endpoints.
- **Bug A:** `/auth/register` returns existing user details with a `201` status code instead of triggering a `409 USERNAME_TAKEN` error when a username is duplicated within an organization.
  - [x] **Solved:** Added `AppError(409, "USERNAME_TAKEN", ...)` check for duplicate username registrations.
- **Bug B:** `/auth/refresh` decodes refresh tokens but fails to track or blacklist their `jti` identifiers, allowing single-use refresh tokens to be reused infinitely.
  - [x] **Solved:** Blacklists the refresh token's `jti` upon use to enforce single-use logic.

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

## 5. app/services/export.py

- **Location:** `generate_export` function.
- **Bug:** When `include_all` evaluates to true with a specified `room_id`, it executes an un-scoped data query across the database. This enables organization cross-read exposures that break multi-tenancy isolation policies.
- [x] **Solved:** Routed export queries to `_fetch_scoped(...)` to ensure multi-tenancy organization filtering is strictly applied.

## 6. app/services/notifications.py

- **Location:** `notify_created` and `notify_cancelled` functions.
- **Bug:** `notify_created` requests locks in the sequence of `_email_lock` $\rightarrow$ `_audit_lock`, while `notify_cancelled` requests them as `_audit_lock` $\rightarrow$ `_email_lock`. Executing these concurrently triggers thread deadlocks.
- [x] **Solved:** Standardized lock order to `_email_lock` then `_audit_lock` in both notification functions to prevent deadlocks.

## 7. Shared Memory Concurrency Bugs (app/services/)

- **Location:** `stats.py`, `ratelimit.py`, and `reference.py`.
- **Bug:** Global variables (`_stats`, `_buckets`, and `_counter`) are modified across worker threads amidst arbitrary `time.sleep` intervals without synchronization mutexes or lock locks, yielding race conditions that drop count updates, leak rate boundaries, or generate identical reference strings.
- [x] **Solved:** Wrapped modifications of `_stats`, `_buckets`, and `_counter` with corresponding thread locks (`_stats_lock`, `_rate_limit_lock`, `_counter_lock`) to guarantee race-free thread safety.
