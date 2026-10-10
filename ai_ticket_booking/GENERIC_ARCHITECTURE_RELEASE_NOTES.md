# AI Ticket Booking 19.0.2.0.0 — Generic prompt-to-product architecture

## Implemented

- Gemini extracts `product_intent`, visitor type and language without inventing canonical provider product titles.
- Product intent is resolved read-only against the worker's live provider catalog before validation.
- Resolution is fail-closed: `resolved`, `ambiguous`, or `not_found`; there is no standard-ticket fallback.
- Odoo stores and displays the resolved exact provider product and match confidence before dispatch.
- Validation refuses unresolved/ambiguous products and duplicate traveler profiles.
- Worker payload carries both `product.intent_text` and the resolved `product.exact_name`.
- Queue Booking can auto-start the worker immediately (`Auto-start Worker on Dispatch`), removing the manual VPS `/start` step.
- Human-action notifications support Email, Telegram, and WhatsApp Cloud API with a direct same-session Take Control URL.
- CAPTCHA, OTP, consent and payment remain manual; notification settings live in Odoo Settings, never in the prompt.

## Upgrade note

Existing old requests with an `Exact Product` value are not treated as resolved automatically. Re-parse/resolve them or create a fresh request so the exact product is confirmed against the current live catalog.
