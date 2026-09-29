from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    ai_ticket_gemini_api_key = fields.Char(
        string="Gemini API Key",
        config_parameter="ai_ticket.gemini_api_key",
        groups="ai_ticket_booking.group_ai_ticket_manager",
    )
    ai_ticket_gemini_model = fields.Char(
        string="Gemini Model",
        default="gemini-2.5-flash-lite",
        config_parameter="ai_ticket.gemini_model",
        groups="ai_ticket_booking.group_ai_ticket_manager",
    )
    ai_ticket_gemini_timeout = fields.Integer(
        string="Gemini Timeout (seconds)",
        default=20,
        config_parameter="ai_ticket.gemini_timeout",
        groups="ai_ticket_booking.group_ai_ticket_manager",
    )
    ai_ticket_worker_base_url = fields.Char(
        string="Booking Worker Base URL",
        config_parameter="ai_ticket.worker_base_url",
        groups="ai_ticket_booking.group_ai_ticket_manager",
    )
    ai_ticket_worker_api_token = fields.Char(
        string="Booking Worker API Token",
        config_parameter="ai_ticket.worker_api_token",
        groups="ai_ticket_booking.group_ai_ticket_manager",
    )
    ai_ticket_worker_webhook_secret = fields.Char(
        string="Worker Webhook Secret",
        config_parameter="ai_ticket.worker_webhook_secret",
        groups="ai_ticket_booking.group_ai_ticket_manager",
    )
    ai_ticket_worker_timeout = fields.Integer(
        string="Worker API Timeout (seconds)",
        default=8,
        config_parameter="ai_ticket.worker_timeout",
        groups="ai_ticket_booking.group_ai_ticket_manager",
    )
    ai_ticket_log_retention_days = fields.Integer(
        string="Log Retention (days)",
        default=30,
        config_parameter="ai_ticket.log_retention_days",
        groups="ai_ticket_booking.group_ai_ticket_manager",
    )

    @api.constrains("ai_ticket_worker_api_token", "ai_ticket_worker_webhook_secret")
    def _check_worker_secrets(self):
        for rec in self:
            if rec.ai_ticket_worker_api_token and len(rec.ai_ticket_worker_api_token) < 32:
                raise ValidationError(_("Worker API token must be at least 32 characters."))
            if rec.ai_ticket_worker_webhook_secret and len(rec.ai_ticket_worker_webhook_secret) < 32:
                raise ValidationError(_("Worker webhook secret must be at least 32 characters."))

    def _require_ai_ticket_manager(self):
        if not self.env.user.has_group("ai_ticket_booking.group_ai_ticket_manager"):
            raise AccessError(_("AI Ticket Manager access is required."))

    def action_ai_ticket_test_gemini(self):
        self.ensure_one()
        self._require_ai_ticket_manager()
        self.env["ai.ticket.gemini.service"]._test_connection()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": _("Gemini"), "message": _("Gemini API connection succeeded."), "type": "success", "sticky": False},
        }

    def action_ai_ticket_test_worker(self):
        self.ensure_one()
        self._require_ai_ticket_manager()
        result = self.env["ai.ticket.worker.client"]._healthcheck()
        message = _("Worker connection succeeded: %s") % (result.get("status") or "OK")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": _("Booking Worker"), "message": message, "type": "success", "sticky": False},
        }
