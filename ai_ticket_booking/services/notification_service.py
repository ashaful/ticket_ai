import logging

import requests

from odoo import models, _

_logger = logging.getLogger(__name__)


class AiTicketNotificationService(models.AbstractModel):
    _name = "ai.ticket.notification.service"
    _description = "AI Ticket Human Action Notification Service"

    def _config(self):
        params = self.env["ir.config_parameter"].sudo()
        return {
            "channel": (params.get_param("ai_ticket.notify_channel") or "none").strip(),
            "destination": (params.get_param("ai_ticket.notify_destination") or "").strip(),
            "telegram_token": (params.get_param("ai_ticket.telegram_bot_token") or "").strip(),
            "whatsapp_token": (params.get_param("ai_ticket.whatsapp_access_token") or "").strip(),
            "whatsapp_phone_number_id": (params.get_param("ai_ticket.whatsapp_phone_number_id") or "").strip(),
        }

    def notify_action(self, action):
        action.ensure_one()
        cfg = self._config()
        channel = cfg["channel"]
        destination = cfg["destination"]
        if channel == "none" or not destination:
            return False

        try:
            takeover_url = self.env["ai.ticket.worker.client"]._get_takeover_url(action)
        except Exception as exc:
            _logger.warning("Could not create Take Control URL for notification: %s", exc)
            takeover_url = False

        request = action.request_id
        message = _(
            "Ticket AI needs your action.\n"
            "Request: %(request)s\n"
            "Type: %(type)s\n"
            "Status: %(status)s"
        ) % {
            "request": request.name,
            "type": dict(action._fields["action_type"].selection).get(action.action_type, action.action_type),
            "status": dict(action._fields["status"].selection).get(action.status, action.status),
        }
        if takeover_url:
            message += "\nTake Control: %s" % takeover_url

        if channel == "email":
            self.env["mail.mail"].sudo().create({
                "subject": _("Ticket AI action required: %s") % request.name,
                "body_html": "<pre>%s</pre>" % message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"),
                "email_to": destination,
            }).send()
            return True

        if channel == "telegram":
            token = cfg["telegram_token"]
            if not token:
                _logger.warning("Telegram notification is enabled but no bot token is configured")
                return False
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": destination, "text": message, "disable_web_page_preview": True},
                timeout=(3, 8),
            )
            response.raise_for_status()
            return True

        if channel == "whatsapp":
            token = cfg["whatsapp_token"]
            phone_id = cfg["whatsapp_phone_number_id"]
            if not token or not phone_id:
                _logger.warning("WhatsApp notification is enabled but Cloud API credentials are incomplete")
                return False
            response = requests.post(
                f"https://graph.facebook.com/v21.0/{phone_id}/messages",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "messaging_product": "whatsapp",
                    "to": destination,
                    "type": "text",
                    "text": {"preview_url": True, "body": message},
                },
                timeout=(3, 10),
            )
            response.raise_for_status()
            return True

        return False
