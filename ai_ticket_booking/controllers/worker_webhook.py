import hashlib
import hmac
import json
import logging
import time

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class AiTicketWorkerWebhook(http.Controller):

    @http.route(
        "/ai_ticket/v1/worker/events",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def worker_event(self, **_kwargs):
        raw = request.httprequest.get_data(cache=False) or b""
        if len(raw) > 262144:
            return request.make_json_response({"error": "payload_too_large"}, status=413)
        headers = request.httprequest.headers
        event_id = (headers.get("X-AI-Ticket-Event-Id") or "").strip()
        timestamp = (headers.get("X-AI-Ticket-Timestamp") or "").strip()
        signature = (headers.get("X-AI-Ticket-Signature") or "").strip()
        secret = request.env["ir.config_parameter"].sudo().get_param("ai_ticket.worker_webhook_secret") or ""

        if not secret or not event_id or not timestamp or not signature:
            return request.make_json_response({"error": "unauthorized"}, status=401)
        if len(event_id) > 128 or len(timestamp) > 20 or len(signature) > 128:
            return request.make_json_response({"error": "invalid_headers"}, status=400)
        try:
            ts = int(timestamp)
        except ValueError:
            return request.make_json_response({"error": "invalid_timestamp"}, status=401)
        if abs(int(time.time()) - ts) > 300:
            return request.make_json_response({"error": "expired_signature"}, status=401)

        signed = timestamp.encode() + b"." + event_id.encode() + b"." + raw
        expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        supplied = signature.removeprefix("sha256=")
        if not hmac.compare_digest(expected, supplied):
            return request.make_json_response({"error": "invalid_signature"}, status=401)

        Event = request.env["ai.ticket.webhook.event"].sudo()
        existing_event = Event.search([("event_id", "=", event_id)], limit=1)
        if existing_event and existing_event.status == "processed":
            return request.make_json_response({"status": "duplicate"}, status=200)

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return request.make_json_response({"error": "invalid_json"}, status=400)
        request_uuid = payload.get("request_uuid")
        if not request_uuid:
            return request.make_json_response({"error": "missing_request_uuid"}, status=400)
        if not isinstance(request_uuid, str) or len(request_uuid) > 128:
            return request.make_json_response({"error": "invalid_request_uuid"}, status=400)
        booking = request.env["ai.ticket.request"].sudo().search([("public_uuid", "=", request_uuid)], limit=1)
        if not booking:
            return request.make_json_response({"error": "request_not_found"}, status=404)

        event = existing_event or Event.create({"event_id": event_id, "request_id": booking.id, "event_type": payload.get("type") or "unknown"})
        if existing_event and existing_event.request_id != booking:
            return request.make_json_response({"error": "event_request_mismatch"}, status=409)
        try:
            booking._apply_worker_event(payload)
            event.write({"status": "processed"})
        except Exception as exc:  # webhook boundary: log server-side, do not leak internals
            _logger.exception("Failed processing AI ticket worker event %s", event_id)
            event.write({"status": "failed", "error_message": str(exc)[:1000]})
            return request.make_json_response({"error": "event_processing_failed"}, status=422)
        return request.make_json_response({"status": "processed"}, status=200)
