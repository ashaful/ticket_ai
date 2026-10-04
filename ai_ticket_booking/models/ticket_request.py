import re
import uuid
from collections import Counter
from datetime import datetime, timezone

from odoo import api, fields, models, Command, _
from odoo.exceptions import AccessError, UserError, ValidationError

TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class AiTicketRequestLine(models.Model):
    _name = "ai.ticket.request.line"
    _description = "Ticket Request Quantity"
    _order = "sequence, id"

    request_id = fields.Many2one("ai.ticket.request", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    category = fields.Selection(
        [("adult", "Adult"), ("child", "Child"), ("student", "Student"), ("senior", "Senior"), ("other", "Other")],
        required=True,
    )
    label = fields.Char()
    quantity = fields.Integer(required=True, default=1)

    _quantity_positive = models.Constraint("CHECK(quantity > 0)", "Ticket quantity must be greater than zero.")


class AiTicketPreferenceLine(models.Model):
    _name = "ai.ticket.preference.line"
    _description = "Ticket Time Preference"
    _order = "sequence, id"

    request_id = fields.Many2one("ai.ticket.request", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(required=True, default=10)
    time_value = fields.Char(required=True, help="24-hour provider-local time, HH:MM.")

    @api.constrains("time_value")
    def _check_time_value(self):
        for rec in self:
            if rec.time_value and not TIME_RE.match(rec.time_value):
                raise ValidationError(_("Time preference must use 24-hour HH:MM format."))


class AiTicketRequestTraveler(models.Model):
    _name = "ai.ticket.request.traveler"
    _description = "Ticket Request Traveler"
    _order = "sequence, id"

    request_id = fields.Many2one("ai.ticket.request", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    traveler_id = fields.Many2one("ai.ticket.traveler", required=True, ondelete="restrict")
    ticket_category = fields.Selection(
        [("adult", "Adult"), ("child", "Child"), ("student", "Student"), ("senior", "Senior"), ("other", "Other")],
        required=True,
        default="adult",
    )


    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.user.has_group("ai_ticket_booking.group_ai_ticket_operator"):
            Request = self.env["ai.ticket.request"]
            Traveler = self.env["ai.ticket.traveler"]
            for vals in vals_list:
                req = Request.browse(vals.get("request_id")).exists()
                traveler = Traveler.browse(vals.get("traveler_id")).exists()
                if not req or req.owner_user_id != self.env.user or not traveler or traveler.owner_user_id != self.env.user:
                    raise AccessError(_("You can only attach your own traveler profiles to your own booking request."))
        return super().create(vals_list)

    def write(self, vals):
        result = super().write(vals)
        if not self.env.user.has_group("ai_ticket_booking.group_ai_ticket_operator"):
            for rec in self:
                if rec.request_id.owner_user_id != self.env.user or rec.traveler_id.owner_user_id != self.env.user:
                    raise AccessError(_("You can only attach your own traveler profiles to your own booking request."))
        return result


class AiTicketRequest(models.Model):
    _name = "ai.ticket.request"
    _description = "AI Ticket Booking Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "priority desc, create_date desc, id desc"

    LOCKED_STATES = {"preparing", "armed", "searching", "reserving", "human_action", "payment_required", "completed"}
    PROTECTED_RULE_FIELDS = {
        "provider_id", "visit_date", "product_name", "visit_language", "visitor_type",
        "ticket_line_ids", "preference_line_ids", "earliest_time", "latest_time",
        "max_total_price", "currency_id", "traveler_line_ids", "release_strategy", "release_id",
        "stop_on_captcha", "stop_on_otp", "stop_on_payment", "allow_early_availability",
    }
    STATE_TRANSITIONS = {
        "draft": {"ai_processing", "cancelled"},
        "ai_processing": {"parsed", "needs_info", "draft"},
        "needs_info": {"ai_processing", "parsed", "cancelled"},
        "parsed": {"validated", "needs_info", "cancelled"},
        "validated": {"waiting_release", "scheduled", "preparing", "cancelled"},
        "waiting_release": {"scheduled", "preparing", "armed", "human_action", "failed", "cancelled"},
        "scheduled": {"preparing", "armed", "human_action", "failed", "cancelled"},
        "preparing": {"waiting_release", "armed", "human_action", "failed", "cancelled"},
        "armed": {"searching", "human_action", "failed", "cancelled"},
        "searching": {"reserving", "sold_out", "no_match", "human_action", "failed", "cancelled"},
        "reserving": {"human_action", "payment_required", "completed", "sold_out", "failed", "cancelled"},
        "human_action": {"preparing", "armed", "searching", "reserving", "payment_required", "completed", "failed", "cancelled"},
        "payment_required": {"reserving", "completed", "failed", "cancelled"},
        "failed": {"validated", "cancelled"},
        "sold_out": {"validated", "cancelled"},
        "no_match": {"validated", "cancelled"},
        "completed": set(),
        "cancelled": {"validated"},
    }

    name = fields.Char(default="New", required=True, readonly=True, copy=False, index="btree")
    public_uuid = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, readonly=True, copy=False, index="btree")
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True, ondelete="cascade"
    )
    owner_user_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user, index=True, tracking=True, ondelete="restrict"
    )
    priority = fields.Selection(
        [("0", "Normal"), ("1", "High"), ("2", "Critical")], default="0", required=True, index=True, tracking=True
    )
    state = fields.Selection(
        [
            ("draft", "Draft"), ("ai_processing", "AI Processing"), ("needs_info", "Needs Information"),
            ("parsed", "AI Parsed"), ("validated", "Validated"), ("waiting_release", "Waiting Release"),
            ("scheduled", "Scheduled"), ("preparing", "Preparing"), ("armed", "Armed"),
            ("searching", "Searching"), ("reserving", "Reserving"), ("human_action", "Human Action"),
            ("payment_required", "Payment Required"), ("completed", "Completed"), ("sold_out", "Sold Out"),
            ("no_match", "No Matching Slot"), ("failed", "Failed"), ("cancelled", "Cancelled"),
        ],
        required=True,
        default="draft",
        index=True,
        tracking=True,
        copy=False,
    )

    prompt = fields.Text(required=True, tracking=False)
    ai_result_json = fields.Json(copy=False, groups="ai_ticket_booking.group_ai_ticket_operator")
    ai_model_used = fields.Char(copy=False, readonly=True)
    ai_missing_fields = fields.Json(copy=False, readonly=True)
    ai_error = fields.Text(copy=False, readonly=True)

    provider_id = fields.Many2one("ai.ticket.provider", index=True, tracking=True, domain="[('company_id', '=', company_id), ('active', '=', True)]")
    visit_date = fields.Date(index=True, tracking=True)
    product_name = fields.Char(string="Exact Product", tracking=True, help="Exact provider product title. Leave empty for the provider's standard admission product.")
    visit_language = fields.Char(string="Visit Language", tracking=True, help="Required language for guided products, for example English.")
    visitor_type = fields.Selection(
        [("individuals", "Individuals"), ("groups", "Groups")],
        string="Visitor Type",
        tracking=True,
    )
    ticket_line_ids = fields.One2many("ai.ticket.request.line", "request_id", string="Tickets", copy=True)
    preference_line_ids = fields.One2many("ai.ticket.preference.line", "request_id", string="Time Priority", copy=True)
    preferred_time = fields.Char(compute="_compute_preferred_time", store=True)
    earliest_time = fields.Char(help="24-hour provider-local time, HH:MM.")
    latest_time = fields.Char(help="24-hour provider-local time, HH:MM.")
    max_total_price = fields.Monetary(currency_field="currency_id", tracking=True)
    currency_id = fields.Many2one("res.currency", required=True, default=lambda self: self.env.company.currency_id)
    traveler_line_ids = fields.One2many("ai.ticket.request.traveler", "request_id", string="Travelers", copy=True)

    release_strategy = fields.Selection(
        [("unknown", "Unknown"), ("fixed", "Fixed"), ("announced", "Announced"), ("watch", "Availability Watch")],
        required=True,
        default="unknown",
        tracking=True,
    )
    release_id = fields.Many2one("ai.ticket.release", ondelete="set null", index=True, tracking=True)
    release_at = fields.Datetime(related="release_id.release_at", store=True, readonly=True, index=True)
    provider_timezone = fields.Selection(related="provider_id.timezone", readonly=True)

    stop_on_captcha = fields.Boolean(default=True)
    stop_on_otp = fields.Boolean(default=True)
    stop_on_payment = fields.Boolean(default=True)
    allow_early_availability = fields.Boolean(default=True)

    active_execution_id = fields.Many2one("ai.ticket.execution", copy=False, readonly=True, ondelete="set null")
    execution_ids = fields.One2many("ai.ticket.execution", "request_id", readonly=True)
    action_ids = fields.One2many("ai.ticket.action", "request_id", readonly=True)
    open_action_count = fields.Integer(compute="_compute_open_action_count")
    execution_count = fields.Integer(compute="_compute_execution_count")
    rules_version = fields.Integer(default=1, required=True, readonly=True, copy=False)
    failure_code = fields.Char(readonly=True, copy=False, index="btree")
    failure_message = fields.Text(readonly=True, copy=False)

    _public_uuid_unique = models.Constraint("UNIQUE(public_uuid)", "Booking request UUID must be unique.")
    _name_unique = models.Constraint("UNIQUE(name)", "Booking request reference must be unique.")
    _state_company_idx = models.Index("(state, company_id)")
    _visit_provider_idx = models.Index("(provider_id, visit_date)")

    @api.depends("preference_line_ids.sequence", "preference_line_ids.time_value")
    def _compute_preferred_time(self):
        for rec in self:
            ordered = rec.preference_line_ids.sorted(key=lambda x: (x.sequence, x.id))
            rec.preferred_time = ordered[:1].time_value if ordered else False

    def _compute_open_action_count(self):
        grouped = self.env["ai.ticket.action"]._read_group(
            [("request_id", "in", self.ids), ("status", "in", ["open", "in_progress"])],
            ["request_id"], ["__count"],
        ) if self.ids else []
        counts = {request.id: count for request, count in grouped}
        for rec in self:
            rec.open_action_count = counts.get(rec.id, 0)

    def _compute_execution_count(self):
        grouped = self.env["ai.ticket.execution"]._read_group(
            [("request_id", "in", self.ids)], ["request_id"], ["__count"]
        ) if self.ids else []
        counts = {request.id: count for request, count in grouped}
        for rec in self:
            rec.execution_count = counts.get(rec.id, 0)

    @api.constrains("earliest_time", "latest_time")
    def _check_time_bounds(self):
        for rec in self:
            for value in (rec.earliest_time, rec.latest_time):
                if value and not TIME_RE.match(value):
                    raise ValidationError(_("Time bounds must use 24-hour HH:MM format."))
            if rec.earliest_time and rec.latest_time and rec.earliest_time > rec.latest_time:
                raise ValidationError(_("Earliest time cannot be after latest time."))

    @api.constrains("max_total_price")
    def _check_max_price(self):
        for rec in self:
            if rec.max_total_price < 0:
                raise ValidationError(_("Maximum total price cannot be negative."))

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env["ir.sequence"]
        is_operator = self.env.user.has_group("ai_ticket_booking.group_ai_ticket_operator")
        for vals in vals_list:
            if vals.get("owner_user_id") and vals["owner_user_id"] != self.env.user.id and not is_operator:
                raise AccessError(_("You cannot create booking requests for another user."))
            if vals.get("name", "New") == "New":
                vals["name"] = sequence.next_by_code("ai.ticket.request") or "New"
        return super().create(vals_list)

    def write(self, vals):
        if "owner_user_id" in vals and vals["owner_user_id"] != self.env.user.id and not self.env.user.has_group("ai_ticket_booking.group_ai_ticket_operator"):
            raise AccessError(_("You cannot reassign booking ownership."))
        protected = self.PROTECTED_RULE_FIELDS.intersection(vals)
        if not self.env.context.get("ai_ticket_allow_locked_write"):
            if protected and any(rec.state in self.LOCKED_STATES for rec in self):
                raise UserError(_("Booking rules cannot be changed while a booking is active. Cancel/reset it first."))
        if protected and not self.env.context.get("ai_ticket_skip_rule_version") and len(self) > 1:
            for rec in self:
                rec_vals = dict(vals, rules_version=rec.rules_version + 1)
                super(AiTicketRequest, rec).write(rec_vals)
            return True
        if protected and not self.env.context.get("ai_ticket_skip_rule_version"):
            vals = dict(vals, rules_version=self.rules_version + 1)
        return super().write(vals)

    def _require_operator(self):
        if not self.env.user.has_group("ai_ticket_booking.group_ai_ticket_operator"):
            raise AccessError(_("Ticket Operator access is required for this operation."))

    def _notification(self, message, level="info"):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": _("AI Ticket Booking"), "message": message, "type": level, "sticky": False},
        }

    def _transition(self, new_state, *, failure_code=None, failure_message=None, force=False):
        self.ensure_one()
        if not force and new_state != self.state and new_state not in self.STATE_TRANSITIONS.get(self.state, set()):
            raise ValidationError(_("Invalid booking state transition: %s → %s") % (self.state, new_state))
        vals = {"state": new_state}
        if failure_code is not None:
            vals["failure_code"] = failure_code
        if failure_message is not None:
            vals["failure_message"] = failure_message
        if new_state not in ("failed", "sold_out", "no_match"):
            vals.setdefault("failure_code", False)
            vals.setdefault("failure_message", False)
        self.with_context(ai_ticket_allow_locked_write=True, ai_ticket_skip_rule_version=True).write(vals)

    def action_parse_with_ai(self):
        self.ensure_one()
        if self.state not in ("draft", "needs_info", "parsed"):
            raise UserError(_("AI parsing is only available before validation."))
        self._transition("ai_processing", force=self.state == "parsed")
        providers = self.env["ai.ticket.provider"].search([("company_id", "=", self.company_id.id), ("active", "=", True)])
        try:
            parsed, model = self.env["ai.ticket.gemini.service"]._parse_prompt(self.prompt, providers.mapped("name"))
            self._apply_ai_result(parsed, model)
        except UserError as exc:
            self.with_context(ai_ticket_skip_rule_version=True).write({"ai_error": str(exc)})
            self._transition("draft", force=True)
            return self._notification(str(exc), "danger")
        return self._notification(_("Prompt parsed successfully. Review the structured booking rules before validation."), "success")

    def _apply_ai_result(self, parsed, model):
        self.ensure_one()
        ticket_commands = [Command.clear()]
        for idx, line in enumerate(parsed.get("ticket_lines") or [], start=1):
            quantity = int(line.get("quantity") or 0)
            if quantity > 0:
                ticket_commands.append(Command.create({
                    "sequence": idx * 10,
                    "category": line.get("category") if line.get("category") in dict(self.env["ai.ticket.request.line"]._fields["category"].selection) else "other",
                    "label": line.get("label") or False,
                    "quantity": quantity,
                }))
        times = []
        preferred = parsed.get("preferred_time")
        if preferred:
            times.append(preferred)
        for value in parsed.get("fallback_times") or []:
            if value and value not in times:
                times.append(value)
        preference_commands = [Command.clear()]
        for idx, value in enumerate(times, start=1):
            if TIME_RE.match(value or ""):
                preference_commands.append(Command.create({"sequence": idx * 10, "time_value": value}))

        provider = self.provider_id
        hint = (parsed.get("provider_hint") or "").strip()
        if not provider and hint:
            provider = self.env["ai.ticket.provider"].search([
                ("company_id", "=", self.company_id.id),
                "|", ("code", "=ilike", hint.replace(" ", "_")), ("name", "ilike", hint),
            ], limit=1)

        currency = self.currency_id
        currency_code = (parsed.get("currency") or "").strip().upper()
        if currency_code:
            found_currency = self.env["res.currency"].search([("name", "=", currency_code)], limit=1)
            if found_currency:
                currency = found_currency

        visit_date = False
        if parsed.get("visit_date"):
            try:
                visit_date = fields.Date.to_date(parsed["visit_date"])
            except (ValueError, TypeError):
                visit_date = False

        release_mode = parsed.get("release_mode") or "unknown"
        if release_mode not in ("fixed", "announced", "watch", "unknown"):
            release_mode = "unknown"
        if release_mode == "unknown" and provider:
            release_mode = provider.release_mode

        missing = list(parsed.get("missing_fields") or [])
        if not provider:
            missing.append("provider")
        if not visit_date:
            missing.append("visit_date")
        if not any(int(line.get("quantity") or 0) > 0 for line in (parsed.get("ticket_lines") or [])):
            missing.append("ticket_quantity")

        vals = {
            "ai_result_json": parsed,
            "ai_model_used": model,
            "ai_missing_fields": sorted(set(missing)),
            "ai_error": False,
            "provider_id": provider.id if provider else False,
            "visit_date": visit_date,
            "product_name": (parsed.get("product_name") or "").strip() or False,
            "visit_language": (parsed.get("visit_language") or "").strip() or False,
            "visitor_type": parsed.get("visitor_type") if parsed.get("visitor_type") in ("individuals", "groups") else False,
            "ticket_line_ids": ticket_commands,
            "preference_line_ids": preference_commands,
            "earliest_time": parsed.get("earliest_time") if TIME_RE.match(parsed.get("earliest_time") or "") else False,
            "latest_time": parsed.get("latest_time") if TIME_RE.match(parsed.get("latest_time") or "") else False,
            "max_total_price": parsed.get("max_total_price") or 0.0,
            "currency_id": currency.id,
            "release_strategy": release_mode,
            "stop_on_captcha": bool(parsed.get("stop_on_captcha", True)),
            "stop_on_otp": bool(parsed.get("stop_on_otp", True)),
            "stop_on_payment": bool(parsed.get("stop_on_payment", True)),
            "allow_early_availability": bool(parsed.get("allow_early_availability", True)),
        }
        if not vals.get("visitor_type") and "grupp" in (vals.get("product_name") or "").casefold():
            vals["visitor_type"] = "groups"
        self.with_context(ai_ticket_skip_rule_version=True).write(vals)
        self._transition("needs_info" if missing else "parsed", force=True)

    def _validate_booking_rules(self):
        self.ensure_one()
        errors = []
        if not self.provider_id:
            errors.append(_("Provider is required."))
        if not self.visit_date:
            errors.append(_("Visit date is required."))
        elif self.visit_date < fields.Date.today():
            errors.append(_("Visit date cannot be in the past."))
        if not self.ticket_line_ids:
            errors.append(_("At least one ticket quantity is required."))
        if self.product_name and "visite guidate" in self.product_name.casefold() and not self.visit_language:
            errors.append(_("Visit language is required for the selected guided product."))
        if not self.preference_line_ids and not (self.earliest_time and self.latest_time):
            errors.append(_("Provide at least one preferred time or an allowed time range."))
        total_tickets = sum(self.ticket_line_ids.mapped("quantity"))
        if self.provider_id.requires_traveler_details and len(self.traveler_line_ids) != total_tickets:
            errors.append(_("Traveler count must match total ticket quantity for this provider."))
        if self.provider_id.requires_traveler_details and self.traveler_line_ids:
            ticket_counts = Counter()
            for line in self.ticket_line_ids:
                ticket_counts[line.category] += line.quantity
            traveler_counts = Counter(self.traveler_line_ids.mapped("ticket_category"))
            if ticket_counts != traveler_counts:
                errors.append(_("Traveler ticket categories must match the requested ticket quantities."))
        if self.release_id and self.provider_id and self.release_id.provider_id != self.provider_id:
            errors.append(_("Selected release information belongs to a different provider."))
        if self.release_id and self.visit_date:
            if self.release_id.visit_date_from and self.visit_date < self.release_id.visit_date_from:
                errors.append(_("Selected release information does not cover the requested visit date."))
            if self.release_id.visit_date_to and self.visit_date > self.release_id.visit_date_to:
                errors.append(_("Selected release information does not cover the requested visit date."))
        if self.release_strategy == "unknown":
            errors.append(_("Release strategy must be selected."))
        if self.release_strategy == "fixed" and not self.release_at:
            errors.append(_("Fixed release strategy requires a release date/time."))
        if self.provider_id.requires_identity_document:
            missing_docs = self.traveler_line_ids.filtered(lambda l: not l.traveler_id.document_number)
            if missing_docs:
                errors.append(_("Identity document data is required for every traveler by this provider."))
        if errors:
            raise ValidationError("\n".join(errors))
        return True

    def action_validate(self):
        self.ensure_one()
        # Validation can be triggered twice by a fast double-click or by a stale
        # form after the first RPC already advanced the workflow. Keep this
        # action idempotent for already-validated pre-execution states.
        allowed_states = {
            "draft", "parsed", "needs_info", "validated",
            "waiting_release", "scheduled",
            "failed", "sold_out", "no_match", "cancelled",
        }
        if self.state not in allowed_states:
            state_label = dict(self._fields["state"].selection).get(self.state, self.state)
            raise UserError(_("This request cannot be validated from its current state: %s") % state_label)

        self._validate_booking_rules()

        # If the first click already completed validation, return a harmless
        # notification instead of raising on the duplicate request.
        if self.state in ("waiting_release", "scheduled"):
            return self._notification(_("Booking rules are already validated."), "info")

        self._transition("validated", force=self.state != "parsed")
        if self.release_at:
            self._transition("scheduled")
        elif self.release_strategy in ("announced", "watch"):
            self._transition("waiting_release")
        return self._notification(_("Booking rules validated."), "success")

    def _worker_payload(self, execution):
        self.ensure_one()
        self._validate_booking_rules()
        sensitive = bool(self.provider_id.requires_identity_document)
        return {
            "schema_version": 2,
            "request_uuid": self.public_uuid,
            "execution_uuid": execution.execution_uuid,
            "rules_version": self.rules_version,
            "provider": self.provider_id.worker_provider_key,
            "visit_date": fields.Date.to_string(self.visit_date),
            "product": {
                "exact_name": self.product_name or None,
                "visit_language": self.visit_language or None,
                "visitor_type": self.visitor_type or None,
            },
            "release": {
                "strategy": self.release_strategy,
                "release_at_utc": fields.Datetime.to_string(self.release_at) if self.release_at else None,
                "provider_timezone": self.provider_id.timezone,
                "allow_early_availability": self.allow_early_availability,
            },
            "tickets": [
                {"category": line.category, "label": line.label or None, "quantity": line.quantity}
                for line in self.ticket_line_ids.sorted(key=lambda x: (x.sequence, x.id))
            ],
            "time_rules": {
                "priority": [line.time_value for line in self.preference_line_ids.sorted(key=lambda x: (x.sequence, x.id))],
                "earliest": self.earliest_time or None,
                "latest": self.latest_time or None,
            },
            "price_rule": {
                "max_total": self.max_total_price if self.max_total_price else None,
                "currency": self.currency_id.name,
            },
            "human_intervention": {
                "stop_on_captcha": self.stop_on_captcha,
                "stop_on_otp": self.stop_on_otp,
                "stop_on_payment": self.stop_on_payment,
            },
            "travelers": [
                dict(line.traveler_id._to_worker_payload(include_sensitive=sensitive), ticket_category=line.ticket_category)
                for line in self.traveler_line_ids.sorted(key=lambda x: (x.sequence, x.id))
            ],
        }

    def action_dispatch_to_worker(self):
        self.ensure_one()
        self._require_operator()
        if self.state not in ("validated", "waiting_release", "scheduled"):
            raise UserError(_("This request is not ready to dispatch."))
        self._validate_booking_rules()
        idem = f"booking:{self.public_uuid}:rules:{self.rules_version}"
        existing = self.env["ai.ticket.execution"].search([("idempotency_key", "=", idem)], limit=1)
        if existing:
            self.active_execution_id = existing.id
            return self._notification(_("This rules version was already dispatched; existing execution was reused."), "warning")
        execution = self.env["ai.ticket.execution"].create({
            "request_id": self.id,
            "idempotency_key": idem,
            "status": "created",
        })
        self.with_context(ai_ticket_allow_locked_write=True, ai_ticket_skip_rule_version=True).active_execution_id = execution.id
        try:
            result = self.env["ai.ticket.worker.client"]._dispatch_booking(execution, self._worker_payload(execution))
        except UserError as exc:
            execution.write({"status": "failed", "error_code": "dispatch_error", "error_message": str(exc), "finished_at": fields.Datetime.now()})
            self._log("error", "worker.dispatch_failed", str(exc), execution=execution)
            return self._notification(str(exc), "danger")
        execution.write({
            "worker_job_id": result.get("job_id") or result.get("booking_id"),
            "status": "queued",
            "response_json": {"job_id": result.get("job_id") or result.get("booking_id"), "status": result.get("status")},
            "last_event_at": fields.Datetime.now(),
        })
        if self.release_at:
            self._transition("scheduled", force=self.state not in ("validated", "waiting_release"))
        elif self.release_strategy in ("announced", "watch"):
            self._transition("waiting_release", force=self.state != "validated")
        self._log("info", "worker.dispatched", _("Booking request dispatched to external worker."), execution=execution)
        return self._notification(_("Booking request dispatched to the external worker."), "success")

    def action_cancel(self):
        for rec in self:
            if rec.state in ("completed", "cancelled"):
                continue
            execution = rec.active_execution_id
            if execution and execution.status not in ("completed", "failed", "cancelled"):
                try:
                    rec.env["ai.ticket.worker.client"]._cancel_booking(execution)
                except UserError as exc:
                    rec._log("warning", "worker.cancel_failed", str(exc), execution=execution)
            rec._transition("cancelled", force=True)
            if execution and execution.status not in ("completed", "failed"):
                execution.write({"status": "cancelled", "finished_at": fields.Datetime.now()})
        return True

    def action_reset_to_validated(self):
        self.ensure_one()
        self._require_operator()
        if self.state not in ("failed", "sold_out", "no_match", "cancelled"):
            raise UserError(_("Only failed, sold-out, no-match or cancelled requests can be reset."))
        self._validate_booking_rules()
        self.with_context(ai_ticket_allow_locked_write=True, ai_ticket_skip_rule_version=True).write({
            "active_execution_id": False,
            "rules_version": self.rules_version + 1,
            "failure_code": False,
            "failure_message": False,
        })
        self._transition("validated", force=True)
        return self._notification(_("Request reset. Review rules and dispatch a new execution."), "success")

    def action_view_actions(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Human Actions"), "res_model": "ai.ticket.action",
            "view_mode": "list,form", "domain": [("request_id", "=", self.id)],
            "context": {"default_request_id": self.id},
        }

    def action_view_executions(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Executions"), "res_model": "ai.ticket.execution",
            "view_mode": "list,form", "domain": [("request_id", "=", self.id)],
        }

    @api.model
    def _sanitize_log_payload(self, value):
        sensitive_fragments = ("token", "secret", "password", "cookie", "authorization", "card", "cvv", "captcha_answer", "session")
        if isinstance(value, dict):
            clean = {}
            for key, item in value.items():
                if any(fragment in str(key).lower() for fragment in sensitive_fragments):
                    clean[key] = "[REDACTED]"
                else:
                    clean[key] = self._sanitize_log_payload(item)
            return clean
        if isinstance(value, list):
            return [self._sanitize_log_payload(item) for item in value[:100]]
        if isinstance(value, str) and len(value) > 4000:
            return value[:4000] + "…"
        return value

    def _log(self, level, event_code, message, *, execution=None, duration_ms=0, payload=None):
        self.ensure_one()
        return self.env["ai.ticket.log"].sudo().create({
            "request_id": self.id,
            "execution_id": execution.id if execution else False,
            "level": level,
            "event_code": event_code,
            "message": message,
            "duration_ms": duration_ms or 0,
            "payload_json": self._sanitize_log_payload(payload) if payload else False,
        })

    @api.model
    def _parse_worker_datetime(self, value, field_label="datetime"):
        """Convert worker ISO-8601 timestamps to naive UTC datetimes for Odoo.

        The external worker uses RFC3339/ISO-8601 values such as
        ``2026-10-03T12:25:59.649971Z``. Odoo Datetime fields expect an
        ORM-compatible datetime (stored as naive UTC), so normalize the value
        before passing it to create/write.
        """
        if not value:
            return False
        if isinstance(value, datetime):
            parsed_dt = value
        else:
            try:
                parsed_dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
            except (TypeError, ValueError) as exc:
                raise ValidationError(_("Worker sent an invalid %s.") % field_label) from exc
        if parsed_dt.tzinfo:
            parsed_dt = parsed_dt.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed_dt.replace(microsecond=0)

    def _apply_worker_event(self, payload):
        self.ensure_one()
        event_type = payload.get("type")
        execution = False
        execution_uuid = payload.get("execution_uuid")
        if execution_uuid:
            execution = self.env["ai.ticket.execution"].search([
                ("request_id", "=", self.id), ("execution_uuid", "=", execution_uuid)
            ], limit=1)
        execution = execution or self.active_execution_id

        if event_type == "booking.state":
            new_state = payload.get("state")
            allowed_states = dict(self._fields["state"].selection)
            if new_state not in allowed_states:
                raise ValidationError(_("Worker sent an unknown booking state."))
            if execution:
                exec_status_map = {
                    "preparing": "running", "armed": "running", "searching": "running", "reserving": "running",
                    "human_action": "paused", "payment_required": "payment_required", "completed": "completed",
                    "failed": "failed", "sold_out": "failed", "no_match": "failed", "cancelled": "cancelled",
                }
                vals = {"last_event_at": fields.Datetime.now()}
                if new_state in exec_status_map:
                    vals["status"] = exec_status_map[new_state]
                if new_state in ("completed", "failed", "sold_out", "no_match", "cancelled"):
                    vals["finished_at"] = fields.Datetime.now()
                if not execution.started_at and new_state in ("preparing", "armed", "searching", "reserving"):
                    vals["started_at"] = fields.Datetime.now()
                if payload.get("error_code"):
                    vals["error_code"] = payload.get("error_code")
                if payload.get("message") and new_state in ("failed", "sold_out", "no_match"):
                    vals["error_message"] = payload.get("message")
                execution.write(vals)
            self._transition(
                new_state,
                failure_code=payload.get("error_code"),
                failure_message=payload.get("message"),
                force=False,
            )
            self._log(payload.get("level", "info"), f"worker.state.{new_state}", payload.get("message") or new_state, execution=execution, duration_ms=payload.get("duration_ms", 0))

        elif event_type == "human_action.required":
            action_type = payload.get("action_type")
            if action_type not in dict(self.env["ai.ticket.action"]._fields["action_type"].selection):
                action_type = "unexpected"
            existing = False
            ext_ref = payload.get("action_reference")
            if ext_ref:
                existing = self.env["ai.ticket.action"].search([
                    ("request_id", "=", self.id), ("external_reference", "=", ext_ref),
                    ("status", "in", ["open", "in_progress"]),
                ], limit=1)
            if not existing:
                self.env["ai.ticket.action"].create({
                    "request_id": self.id,
                    "execution_id": execution.id if execution else False,
                    "action_type": action_type,
                    "priority": payload.get("priority") if payload.get("priority") in ("0", "1", "2") else "2",
                    "expires_at": self._parse_worker_datetime(payload.get("expires_at"), _("human-action expiry")),
                    "instructions": payload.get("message") or False,
                    "external_reference": ext_ref or False,
                })
            if execution:
                execution.write({"status": "paused", "last_event_at": fields.Datetime.now()})
            self._transition("payment_required" if action_type == "payment" else "human_action", force=self.state not in ("reserving", "human_action", "payment_required"))
            self._log("warning", f"human_action.{action_type}", payload.get("message") or _("Human action required."), execution=execution)

        elif event_type == "human_action.resolved":
            ext_ref = payload.get("action_reference")
            action = self.env["ai.ticket.action"].search([
                ("request_id", "=", self.id), ("external_reference", "=", ext_ref)
            ], limit=1)
            if action:
                action.write({"status": "done", "resolved_at": fields.Datetime.now()})
            self._log("info", "human_action.resolved", payload.get("message") or _("Human action resolved."), execution=execution)

        elif event_type == "release.update":
            release_at = payload.get("release_at_utc")
            release_dt = False
            if release_at:
                try:
                    parsed_dt = datetime.fromisoformat(release_at.replace("Z", "+00:00"))
                    if parsed_dt.tzinfo:
                        parsed_dt = parsed_dt.astimezone(timezone.utc).replace(tzinfo=None)
                    release_dt = parsed_dt
                except (ValueError, TypeError):
                    raise ValidationError(_("Worker sent an invalid release date/time."))
            release = self.env["ai.ticket.release"].create({
                "provider_id": self.provider_id.id,
                "visit_date_from": self.visit_date,
                "visit_date_to": self.visit_date,
                "status": payload.get("status") if payload.get("status") in dict(self.env["ai.ticket.release"]._fields["status"].selection) else "announced",
                "release_at": release_dt,
                "announced_at": fields.Datetime.now(),
                "source_type": "worker",
                "source_reference": payload.get("source_reference") or False,
                "notes": payload.get("message") or False,
            })
            self.with_context(ai_ticket_allow_locked_write=True, ai_ticket_skip_rule_version=True).write({
                "release_id": release.id,
                "release_strategy": self.release_strategy if self.release_strategy != "unknown" else "announced",
            })
            if release_dt and self.state == "waiting_release":
                self._transition("scheduled")
            self._log("info", "release.update", payload.get("message") or _("Release information updated."), execution=execution)

        elif event_type == "execution.log":
            self._log(
                payload.get("level") if payload.get("level") in ("debug", "info", "warning", "error") else "info",
                payload.get("event_code") or "worker.log",
                payload.get("message") or "Worker event",
                execution=execution,
                duration_ms=int(payload.get("duration_ms") or 0),
                payload=payload.get("data"),
            )
        else:
            raise ValidationError(_("Unsupported worker event type."))
        return True
