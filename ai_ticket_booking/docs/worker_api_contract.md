# External Booking Worker Contract (MVP)

The Odoo.sh module intentionally does **not** run Playwright/Chromium or exact-second scheduling. The external worker owns those responsibilities.

## Odoo -> worker

All requests use HTTPS and `Authorization: Bearer <token>`.

### `GET /v1/health`
Returns JSON such as `{ "status": "ok" }`.

### `POST /v1/bookings`
Header: `Idempotency-Key: booking:<request_uuid>:rules:<rules_version>`.
Body contains schema version, provider key, visit date, release strategy/time, ticket quantities, deterministic time priority, max price, human intervention flags, and optional traveler data.

Returns `{ "job_id": "..." }`.

### `POST /v1/bookings/{job_id}/cancel`
Cancels an active worker execution. Must itself be idempotent.

### `POST /v1/human-actions/{reference}/takeover`
Returns a short-lived HTTPS URL for the operator to control the **same active browser session**.

### `POST /v1/human-actions/{reference}/resume`
Resumes automation after the operator completes CAPTCHA/OTP/consent/payment as applicable.

## worker -> Odoo webhook

`POST /ai_ticket/v1/worker/events`

Required headers:

- `X-AI-Ticket-Event-Id`: globally unique event ID
- `X-AI-Ticket-Timestamp`: Unix epoch seconds
- `X-AI-Ticket-Signature`: `sha256=<hex HMAC>`

Signature input is exactly:

`<timestamp>.<event_id>.<raw_request_body>`

HMAC algorithm: SHA-256 using the configured webhook secret. Odoo rejects timestamps outside a 5-minute window and persists event IDs to reject replay/duplicate delivery.

Supported event types:

- `booking.state`
- `human_action.required`
- `human_action.resolved`
- `release.update`
- `execution.log`

Every event must include `request_uuid`; execution-specific events should also include `execution_uuid`.

The worker must never send browser cookies, provider session tokens, card data, API tokens, or CAPTCHA answers in webhook payloads/logs.
