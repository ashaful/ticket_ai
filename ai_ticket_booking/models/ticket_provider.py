from odoo import api, fields, models, _
from odoo.addons.base.models.res_partner import _tz_get
from odoo.exceptions import ValidationError


class AiTicketProvider(models.Model):
    _name = "ai.ticket.provider"
    _description = "AI Ticket Provider"
    _order = "name"

    name = fields.Char(required=True, index="btree")
    code = fields.Char(required=True, index="btree", help="Stable technical identifier, e.g. vatican_museums.")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True, ondelete="cascade"
    )
    website_url = fields.Char()
    timezone = fields.Selection(
        selection=_tz_get,
        required=True,
        default="UTC",
        help="Provider local timezone. Release times are converted and stored in UTC by Odoo.",
    )
    release_mode = fields.Selection(
        [
            ("fixed", "Fixed Schedule"),
            ("announced", "Announced Schedule"),
            ("watch", "Availability Watch"),
        ],
        required=True,
        default="announced",
    )
    worker_provider_key = fields.Char(
        required=True,
        help="Provider key understood by the external booking worker. This is not a secret.",
    )
    default_currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id, required=True
    )
    requires_traveler_details = fields.Boolean(default=True)
    requires_identity_document = fields.Boolean(default=False)
    booking_supported = fields.Boolean(default=True)
    release_monitor_supported = fields.Boolean(default=False)
    notes = fields.Text()

    _code_company_unique = models.Constraint(
        "UNIQUE(code, company_id)",
        "Provider code must be unique per company.",
    )
    _worker_key_company_unique = models.Constraint(
        "UNIQUE(worker_provider_key, company_id)",
        "Worker provider key must be unique per company.",
    )

    @api.constrains("code", "worker_provider_key")
    def _check_technical_keys(self):
        allowed = set("abcdefghijklmnopqrstuvwxyz0123456789_-")
        for rec in self:
            for value, label in ((rec.code, _("Provider code")), (rec.worker_provider_key, _("Worker provider key"))):
                if value and any(ch not in allowed for ch in value):
                    raise ValidationError(_("%s may contain only lowercase letters, numbers, underscore and hyphen.") % label)
