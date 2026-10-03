import uuid

from odoo import fields, models


class AiTicketExecution(models.Model):
    _name = "ai.ticket.execution"
    _description = "Ticket Booking Execution"
    _order = "create_date desc, id desc"

    execution_uuid = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, readonly=True, index="btree")
    idempotency_key = fields.Char(required=True, readonly=True, index="btree")
    request_id = fields.Many2one("ai.ticket.request", required=True, index=True, ondelete="cascade")
    company_id = fields.Many2one(related="request_id.company_id", store=True, index=True)
    worker_job_id = fields.Char(index="btree", copy=False)
    status = fields.Selection(
        [
            ("created", "Created"),
            ("queued", "Queued"),
            ("running", "Running"),
            ("paused", "Paused"),
            ("payment_required", "Payment Required"),
            ("completed", "Completed"),
            ("failed", "Failed"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="created",
        index=True,
    )
    started_at = fields.Datetime()
    finished_at = fields.Datetime()
    last_event_at = fields.Datetime()
    error_code = fields.Char(index="btree")
    error_message = fields.Text()
    timing_json = fields.Json(copy=False)
    response_json = fields.Json(copy=False)

    _execution_uuid_unique = models.Constraint("UNIQUE(execution_uuid)", "Execution UUID must be unique.")
    _idempotency_unique = models.Constraint("UNIQUE(idempotency_key)", "Idempotency key must be unique.")
    _request_status_idx = models.Index("(request_id, status)")
