from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    van_telegram_bot_token = fields.Char(
        string='Telegram Bot Token', 
        config_parameter='van.telegram.bot.token',
        help="Paste the HTTP API Token provided by BotFather here."
    )

    van_telegram_odoo_url = fields.Char(
        string='Odoo URL for Telegram Bot',
        config_parameter='van.telegram.odoo.url',
        help="Paste the external Odoo URL here (e.g. https://logistics1234.duckdns.org)."
    )
