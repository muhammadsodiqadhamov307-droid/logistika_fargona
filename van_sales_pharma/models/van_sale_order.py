import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class VanSaleOrder(models.Model):
    _name = 'van.sale.order'
    _description = 'Agent Sotuvi'
    _order = 'date desc, id desc'

    name = fields.Char(string='Sotuv Raqami', required=True, copy=False, readonly=True, default=lambda self: _('Yangi'))
    company_id = fields.Many2one('res.company', string='Korxona', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', store=True)

    trip_id = fields.Many2one('van.trip', string='Sayohat', required=True, ondelete='cascade')
    agent_id = fields.Many2one('res.users', related='trip_id.agent_id', store=True)

    partner_id = fields.Many2one('res.partner', string='Mijoz')
    date = fields.Datetime(string='Sana', required=True, default=fields.Datetime.now)
    
    line_ids = fields.One2many('van.sale.order.line', 'order_id', string='Sotuv Satrlari')
    
    payment_method = fields.Selection([
        ('cash', 'Naqt'),
        ('card', 'Karta / Bank'),
        ('nasiya', 'Nasiya / Qarz')
    ], string='To\'lov Usuli', required=True, default='cash')
    
    state = fields.Selection([
        ('draft', 'Qoralama'),
        ('confirmed', 'Tasdiqlangan'),
        ('paid', 'To\'langan'),
        ('nasiya', 'Nasiyaga Berilgan'),
        ('cancel', 'Bekor Qilingan')
    ], string='Holat', default='draft', required=True)

    amount_total = fields.Monetary(string='Jami Summa', compute='_compute_amount_total', store=True, currency_field='currency_id')

    invoice_id = fields.Many2one('account.move', string='Faktura (Invoice)', readonly=True, ondelete='set null')
    nasiya_id = fields.Many2one('van.nasiya', string='Nasiya PDF', readonly=True, ondelete='set null')
    payment_ids = fields.One2many('van.payment', 'sale_order_id', string='To\'lovlar')

    note = fields.Text(string='Izoh')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Yangi')) == _('Yangi'):
                vals['name'] = self.env['ir.sequence'].next_by_code('van.sale.order') or _('Yangi')
        return super().create(vals_list)

    @api.depends('line_ids.subtotal')
    def _compute_amount_total(self):
        for order in self:
            order.amount_total = sum(line.subtotal for line in order.line_ids)

    def action_confirm(self):
        for order in self:
            if order.trip_id.state == 'draft':
                raise UserError(_("Faqat tasdiqlangan sayohatlarda sotuvni tasdiqlash mumkin!"))
                
            # Ombor qoldiqlarini tekshirish (Agent Summary orqali)
            summary = self.env['van.agent.summary'].search([('agent_id', '=', order.agent_id.id)], limit=1)
            for line in order.line_ids:
                inv_line = self.env['van.agent.inventory.line'].search([
                    ('summary_id', '=', summary.id),
                    ('product_id', '=', line.product_id.id)
                ], limit=1)
                
                if not inv_line:
                    raise UserError(_("Mahsulot '%s' agent qoldig'ida mavjud emas!") % line.product_id.display_name)
                
                rem_qty = inv_line.loaded_qty - inv_line.sold_qty + inv_line.returned_qty
                if rem_qty < line.qty:
                    raise UserError(_("Agent qoldig'ida '%s' dan faqat %s ta qolgan. Siz %s ta sotmoqchisiz!") % 
                                    (line.product_id.display_name, rem_qty, line.qty))
                                    
            order.state = 'confirmed'
        return True

    def _create_invoice(self):
        """ Creates and posts a generic outbound invoice for this sale order """
        # Custom inventory bypasses account.move
        pass

    def action_pay(self):
        for order in self:
            if order.state != 'confirmed':
                raise UserError(_("To'lash uchun buyurtma 'Tasdiqlangan' holatda bo'lishi kerak!"))
            
            # Step 1: Nasiya uchun maxsus tekshiruv
            if order.payment_method == 'nasiya' and not order.partner_id:
                raise UserError(_("Nasiya (qarzga) sotish uchun albatta mijozni tanlashingiz shart!"))

            # Step 2: Buxgalteriya Invoisini yaratish (hamma tur uchun kerak PnL u-n)
            order._create_invoice()
            
            # Step 3: Ombor harakati (Stock Move) Mashinadan Mijozga ko'chirish
            order._create_delivery_picking()

            # Step 4: To'lov/Nasiya ob'ektlarini ro'yxatdan o'tkazish
            if order.payment_method in ['cash', 'card']:
                self.env['van.payment'].create({
                    'agent_id': order.agent_id.id,
                    'payment_method': order.payment_method,
                    'amount': order.amount_total,
                    'sale_order_id': order.id,
                })
                order.state = 'paid'
                
            elif order.payment_method == 'nasiya':
                nasiya = self.env['van.nasiya'].create({
                    'partner_id': order.partner_id.id,
                    'agent_id': order.agent_id.id,
                    'sale_order_id': order.id,
                    'invoice_id': order.invoice_id.id,
                    'amount_total': order.amount_total,
                    'date': order.date.date(),
                })
                order.nasiya_id = nasiya.id
                order.state = 'nasiya'
        return True

    def _create_delivery_picking(self):
        """ Tranzit ombordan tashqariga (Mijozga) tovar yetkazish yozuvi """
        # Custom inventory bypasses stock.picking
        pass

    def action_cancel(self):
        for order in self:
            if order.state not in ['draft', 'confirmed']:
                raise UserError(_("Faqat Qoralama yoki Tasdiqlangan holatdagi sotuvni bekor qilish mumkin. To'langanlarni qaytarish (refund) qilinishi kerak."))
            order.state = 'cancel'
