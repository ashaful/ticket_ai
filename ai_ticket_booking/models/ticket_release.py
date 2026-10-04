from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class AiTicketRelease(models.Model):
    _name = "ai.ticket.release"
    _description = "Ticket Release Information"
    _order = "release_at desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    provider_id = fields.Many2one("ai.ticket.provider", required=True, index=True, ondelete="cascade")
    company_id = fields.Many2one(related="provider_id.company_id", store=True, index=True)
    visit_date_from = fields.Date(index=True)
    visit_date_to = fields.Date(index=True)
    status = fields.Selection(
        [
            ("unknown", "Unknown"),
            ("estimated", "Estimated"),
            ("announced", "Announced"),
            ("confirmed", "Confirmed"),
            ("changed", "Changed"),
            ("live", "Live"),
        ],
        required=True,
        default="unknown",
        index=True,
    )
    release_at = fields.Datetime(index=True, help="Stored in UTC; provider timezone is preserved separately.")
    timezone = fields.Selection(related="provider_id.timezone", store=True, readonly=True)
    announced_at = fields.Datetime()
    source_type = fields.Selection(
        [("manual", "Manual"), ("worker", "Worker Monitor"), ("provider", "Provider Source")],
        default="manual",
        required=True,
    )
    source_reference = fields.Char(help="Public URL or external source identifier; do not store secrets here.")
    notes = fields.Text()

    _provider_release_idx = models.Index("(provider_id, release_at)")

    @api.depends("provider_id", "release_at", "status")
    def _compute_name(self):
        for rec in self:
            when = fields.Datetime.to_string(rec.release_at) if rec.release_at else _("Unknown time")
            rec.name = f"{rec.provider_id.name or ''} - {when} [{rec.status}]"

    @api.constrains("visit_date_from", "visit_date_to")
    def _check_date_range(self):
        for rec in self:
            if rec.visit_date_from and rec.visit_date_to and rec.visit_date_to < rec.visit_date_from:
                raise ValidationError(_("Visit date end cannot be before visit date start."))
