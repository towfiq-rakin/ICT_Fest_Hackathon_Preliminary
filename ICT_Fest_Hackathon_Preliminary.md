**AAI presents IUT 12th ICT Fest** powered by Therap (BD) Ltd. organized by IUT Computer Society

## Bdapps presents

## **Agentic AI Hackathon**

powered by Codex

## **Preliminary Round Problem Statement**

CoWork: Multi-Tenant Coworking Space Booking API

## **Repository Link**

`https://github.com/AlchemistReturns/ICT_Fest_Hackathon_ Preliminary`

## **Duration**

4 hours, 6:00 PM to 10:00 PM

Document version: Preliminary Round July 9, 2026

Bdapps Agentic AI Hackathon

IUT 12th ICT Fest

## **1 Overview**

This is a bug fix challenge. Participants are given a broken codebase and must find the bugs, understand why they are broken, and fix them. There are bugs hidden across the project, ranging from easy one-liners to subtle concurrency and logic issues. Participants do not need to add features or refactor anything. Find the bugs. Fix them. That is the entire task.

**Grading is automatic and black-box.** A grader will build your submitted repository and talk to it only through the API. It will assert behavior against the business rules and API contract described in this document (Sections 3 and 4). **Your fixes must preserve this contract exactly** - paths, status codes, error codes, and JSON field names must not change.

## **2 The Project**

CoWork is a REST API for managing bookable rooms inside a coworking space, supporting multiple tenant organizations. Each organization has its own rooms, staff (admins), and members. Members book rooms for time slots; admins manage rooms and pull usage reports.

**Stack:** Python 3.11, FastAPI, SQLAlchemy, SQLite (single file, no external database service). Authentication is handled via JWT access and refresh tokens (HS256). **Out of scope:** There is no real payment gateway (refunds are calculated and logged, not processed), and there is no real email delivery (a “send confirmation email” step only logs a line).

## **File Structure**

| `app/`          |                                                    |
| --------------- | -------------------------------------------------- | ------------------------------------------------------------- |
| `               | -- main.py`                                        | `# FastAPI app entrypoint`                                    |
| `               | -- config.py`                                      | `# Environment/config loading`                                |
| `               | -- database.py`                                    | `# Database engine and session setup`                         |
| `               | -- models.py`                                      | `# SQLAlchemy database models`                                |
| `               | -- schemas.py`                                     | `# Pydantic request/response schemas`                         |
| `               | -- serializers.py`                                 | `# Model -> response object conversion`                       |
| `               | -- auth.py`                                        | `# JWT creation, password hashing, auth dependency`           |
| `               | -- cache.py`                                       | `# In-memory caching for reports/availability`                |
| `               | -- errors.py`                                      | `# Application error types and handler`                       |
| `               | -- timeutils.py`                                   | `# Datetime parsing/normalization helpers`                    |
| `               | -- routers/`                                       | `# API route handlers (auth, rooms, bookings, admin, health)` |
| `‘-- services/` | `# Business logic (refunds, stats, rate limiting,` |
|                 | `# reference codes, export, notifications)`        |

## **3 Data Model**

- **Organization** : `id` , `name` (unique)

- **User** : `id` , `org` ~~`i`~~ `d` , `username` (unique within org), `hashed` ~~`p`~~ `assword` , `role` ( `admin` _|_ `member` ), `created at`

- **Room** : `id` , `org` ~~`i`~~ `d` , `name` , `capacity` , `hourly` ~~`r`~~ `ate` ~~`c`~~ `ents`

- **Booking** : `id` , `room` ~~`i`~~ `d` , `user` ~~`i`~~ `d` , `start` ~~`t`~~ `ime` , `end` ~~`t`~~ `ime` , `status` ( `confirmed` _|_ `cancelled` ), `reference` ~~`c`~~ `ode` , `price` ~~`c`~~ `ents` , `created` ~~`a`~~ `t`

- **RefundLog** : `id` , `booking id` , `amount cents` , `status` ( `processed` _|_ `failed` ), `processed` ~~`a`~~ `t`

1

Bdapps Agentic AI Hackathon

IUT 12th ICT Fest

## **4 Business Rules**

These are the rules the API is expected to follow. Some bugs are deviations from these rules - use them as your source of truth when deciding whether behavior is correct.

