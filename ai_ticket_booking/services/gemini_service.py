import json
import logging

import requests

from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AiTicketGeminiService(models.AbstractModel):
    _name = "ai.ticket.gemini.service"
    _description = "Gemini Ticket Prompt Parser"

    API_BASE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def _config(self):
        params = self.env["ir.config_parameter"].sudo()
        api_key = params.get_param("ai_ticket.gemini_api_key")
        model = params.get_param("ai_ticket.gemini_model", "gemini-2.5-flash-lite")
        try:
            timeout = min(60, max(3, int(params.get_param("ai_ticket.gemini_timeout", "20"))))
        except ValueError:
            timeout = 20
        if not api_key:
            raise UserError(_("Gemini API key is not configured in AI Ticket Booking settings."))
        return api_key, model, timeout

    def _response_schema(self):
        nullable_string = {"type": ["string", "null"]}
        nullable_number = {"type": ["number", "null"]}
        return {
            "type": "object",
            "properties": {
                "provider_hint": nullable_string,
                "visit_date": nullable_string,
                "ticket_lines": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "category": {"type": "string", "enum": ["adult", "child", "student", "senior", "other"]},
                            "label": nullable_string,
                            "quantity": {"type": "integer", "minimum": 1, "maximum": 20},
                        },
                        "required": ["category", "quantity"],
                    },
                },
                "preferred_time": nullable_string,
                "fallback_times": {"type": "array", "items": {"type": "string"}},
                "earliest_time": nullable_string,
                "latest_time": nullable_string,
                "max_total_price": nullable_number,
                "currency": nullable_string,
                "release_mode": {"type": "string", "enum": ["fixed", "announced", "watch", "unknown"]},
                "stop_on_captcha": {"type": "boolean"},
                "stop_on_otp": {"type": "boolean"},
                "stop_on_payment": {"type": "boolean"},
                "allow_early_availability": {"type": "boolean"},
                "missing_fields": {"type": "array", "items": {"type": "string"}},
                "notes": nullable_string,
            },
            "required": [
                "ticket_lines", "fallback_times", "release_mode", "stop_on_captcha", "stop_on_otp",
                "stop_on_payment", "allow_early_availability", "missing_fields"
            ],
        }

    def _system_prompt(self):
        return (
            "You are a strict parser for a ticket-booking orchestration system. "
            "Extract only facts or explicit preferences from the user's prompt. Never invent traveler data, prices, dates, "
            "ticket categories, provider rules, release times, or availability. Use ISO date YYYY-MM-DD and 24-hour HH:MM. "
            "You may normalize an explicit relative date using the supplied current date; if a date is still ambiguous, do not guess. "
            "If information is missing or ambiguous, put a short machine-readable key in missing_fields. "
            "Do not claim a booking exists. CAPTCHA, OTP, identity verification and payment must remain manual when requested. "
            "Return only data matching the provided schema."
        )

    def _parse_prompt(self, prompt, provider_names=None):
        if not prompt or not prompt.strip():
            raise UserError(_("Enter a booking prompt before using AI parsing."))
        clean_prompt = prompt.strip()
        if len(clean_prompt) > 12000:
            raise UserError(_("Booking prompt is too long. Keep it under 12,000 characters."))
        api_key, model, timeout = self._config()
        provider_context = ", ".join((provider_names or [])[:50]) or "No provider list supplied"
        today = fields.Date.to_string(fields.Date.context_today(self))
        user_text = f"Current date: {today}\nKnown configured providers: {provider_context}\n\nUser booking request:\n{clean_prompt}"
        payload = {
            "systemInstruction": {"parts": [{"text": self._system_prompt()}]},
            "contents": [{"role": "user", "parts": [{"text": user_text}]}],
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json",
                "responseJsonSchema": self._response_schema(),
            },
        }
        url = self.API_BASE.format(model=model)
        try:
            response = requests.post(
                url,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json=payload,
                timeout=(4, timeout),
            )
        except requests.RequestException as exc:
            _logger.warning("Gemini API request failed: %s", exc)
            raise UserError(_("Gemini API is temporarily unreachable.")) from exc
        if response.status_code >= 400:
            _logger.warning("Gemini API error HTTP %s: %s", response.status_code, response.text[:2000])
            if response.status_code == 429:
                raise UserError(_("Gemini free-tier rate limit was reached. Try again later."))
            detail = ""
            try:
                error_body = response.json()
                detail = (error_body.get("error") or {}).get("message") or ""
            except (ValueError, TypeError, AttributeError):
                detail = ""
            if detail:
                # Keep the UI useful without dumping an unbounded provider response.
                detail = " ".join(detail.split())[:700]
                raise UserError(_("Gemini API error (HTTP %(code)s): %(detail)s", code=response.status_code, detail=detail))
            raise UserError(_("Gemini API returned HTTP %s.") % response.status_code)
        try:
            body = response.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            _logger.exception("Unexpected Gemini response format")
            raise UserError(_("Gemini returned an invalid structured response.")) from exc
        return parsed, model

    def _test_connection(self):
        parsed, _model = self._parse_prompt(
            "One adult ticket for 2030-01-01 at 10:00. Stop before payment.",
            provider_names=[],
        )
        if not isinstance(parsed, dict):
            raise UserError(_("Gemini connection test returned an unexpected result."))
        return True
