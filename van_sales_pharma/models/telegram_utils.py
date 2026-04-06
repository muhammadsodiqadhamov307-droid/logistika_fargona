import logging
import requests
from odoo import models, api

_logger = logging.getLogger(__name__)

class TelegramUtils(models.AbstractModel):
    _name = 'van.telegram.utils'
    _description = 'Telegram Bot Utility'

    @api.model
    def send_message(self, chat_id, text, reply_markup=None):
        """ Sends a generic text message to a Telegram Chat ID """
        if not chat_id:
            return False

        # Get the token from system settings
        token = self.env['ir.config_parameter'].sudo().get_param('van.telegram.bot.token')
        if not token:
            _logger.warning("Telegram Bot Token is not set in System Settings.")
            return False

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML'
        }
        
        if reply_markup is not None:
            payload['reply_markup'] = reply_markup

        try:
            response = requests.post(url, json=payload, timeout=5)
            response.raise_for_status()
            return True
        except Exception as e:
            _logger.error(f"Failed to send Telegram message to {chat_id}: {e}")
            return False
