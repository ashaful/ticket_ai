import hashlib
import hmac
import json
import time

from odoo import http
from odoo.http import request


class AiTicketWorkerWebhookController(http.Controller):
    """Authenticated callback endpoint used by the external booking worker."""

    _MAX_CLOCK_SKEW_SECONDS = 300

    @staticmethod
    def _json_response(payload, status=200):
        return request.make_json_response(payload, status=status)

    @http.route(
        "/ai_ticket/v1/worker/events",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def worker_events(self, **kwargs):
        raw_body = request.httprequest.get_data(cache=True) or b""
        headers = request.httprequest.headers

        event_id = (headers.get("X-AI-Ticket-Event-Id") or "").strip()
        timestamp_raw = (headers.get("X-AI-Ticket-Timestamp") or "").strip()
        signature = (headers.get("X-AI-Ticket-Signature") or "").strip()

        if not event_id or not timestamp_raw or not signature:
            return self._json_response({"ok": False, "error": "missing_signature_headers"}, status=401)

        try:
            timestamp = int(timestamp_raw)
        except (TypeError, ValueError):
            return self._json_response({"ok": False, "error": "invalid_timestamp"}, status=401)

        if abs(int(time.time()) - timestamp) > self._MAX_CLOCK_SKEW_SECONDS:
            return self._json_response({"ok": False, "error": "stale_timestamp"}, status=401)

        params = request.env["ir.config_parameter"].sudo()
        secret = params.get_param("ai_ticket.worker_webhook_secret") or ""
        if not secret:
            return self._json_response({"ok": False, "error": "webhook_secret_not_configured"}, status=503)

        signed = timestamp_raw.encode("utf-8") + b"." + event_id.encode("utf-8") + b"." + raw_body
        expected = "sha256=" + hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return self._json_response({"ok": False, "error": "invalid_signature"}, status=401)

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._json_response({"ok": False, "error": "invalid_json"}, status=400)

        if not isinstance(payload, dict):
            return self._json_response({"ok": False, "error": "invalid_payload"}, status=400)

        request_uuid = payload.get("request_uuid")
        event_type = payload.get("type")
        if not request_uuid or not event_type:
            return self._json_response({"ok": False, "error": "missing_event_fields"}, status=400)

        webhook_model = request.env["ai.ticket.webhook.event"].sudo()
        if webhook_model.search_count([("event_id", "=", event_id)]):
            return self._json_response({"ok": False, "error": "duplicate_event"}, status=409)

        booking = request.env["ai.ticket.request"].sudo().search(
            [("public_uuid", "=", request_uuid)], limit=1
        )
        if not booking:
            return self._json_response({"ok": False, "error": "request_not_found"}, status=404)

        event = webhook_model.create({
            "event_id": event_id,
            "request_id": booking.id,
            "event_type": str(event_type)[:128],
            "status": "received",
        })

        try:
            # Roll back partial state changes if an event is invalid, while keeping
            # the webhook audit row itself available for diagnosis.
            with request.env.cr.savepoint():
                booking._apply_worker_event(payload)
            event.write({"status": "processed"})
        except Exception as exc:
            # Keep a persistent audit row while avoiding sensitive payload storage.
            event.write({
                "status": "failed",
                "error_message": str(exc)[:2000],
            })
            return self._json_response({"ok": False, "error": "event_processing_failed"}, status=400)

        return self._json_response({"ok": True, "event_id": event_id}, status=200)
