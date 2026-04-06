import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

class VanNasiya(models.Model):
    _name = 'van.nasiya'
    _description = 'Nasiya Boshqaruvi'
    _order = 'date desc, id desc'

    name = fields.Char(string='Nasiya Raqami', required=True, copy=False, readonly=True, default=lambda self: _('Yangi'))
    company_id = fields.Many2one('res.company', string='Korxona', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', store=True)

    partner_id = fields.Many2one('res.partner', string='Mijoz')
    agent_id = fields.Many2one('res.users', string='Savdo Agenti')
    sale_order_id = fields.Many2one('van.sale.order', string='Muloqot Sotuvi', ondelete='set null')
    invoice_id = fields.Many2one('account.move', string='Faktura (Invoice)', ondelete='cascade')

    date = fields.Date(string='Nasiya Sanasi', default=fields.Date.context_today)

    amount_total = fields.Monetary(string='Jami Qarz', required=True, currency_field='currency_id')
    amount_paid = fields.Monetary(string='To\'langan', compute='_compute_payment_amounts', store=True, currency_field='currency_id')
    amount_residual = fields.Monetary(string='Qolgan Qarz', compute='_compute_payment_amounts', store=True, currency_field='currency_id')
    
    # Yangi manual to'lov yozuvlari (Kirimlar orqali)
    payment_ids = fields.One2many('van.payment', 'nasiya_id', string="To'lovlar")

    state = fields.Selection([
        ('open', 'Ochiq'),
        ('partial', 'Qisman To\'langan'),
        ('paid', 'To\'langan Uzilgan')
    ], string='Holat', compute='_compute_state', store=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Yangi')) == _('Yangi'):
                vals['name'] = self.env['ir.sequence'].next_by_code('van.nasiya') or _('Yangi')
        return super().create(vals_list)

    @api.depends('invoice_id.amount_residual', 'payment_ids.amount', 'amount_total')
    def _compute_payment_amounts(self):
        for record in self:
            if record.invoice_id:
                record.amount_residual = record.invoice_id.amount_residual
                record.amount_paid = record.invoice_id.amount_total - record.invoice_id.amount_residual
            else:
                total_paid = sum(p.amount for p in record.payment_ids if p.payment_type == 'in')
                record.amount_paid = total_paid
                record.amount_residual = record.amount_total - total_paid

    @api.depends('amount_residual', 'amount_total')
    def _compute_state(self):
        for record in self:
            if record.amount_residual <= 0.0:
                record.state = 'paid'
            elif record.amount_residual < record.amount_total:
                record.state = 'partial'
            else:
                record.state = 'open'

    def unlink(self):
        for record in self:
            # Delete any pos orders that are related to this nasiya (to prevent orphan records)
            pos_orders = self.env['van.pos.order'].search([('nasiya_id', '=', record.id)])
            if pos_orders:
                pos_orders.unlink()
        return super().unlink()

    def action_register_payment(self, amount=None, payment_method=None):
        """ Used primarily by RPC from OWL or generic XML views """
        self.ensure_one()
        if not self.invoice_id:
            return False

        # In Odoo, account.payment is the main source of cash-in
        # For simplicity, we just jump to standard invoice wizard or do it directly
        return self.invoice_id.action_register_payment()
