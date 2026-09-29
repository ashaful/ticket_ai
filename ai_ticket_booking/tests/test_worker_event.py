from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAiTicketWorkerEvent(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        provider = cls.env["ai.ticket.provider"].create({
            "name": "Worker Test Museum",
            "code": "worker_test_museum",
            "worker_provider_key": "worker_test_museum",
            "timezone": "Europe/Rome",
            "release_mode": "announced",
            "requires_traveler_details": False,
        })
        cls.request = cls.env["ai.ticket.request"].create({
            "prompt": "One adult ticket at 10:00",
            "provider_id": provider.id,
            "visit_date": "2030-02-10",
            "release_strategy": "announced",
            "ticket_line_ids": [(0, 0, {"category": "adult", "quantity": 1})],
            "preference_line_ids": [(0, 0, {"sequence": 10, "time_value": "10:00"})],
        })
        cls.request.action_validate()

    def test_release_update_schedules_request(self):
        self.request._apply_worker_event({
            "type": "release.update",
            "request_uuid": self.request.public_uuid,
            "status": "announced",
            "release_at_utc": "2029-12-01T09:00:00Z",
        })
        self.assertEqual(self.request.state, "scheduled")
        self.assertTrue(self.request.release_id)

    def test_human_action_creates_queue_record(self):
        self.request._transition("preparing", force=True)
        self.request._transition("armed")
        self.request._transition("searching")
        self.request._transition("reserving")
        self.request._apply_worker_event({
            "type": "human_action.required",
            "request_uuid": self.request.public_uuid,
            "action_type": "captcha",
            "action_reference": "test-captcha-1",
            "priority": "2",
            "message": "Human CAPTCHA required",
        })
        self.assertEqual(self.request.state, "human_action")
        action = self.env["ai.ticket.action"].search([("request_id", "=", self.request.id)], limit=1)
        self.assertEqual(action.action_type, "captcha")
        self.assertEqual(action.status, "open")
