import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

class VanPayment(models.Model):
    _name = 'van.payment'
    _description = 'Agent To\'lovi'
    _order = 'date desc, id desc'

    name = fields.Char(string='To\'lov Raqami', required=True, copy=False, readonly=True, default=lambda self: _('Yangi'))
    company_id = fields.Many2one('res.company', string='Korxona', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', store=True)

    partner_id = fields.Many2one('res.partner', string='Kirim Qilgan Mijoz', help="POSdan qilingan mijoz qarzi to'lovi")
    agent_id = fields.Many2one('res.users', string='Agent', required=True, default=lambda self: self.env.user)
    sale_order_id = fields.Many2one('van.sale.order', string='Sotuv', ondelete='cascade')
    nasiya_id = fields.Many2one('van.nasiya', string='Nasiya', ondelete='cascade')
    taminotchi_id = fields.Many2one('van.taminotchi', string="Taminotchi (Yetkazib beruvchi)", ondelete='cascade')
    taminotchi_balance_dummy = fields.Monetary(
        string="Hisobidagi Qoldiq", 
        related='taminotchi_id.balance', 
        currency_field='currency_id', 
        readonly=True,
        help="Tanlangan Taminotchiga qancha qarzimiz borligini ko'rsatadi"
    )

    payment_type = fields.Selection([
        ('in', 'Kirim (+)') ,
        ('out', 'Chiqim (-)')
    ], string='Turi', default='in', required=True)

    expense_type = fields.Selection([
        ('daily', '🟡 Kunlik Chiqim'),
        ('salary', '🟣 Oylik Chiqim'),
        ('payout', '🟢 Oylik To\'lovi (Yopish)')
    ], string='Chiqim Turi', default='daily', help="Chiqim bo'lganda bu agentning oyligidan chegiriladimi yoki yo'q")
    
    offline_id = fields.Char(string='Offline ID', help="Takroriylikni oldini olish uchun Mobil Ilova tomondan yuborilgan ID")

    payment_method = fields.Selection([
        ('cash', 'Naqt'),
        ('card', 'Karta / Bank')
    ], string='To\'lov Usuli', required=True, default='cash')
    
    amount = fields.Monetary(string='Mablag\'', required=True, currency_field='currency_id')
    date = fields.Datetime(string='Sana', default=fields.Datetime.now, required=True)
    
    state = fields.Selection([
        ('received', 'Qabul Qilingan'),
        ('confirmed', 'Tasdiqlangan (Buxgalteriya)')
    ], string='Holat', default='received', required=True)
    
    note = fields.Text(string='Izoh')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Yangi')) == _('Yangi'):
                vals['name'] = self.env['ir.sequence'].next_by_code('van.payment') or _('Yangi')
        records = super().create(vals_list)
        
        # Telegram notification must never block payment creation.
        for rec in records:
            if rec.payment_type != 'in' or not rec.partner_id or not rec.partner_id.telegram_chat_id:
                continue
            try:
                rec.partner_id._compute_van_nasiya_stats()
                local_dt = fields.Datetime.context_timestamp(
                    rec.with_context(tz=self.env.user.tz or 'Asia/Tashkent'),
                    rec.date,
                )
                date_str = local_dt.strftime('%Y-%m-%d %H:%M')

                msg = f"✅ <b>To'lov qabul qilindi</b>\n"
                msg += f"📅 {date_str}\n"
                msg += f"💵 Miqdor: {rec.amount:,.0f} so'm\n"
                msg += f"💳 Qolgan qarz: {rec.partner_id.x_van_total_due:,.0f} so'm"

                self.env['van.telegram.utils'].send_message(
                    rec.partner_id.telegram_chat_id,
                    msg,
                )
            except Exception:
                _logger.exception("Failed post-create kirim notification for van.payment %s", rec.id)
        return records
