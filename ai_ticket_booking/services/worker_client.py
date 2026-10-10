import logging
from urllib.parse import urljoin, urlparse

import requests

from odoo import models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AiTicketWorkerClient(models.AbstractModel):
    _name = "ai.ticket.worker.client"
    _description = "External Booking Worker Client"

    def _config(self):
        params = self.env["ir.config_parameter"].sudo()
        base_url = (params.get_param("ai_ticket.worker_base_url") or "").strip().rstrip("/") + "/"
        token = params.get_param("ai_ticket.worker_api_token") or ""
        try:
            timeout = min(30, max(2, int(params.get_param("ai_ticket.worker_timeout", "8"))))
        except ValueError:
            timeout = 8
        if not base_url or base_url == "/":
            raise UserError(_("Booking worker base URL is not configured."))
        parsed = urlparse(base_url)
        if parsed.username or parsed.password:
            raise UserError(_("Do not embed credentials in the booking worker URL."))
        if parsed.scheme != "https" and parsed.hostname not in ("127.0.0.1", "localhost"):
            raise UserError(_("Booking worker URL must use HTTPS outside localhost."))
        if not token:
            raise UserError(_("Booking worker API token is not configured."))
        return base_url, token, timeout

    def _request(self, method, path, *, json_data=None, idempotency_key=None):
        base_url, token, timeout = self._config()
        url = urljoin(base_url, path.lstrip("/"))
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Odoo-AI-Ticket/19.0",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            response = requests.request(method, url, json=json_data, headers=headers, timeout=(3, timeout))
        except requests.RequestException as exc:
            _logger.warning("Booking worker request failed %s %s: %s", method, url, exc)
            raise UserError(_("Booking worker is unreachable.")) from exc
        if response.status_code >= 400:
            _logger.warning("Booking worker HTTP %s for %s: %s", response.status_code, path, response.text[:1000])
            raise UserError(_("Booking worker rejected the request (HTTP %s).") % response.status_code)
        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise UserError(_("Booking worker returned invalid JSON.")) from exc

    def _healthcheck(self):
        return self._request("GET", "/v1/health")

    def _dispatch_booking(self, execution, payload):
        return self._request(
            "POST",
            "/v1/bookings",
            json_data=payload,
            idempotency_key=execution.idempotency_key,
        )


    def _resolve_product(self, request):
        return self._request(
            "POST",
            "/v1/catalog/resolve",
            json_data=request,
        )

    def _start_booking(self, execution):
        if not execution.worker_job_id:
            raise UserError(_("Worker job ID is missing."))
        return self._request(
            "POST",
            f"/v1/bookings/{execution.worker_job_id}/start",
            json_data={"execution_uuid": execution.execution_uuid},
            idempotency_key=f"start:{execution.execution_uuid}",
        )

    def _cancel_booking(self, execution):
        if not execution.worker_job_id:
            return {}
        return self._request(
            "POST",
            f"/v1/bookings/{execution.worker_job_id}/cancel",
            json_data={"execution_uuid": execution.execution_uuid},
            idempotency_key=f"cancel:{execution.execution_uuid}",
        )

    def _get_takeover_url(self, action):
        if not action.external_reference:
            raise UserError(_("The worker did not provide a human-action reference."))
        data = self._request(
            "POST",
            f"/v1/human-actions/{action.external_reference}/takeover",
            json_data={"action_uuid": action.action_uuid},
            idempotency_key=f"takeover:{action.action_uuid}",
        )
        url = data.get("url")
        if not url or urlparse(url).scheme != "https":
            raise UserError(_("Worker did not return a secure takeover URL."))
        return url

    def _resume_human_action(self, action):
        if not action.external_reference:
            raise UserError(_("The worker did not provide a human-action reference."))
        return self._request(
            "POST",
            f"/v1/human-actions/{action.external_reference}/resume",
            json_data={"action_uuid": action.action_uuid},
            idempotency_key=f"resume:{action.action_uuid}",
        )