1. **Datetimes.** All API datetimes are ISO 8601. Input datetimes carrying a UTC offset must be converted to UTC before storage or comparison; naive input is treated as UTC. All response datetimes are UTC with an explicit UTC designator.

2. **Booking price.** `price_cents = hourly_rate_cents` _×_ `duration_hours` . Duration must be a whole number of hours, minimum 1, maximum 8. `end_time` must be strictly after `start_time` . `start_time` must be strictly in the future at request time - no grace window.

3. **No double-booking.** Two confirmed bookings for the same room overlap iff `existing.start < new.end AND new.start < existing.end` . Back-to-back bookings are allowed. Conflict _→_ `409 ROOM_CONFLICT` . Must hold under concurrent requests.

4. **Booking quota.** A member may hold at most 3 confirmed bookings with `start_time` in the window ( _now, now_ + 24 _h_ ], across all rooms in their org. Violation _→_ `409 QUOTA EXCEEDED` . Must hold under concurrent requests.

5. **Rate limit.** `POST /bookings` is limited to 20 requests per rolling 60 seconds per user (all requests count). Excess _→_ `429 RATE LIMITED` . Must hold under concurrent requests.

6. **Cancellation refund policy.** Only the booking’s owner or an admin of the same org may cancel. Notice = `start time` _−_ cancellation time:
   - notice _≥_ 48 hours _→_ 100% refund

   - 24 hours _≤_ notice _<_ 48 hours _→_ 50% refund

   - notice _<_ 24 hours _→_ 0% refund

Refund amount rounds to the nearest cent, half-cents rounding up. Cancelling an alreadycancelled booking _→_ `409 ALREADY_CANCELLED` . A cancelled booking has exactly one RefundLog entry, and the amount returned by the cancel response must equal the amount stored in the RefundLog. Must hold under concurrent cancel requests for the same booking.

7. **Reference codes.** Every booking’s `reference_code` is unique, including under concurrent creation.

8. **Auth.** Tokens are JWTs (HS256) with claims `sub` (user id, string), `org` (org id), `role` , `jti` (unique per token), `iat` , `exp` , `type` ( `access` _|_ `refresh` ). Access tokens expire in exactly 900 seconds. Refresh tokens expire in 7 days. Logout immediately invalidates the presented access token (subsequent use _→_ `401` ). Refresh tokens are single-use: refreshing returns a new access and refresh token and invalidates the presented refresh token (reuse _→_ `401` ).

9. **Multi-tenancy.** A user (including admins) may only ever read or act on data belonging to their own organization, on every code path. Cross-org resource IDs behave as non-existent ( _→_ `404` ).

10. **Booking visibility.** Members may read and cancel only their own bookings (another member’s booking id _→_ `404 BOOKING NOT FOUND` ). Admins may read and cancel any booking in their org.

11. **Pagination & ordering.** `GET /bookings` takes `page` (default 1) and `limit` (default 10, max 100). Items are the caller’s own bookings sorted ascending by `start_time` (ties by ascending `id` ). Sequential pages never skip or repeat items. Response includes `total` .

2

Bdapps Agentic AI Hackathon

IUT 12th ICT Fest

12. **Usage report.** `GET /admin/usage-report?from=...&to=...` returns, per room in the caller’s org (including rooms with zero bookings), the count and summed `price` ~~`c`~~ `ents` of confirmed bookings starting in `[from, to]` (UTC, inclusive). Must reflect the current state immediately.

13. **Availability.** `GET /rooms/` _{_ `id` _}_ `/availability?date=...` returns the room’s confirmed bookings starting on that UTC date as busy intervals, sorted ascending, reflecting the current state immediately.

14. **Room stats.** `GET /rooms/` _{_ `id` _}_ `/stats` returns the room’s current count of confirmed bookings and their summed `price cents` , always consistent with the bookings themselves, including after bursts of concurrent activity.

15. **Registration.** `POST /auth/register` with an unknown `org` ~~`n`~~ `ame` creates the org and the user as `admin` ; with a known `org name` it joins the caller as `member` . A duplicate username within the org _→_ `409 USERNAME TAKEN` .

16. **Liveness.** The service must respond to all endpoints at all times; no combination of concurrent valid requests may hang the service.

## **5 API Contract**

## **Endpoints**

