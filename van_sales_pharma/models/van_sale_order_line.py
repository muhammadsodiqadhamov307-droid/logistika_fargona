import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

class VanSaleOrderLine(models.Model):
    _name = 'van.sale.order.line'
    _description = 'Agent Sotuvi Satrlari'

    order_id = fields.Many2one('van.sale.order', string='Sotuv', required=True, ondelete='cascade')
    company_id = fields.Many2one('res.company', related='order_id.company_id', store=True)
    currency_id = fields.Many2one('res.currency', related='order_id.currency_id', store=True)

    product_id = fields.Many2one('van.product', string='Mahsulot', required=True)
    qty = fields.Float(string='Miqdor', required=True, default=1.0)
    price_unit = fields.Float(string='Narx', required=True)
    
    subtotal = fields.Monetary(string='Mablag\'', compute='_compute_subtotal', store=True, currency_field='currency_id')

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            # Sayohatga yuklangan mahsulotlardan (trip_lines) narxini topish afzal,
            # Lekin tezlik uchun ro'yxatdan asosiy narxni tortamiz.
            self.price_unit = self.product_id.list_price

    @api.depends('qty', 'price_unit')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.qty * line.price_unit
