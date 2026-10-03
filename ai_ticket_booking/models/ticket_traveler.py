import uuid

from odoo import api, fields, models, _
from odoo.exceptions import AccessError


class AiTicketTraveler(models.Model):
    _name = "ai.ticket.traveler"
    _description = "Ticket Traveler"
    _order = "last_name, first_name"

    traveler_uuid = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, readonly=True, copy=False, index="btree")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True, ondelete="cascade"
    )
    owner_user_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user, index=True, ondelete="restrict"
    )
    partner_id = fields.Many2one("res.partner", ondelete="set null")
    first_name = fields.Char(required=True)
    last_name = fields.Char(required=True)
    name = fields.Char(compute="_compute_name", store=True, index="btree")
    birth_date = fields.Date()
    nationality_id = fields.Many2one("res.country", ondelete="set null")
    email = fields.Char()
    phone = fields.Char()
    document_type = fields.Selection(
        [("passport", "Passport"), ("national_id", "National ID"), ("other", "Other")],
        groups="ai_ticket_booking.group_ai_ticket_manager",
    )
    document_number = fields.Char(
        groups="ai_ticket_booking.group_ai_ticket_manager",
        copy=False,
        help="Sensitive identity data. Store only when a provider genuinely requires it.",
    )
    external_reference = fields.Char(index="btree")

    _traveler_uuid_unique = models.Constraint("UNIQUE(traveler_uuid)", "Traveler UUID must be unique.")
    _company_owner_idx = models.Index("(company_id, owner_user_id)")

    @api.depends("first_name", "last_name")
    def _compute_name(self):
        for rec in self:
            rec.name = " ".join(filter(None, [rec.first_name, rec.last_name]))


    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.user.has_group("ai_ticket_booking.group_ai_ticket_operator"):
            for vals in vals_list:
                if vals.get("owner_user_id") and vals["owner_user_id"] != self.env.user.id:
                    raise AccessError(_("You cannot create traveler profiles for another user."))
        return super().create(vals_list)

    def write(self, vals):
        if "owner_user_id" in vals and not self.env.user.has_group("ai_ticket_booking.group_ai_ticket_operator"):
            if vals["owner_user_id"] != self.env.user.id:
                raise AccessError(_("You cannot reassign traveler ownership."))
        return super().write(vals)

    def _to_worker_payload(self, include_sensitive=False):
        self.ensure_one()
        payload = {
            "traveler_uuid": self.traveler_uuid,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "birth_date": fields.Date.to_string(self.birth_date) if self.birth_date else None,
            "nationality": self.nationality_id.code or None,
            "email": self.email or None,
            "phone": self.phone or None,
        }
        if include_sensitive:
            payload.update({
                "document_type": self.document_type or None,
                "document_number": self.document_number or None,
            })
        return payload
