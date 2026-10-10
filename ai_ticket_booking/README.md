# AI Ticket Booking 19.0.2.0.0 — Generic Ticket Sniper control plane

This version implements strict prompt-to-live-product resolution, operator confirmation, auto-start on dispatch, and CAPTCHA/OTP/payment notifications with direct Take Control links. It is designed to pair with AI Ticket Worker v1.1.0.

There is **no silent product fallback**. Ambiguous or missing product matches stay in Needs Information.

See `GENERIC_ARCHITECTURE_RELEASE_NOTES.md`.

# AI Ticket Booking for Odoo 19 / Odoo.sh

Production-oriented Odoo control-plane module for an AI-assisted ticket booking system.

## What runs on Odoo.sh

- Natural-language prompt capture
- Gemini structured parsing
- Deterministic booking rules
- Providers, travelers, release information
- Booking state machine
- Human Action / Payment queue
- Worker dispatch and status integration
- HMAC-signed worker webhook with replay protection
- Execution audit logs and retention
- Odoo 19 native `res.groups.privilege`, multi-company and role-based security

## What intentionally does NOT run on Odoo.sh

- Playwright/Chromium
- Exact-second release scheduling
- Browser-session persistence
- CAPTCHA solving
- Provider bot-protection bypass

Those belong on the external booking worker. This follows Odoo.sh's best-effort scheduled-action model and avoids depending on long-running browser processes inside managed Odoo containers.

## Roles

- **Ticket User**: own requests/travelers; read own execution/action/log data.
- **Ticket Operator**: operational access across the current company; dispatch, cancel, takeover and resume.
- **Ticket Manager**: provider/settings/secrets management and full model access.

## Setup

1. Install the module on Odoo 19.
2. The built-in Administrator is assigned Ticket Manager on install. Give other users the appropriate AI Ticket Booking role from Settings → Users.
3. Configuration -> Ticket Providers: create `Vatican Museums` (or another supported provider) with the exact worker provider key.
4. Configuration -> Settings: set Gemini API key/model and external worker URL/token/webhook secret.
5. Test Gemini and worker connectivity.
6. Create a Booking Request and use **Parse with Gemini**.
7. Review all AI-derived fields. AI output never arms a booking by itself.
8. Validate rules, then an Operator dispatches them to the worker.

## Security notes

- Gemini receives the booking prompt, not saved traveler records. Do not type passport/payment secrets into the prompt. Traveler PII is attached only when building the deterministic worker payload.
- Identity-document fields are Manager-only and should be left empty unless a provider requires them. Odoo fields are not application-level encrypted by this module.
- Secrets are stored as Odoo system configuration parameters; restrict Settings/System Parameters to trusted administrators and use separate staging/production credentials.
- The worker webhook uses HMAC SHA-256, a 5-minute timestamp window and persistent event IDs for replay protection.
- The worker API must use HTTPS in production. Localhost HTTP is allowed for development only.
- Payment card data must never be stored in Odoo logs or worker webhook payloads.

## Gemini behavior

The module uses Gemini REST `generateContent` with a strict response schema. The model is configurable; the default is `gemini-2.5-flash-lite`. AI is used only before execution. The time-critical worker receives fully structured rules and does not need an LLM.

## Odoo.sh

No third-party Python package is required by this module beyond libraries already present in Odoo's runtime (`requests`). This avoids dependency conflicts on Odoo.sh.

The included cleanup cron is intentionally low-frequency and idempotent. It is not used for ticket release timing.

## Production checklist

- Use separate Odoo.sh staging and production branches.
- Use a strong random worker bearer token and independent HMAC webhook secret.
- Rotate secrets periodically.
- Confirm provider automation is permitted before enabling a connector.
- Configure worker-side rate limits and stop on CAPTCHA/OTP/payment.
- Test worker crash, duplicate webhook, duplicate dispatch, session expiry, sold-out and provider HTML changes before production use.
- Monitor Human Action Queue continuously during high-demand releases.


## 19.0.1.0.4 Gemini schema compatibility

The Gemini REST integration uses `generationConfig.responseJsonSchema` for JSON Schema structured output. This is required for nullable union types such as `{"type": ["string", "null"]}`; the legacy `responseSchema` field expects the older OpenAPI-style schema representation. Gemini API errors are also surfaced with a bounded provider message to make configuration failures diagnosable.

## 19.0.1.0.9 — RC18 request fields

Adds exact product, guided visit language, and visitor type to Booking Requests and schema-v2 worker payloads. Gemini may extract these only when explicit in the prompt. Guided products require a visit language before validation. Human Action timestamp normalization from 19.0.1.0.8 is retained.