| **Method ** | **Path**                              | **Auth** | **Auth** | **Description**                          |       |
| ----------- | ------------------------------------- | -------- | -------- | ---------------------------------------- | ----- |
| POST        | `/auth/register`                      | No       |          | Register org admin or join org as member |       |
| POST        | `/auth/login`                         | No       |          | Returns access + refresh token           |       |
| POST        | `/auth/refresh`                       | No       | (to-     | Rotates tokens                           |       |
|             |                                       | ken      | in       |                                          |       |
|             |                                       | body)    |          |                                          |       |
| POST        | `/auth/logout`                        | Yes      |          | Invalidates presented access token       |       |
| GET         | `/rooms`                              | Yes      |          | List rooms in caller’s org               |       |
| POST        | `/rooms`                              | Yes      | (ad-     | Create a room                            |       |
|             |                                       | min)     |          |                                          |       |
| GET         | `/rooms/`_{_`id`_}_`/availability`Yes |          |          | Busy intervals for a date                |       |
| GET         | `/rooms/`_{_`id`_}_`/stats`           | Yes      |          | Live confrmed-booking count & revenue    |       |
| POST        | `/bookings`                           | Yes      |          | Create a booking                         |       |
| GET         | `/bookings`                           | Yes      |          | Caller’s bookings, paginated             |       |
| GET         | `/bookings/`_{_`id`_}_                | Yes      |          | Single booking incl. refunds             |       |
| POST        | `/bookings/`_{_`id`_}_`/cancel`       | Yes      |          | Cancel + refund calculation              |       |
| GET         | `/admin/usage-report`                 | Yes      | (ad-     | Per-room usage/revenue for range         |       |
|             |                                       | min)     |          |                                          |       |
| GET         | `/admin/export`                       | Yes      | (ad-     | Bookings CSV; `room`<br>`id`, `include`  | `all` |
|             |                                       | min)     |          |                                          |       |
| GET         | `/health`                             | No       |          | _{_`"status":`<br>`"ok"`_}_              |       |

For all authenticated endpoints, pass the token in the Authorization header:

```
Authorization:Bearer<your_token>
```

3

Bdapps Agentic AI Hackathon

IUT 12th ICT Fest

## **Request / Response Schemas**

- `POST /auth/register` body _{_ `org` ~~`n`~~ `ame, username, password` _} →{_ `user` ~~`i`~~ `d, org` ~~`i`~~ `d, username, role` _}_

- `POST /auth/login` body _{_ `org` ~~`n`~~ `ame, username, password` _} →{_ `access` ~~`t`~~ `oken, refresh token, token` ~~`t`~~ `ype: "bearer"` _}_ ; bad credentials _→_ `401 INVALID CREDENTIALS`

- `POST /auth/refresh` body _{_ `refresh token` _} →_ same shape as login

- Room: _{_ `id, org id, name, capacity, hourly rate` ~~`c`~~ `ents` _}_ ; `POST /rooms` body _{_ `name, capacity, hourly rate` ~~`c`~~ `ents` _}_

- Availability: _{_ `room` ~~`i`~~ `d, date, busy:`
  - `[` _{_ `start` ~~`t`~~ `ime, end time` _}_ `, ...]` _}_

- Stats: _{_ `room id, total` ~~`c`~~ `onfirmed` ~~`b`~~ `ookings, total` ~~`r`~~ `evenue` ~~`c`~~ `ents` _}_

- `POST /bookings` body _{_ `room` ~~`i`~~ `d, start time, end` ~~`t`~~ `ime` _} →_ Booking: _{_ `id, reference` ~~`c`~~ `ode, room` ~~`i`~~ `d, user` ~~`i`~~ `d, start` ~~`t`~~ `ime, end` ~~`t`~~ `ime, status, price` ~~`c`~~ `ents, created at` _}_

- `GET /bookings` _→{_ `items: [Booking, ...], page, limit, total` _}_

- `GET /bookings/` _{_ `id` _} →_ Booking plus `refunds: [` _{_ `amount` ~~`c`~~ `ents, status, processed at` _}_ `, ...]`

- `POST /bookings/` _{_ `id` _}_ `/cancel` _→{_ `id, status: "cancelled", refund percent, refund amount` ~~`c`~~ `ents` _}_

- Usage report _→{_ `from, to, rooms: [` _{_ `room` ~~`i`~~ `d, room name, confirmed` ~~`b`~~ `ookings, revenue cents` _}_ `, ...]` _}_

