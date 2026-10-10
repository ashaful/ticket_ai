from datetime import timedelta

from odoo import api, fields, models


class AiTicketLog(models.Model):
    _name = "ai.ticket.log"
    _description = "Ticket Execution Log"
    _order = "create_date desc, id desc"
    _rec_name = "event_code"

    request_id = fields.Many2one("ai.ticket.request", required=True, index=True, ondelete="cascade")
    execution_id = fields.Many2one("ai.ticket.execution", index=True, ondelete="set null")
    company_id = fields.Many2one(related="request_id.company_id", store=True, index=True)
    level = fields.Selection(
        [("debug", "Debug"), ("info", "Info"), ("warning", "Warning"), ("error", "Error")],
        required=True,
        default="info",
        index=True,
    )
    event_code = fields.Char(required=True, index="btree")
    message = fields.Text(required=True)
    duration_ms = fields.Integer()
    payload_json = fields.Json(copy=False)

    _request_created_idx = models.Index("(request_id, create_date)")

    @api.model
    def _cron_gc_logs(self):
        params = self.env["ir.config_parameter"].sudo()
        try:
            retention_days = max(1, int(params.get_param("ai_ticket.log_retention_days", "30")))
        except ValueError:
            retention_days = 30
        cutoff = fields.Datetime.now() - timedelta(days=retention_days)
        old_logs = self.sudo().search([("create_date", "<", cutoff)], limit=2000, order="id")
        if old_logs:
            old_logs.unlink()
        return True


class AiTicketWebhookEvent(models.Model):
    _name = "ai.ticket.webhook.event"
    _description = "Ticket Worker Webhook Event"
    _order = "create_date desc, id desc"

    event_id = fields.Char(required=True, index="btree", readonly=True)
    request_id = fields.Many2one("ai.ticket.request", required=True, index=True, ondelete="cascade", readonly=True)
    company_id = fields.Many2one(related="request_id.company_id", store=True, index=True)
    event_type = fields.Char(required=True, index="btree", readonly=True)
    status = fields.Selection([("received", "Received"), ("processed", "Processed"), ("failed", "Failed")], default="received", required=True, index=True, readonly=True)
    error_message = fields.Text(readonly=True)

    _event_id_unique = models.Constraint("UNIQUE(event_id)", "Webhook event ID must be unique.")
