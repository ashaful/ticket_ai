import uuid

from odoo import fields, models, _
from odoo.exceptions import AccessError, UserError


class AiTicketAction(models.Model):
    _name = "ai.ticket.action"
    _description = "Ticket Human Action"
    _order = "priority desc, create_date asc, id asc"

    action_uuid = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, readonly=True, index="btree")
    request_id = fields.Many2one("ai.ticket.request", required=True, index=True, ondelete="cascade")
    execution_id = fields.Many2one("ai.ticket.execution", index=True, ondelete="set null")
    company_id = fields.Many2one(related="request_id.company_id", store=True, index=True)
    action_type = fields.Selection(
        [
            ("captcha", "CAPTCHA"),
            ("otp", "OTP / Verification Code"),
            ("payment", "Payment"),
            ("consent", "Consent / Terms"),
            ("unexpected", "Unexpected Provider Challenge"),
        ],
        required=True,
        index=True,
    )
    priority = fields.Selection(
        [("0", "Normal"), ("1", "High"), ("2", "Critical")],
        required=True,
        default="1",
        index=True,
    )
    status = fields.Selection(
        [
            ("open", "Open"),
            ("in_progress", "In Progress"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
            ("expired", "Expired"),
        ],
        required=True,
        default="open",
        index=True,
    )
    expires_at = fields.Datetime(index=True)
    instructions = fields.Text()
    external_reference = fields.Char(index="btree", help="Worker-side action reference. Must not contain secrets.")
    claimed_by_id = fields.Many2one("res.users", ondelete="set null", readonly=True)
    claimed_at = fields.Datetime(readonly=True)
    resolved_at = fields.Datetime(readonly=True)

    _action_uuid_unique = models.Constraint("UNIQUE(action_uuid)", "Action UUID must be unique.")
    _request_status_idx = models.Index("(request_id, status)")

    def action_take_control(self):
        self.ensure_one()
        if not self.env.user.has_group("ai_ticket_booking.group_ai_ticket_operator"):
            raise AccessError(_("Ticket Operator access is required."))
        if self.status not in ("open", "in_progress"):
            raise UserError(_("This action is no longer active."))
        if self.action_type not in ("captcha", "otp", "consent", "unexpected", "payment"):
            raise UserError(_("This action does not support browser takeover."))
        self.write({
            "status": "in_progress",
            "claimed_by_id": self.env.user.id,
            "claimed_at": fields.Datetime.now(),
        })
        url = self.env["ai.ticket.worker.client"]._get_takeover_url(self)
        return {"type": "ir.actions.act_url", "url": url, "target": "new"}

    def action_resume(self):
        self.ensure_one()
        if not self.env.user.has_group("ai_ticket_booking.group_ai_ticket_operator"):
            raise AccessError(_("Ticket Operator access is required."))
        if self.status not in ("open", "in_progress"):
            raise UserError(_("This action is no longer active."))
        self.env["ai.ticket.worker.client"]._resume_human_action(self)
        self.write({"status": "done", "resolved_at": fields.Datetime.now()})
        return self.request_id._notification(_("Resume command accepted by the booking worker."), "success")