- Export CSV header (exact): `id,reference` ~~`c`~~ `ode,room id,user id, start` ~~`t`~~ `ime, end time,status,price` ~~`c`~~ `ents`

## **Errors**

Application errors return JSON _{_ `"detail": <string>, "code": <CODE>` _}_ with codes: `USERNAME` ~~`T`~~ `AKEN` (409), `INVALID CREDENTIALS` (401), `ROOM CONFLICT` (409), `QUOTA EXCEEDED` (409), `RATE` ~~`L`~~ `IMITED` (429), `ALREADY` ~~`C`~~ `ANCELLED` (409), `BOOKING` ~~`N`~~ `OT` ~~`F`~~ `OUND` (404), `ROOM` ~~`N`~~ `OT` ~~`F`~~ `OUND` (404), `FORBIDDEN` (403), `INVALID BOOKING WINDOW` (400 — past start, non-whole/out-of-range duration, or `end time` _≤_ `start time` ). Missing/invalid/expired/blacklisted tokens _→_ 401. Framework validation errors (422) may use FastAPI’s default shape.

## **Fixes must preserve this contract exactly; grading is black-box against it.**

4

Bdapps Agentic AI Hackathon

IUT 12th ICT Fest

## **6 Running the Project**

## **With Docker (recommended)**

```
dockercomposeup--build
```

## **Without Docker (Python 3.11)**

```
python-mvenv.venv
#Windows
.venv\Scripts\activate
#macOS/Linux
source.venv/bin/activate
```

```
pipinstall-rrequirements.txt
uvicornapp.main:app--reload
```

App runs at `http://localhost:8000` . Interactive API docs at `http://localhost:8000/docs` .

## **7 How to Test**

Use the Swagger UI at `/docs` , curl, or clients like Postman.

## **curl Example**

```
#Register
```

```
curl-XPOSThttp://localhost:8000/auth/register\
```

- `-H "Content-Type: application/json" \`

- `-d ’{"org_name": "acme", "username": "alice", "password": "pass123"}’`

```
#Login
```

```
curl-XPOSThttp://localhost:8000/auth/login\
```

- `-H "Content-Type: application/json" \`

- `-d ’{"org_name": "acme", "username": "alice", "password": "pass123"}’`

```
#Usethetoken
```

```
curlhttp://localhost:8000/rooms\
```

- `-H "Authorization: Bearer <TOKEN>"`

## **8 The Challenge**

There are multiple bugs in the codebase, distributed across the difficulty tiers below. Each bug causes clearly observable, wrong behavior when interacting with the API.

## **What counts as a valid fix:**

- The fixed code produces the correct behavior described in Sections 3–4

- Only the broken code should be changed - do not refactor or rewrite unrelated code

- The API contract (paths, status codes, error codes, JSON field names) must remain exactly as specified

5

Bdapps Agentic AI Hackathon

IUT 12th ICT Fest

## **9 Submission**

1. Fork the preliminary-round repository to your own GitHub account: `https://github.com/ AlchemistReturns/ICT_Fest_Hackathon_Preliminary`

2. **Leave the fork’s network** so your copy is no longer linked to the original repository (GitHub _→_ your repo’s _Settings →_ scroll to _Danger Zone → Leave fork network_ ). Do this before you start editing.

3. Fix the bugs in your repository.

4. Your repository may be kept **private** during the competition, if you prefer.

5. You must make it **public** within 1 hour of the competition ending - repositories that remain private after this window will not be evaluated.

6. Submit your repository URL via the provided Google Form link.

## **10 Scoring & Tie-Breaking**

Points are awarded per bug based on difficulty:

| **Difculty** | **Points ** | **each** |
| ------------ | ----------- | -------- |
| Easy         | 3           |          |
| Medium       | 5           |          |
| Hard         | 10          |          |

## **Tie-Breaking**

Ties are resolved in the following order:

1. **Difficulty of bugs solved** - the participant who fixed harder bugs ranks higher.

2. `bug report.md` (optional) - if a tie remains after step 1, participants who submitted a `bug report.md` in the root of their repository go through manual evaluation.

`bug report.md` should include, for each bug found:

- Which file(s)/line(s) the bug is on

- What the bug was and why it caused incorrect behavior

- How it was fixed

Manual evaluation of `bug` ~~`r`~~ `eport.md` is the final tie-breaking mechanism.

_Good luck._

6
