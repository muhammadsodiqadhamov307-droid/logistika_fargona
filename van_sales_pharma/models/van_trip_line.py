import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

class VanTripLine(models.Model):
    _name = 'van.trip.line'
    _description = 'Kun Sayohati Mahsulotlari'
    _order = 'id desc'

    trip_id = fields.Many2one('van.trip', string='Sayohat', required=True, ondelete='cascade')
    company_id = fields.Many2one('res.company', related='trip_id.company_id', store=True)
    currency_id = fields.Many2one('res.currency', related='trip_id.currency_id', store=True)
    trip_date = fields.Datetime(related='trip_id.date', string='Sana', readonly=True)
    trip_agent_id = fields.Many2one('res.users', related='trip_id.agent_id', string='Agent', readonly=True)
    trip_taminotchi_id = fields.Many2one('van.taminotchi', related='trip_id.taminotchi_id', string='Taminotchi', readonly=True)

    product_id = fields.Many2one('van.product', string='Mahsulot', required=True)
    price_unit = fields.Float(string='Kelish Narxi', required=True)
    sale_price_unit = fields.Float(string='Sotish Narxi', required=True)

    loaded_qty = fields.Float(string='Yuklangan Miqdor', default=0.0, required=True)
    uom_id = fields.Many2one('uom.uom', string='O‘lchov Birligi')

    price_subtotal = fields.Monetary(string='Summasi', compute='_compute_subtotal', currency_field='currency_id', store=True)

    @api.depends('loaded_qty', 'price_unit')
    def _compute_subtotal(self):
        for line in self:
            line.price_subtotal = line.loaded_qty * line.price_unit

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.price_unit = self.product_id.cost_price
            self.sale_price_unit = self.product_id.list_price
