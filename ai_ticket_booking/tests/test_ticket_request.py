from odoo.tests import TransactionCase, tagged
from odoo.exceptions import ValidationError


@tagged("post_install", "-at_install")
class TestAiTicketRequest(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env["ai.ticket.provider"].create({
            "name": "Test Museum",
            "code": "test_museum",
            "worker_provider_key": "test_museum",
            "timezone": "Europe/Rome",
            "release_mode": "announced",
            "requires_traveler_details": False,
        })

    def _request(self):
        return self.env["ai.ticket.request"].create({
            "prompt": "Two adult tickets at 10:00",
            "provider_id": self.provider.id,
            "visit_date": "2030-01-10",
            "release_strategy": "announced",
            "ticket_line_ids": [(0, 0, {"category": "adult", "quantity": 2})],
            "preference_line_ids": [(0, 0, {"sequence": 10, "time_value": "10:00"})],
        })

    def test_validate_moves_to_waiting_release(self):
        request = self._request()
        request.action_validate()
        self.assertEqual(request.state, "waiting_release")

    def test_invalid_time_rejected(self):
        request = self._request()
        with self.assertRaises(ValidationError):
            request.write({"earliest_time": "25:00"})

    def test_worker_payload_has_no_ai_dependency(self):
        request = self._request()
        request.action_validate()
        execution = self.env["ai.ticket.execution"].create({
            "request_id": request.id,
            "idempotency_key": "unit-test-idem",
        })
        payload = request._worker_payload(execution)
        self.assertEqual(payload["provider"], "test_museum")
        self.assertEqual(payload["time_rules"]["priority"], ["10:00"])
        self.assertNotIn("prompt", payload)
