from odoo import models, fields, api
from datetime import datetime, time
import pytz

class VanProduct(models.Model):
    _name = 'van.product'
    _description = 'Van Sales Product'
    _order = 'name'

    name = fields.Char(string='Mahsulot Nomi', required=True, translate=True)
    qty = fields.Float(string='Soni', default=0.0, help="Umumiy ombordagi soni")
    cost_price = fields.Float(string='Kelish Narxi', default=0.0)
    list_price = fields.Float(string='Sotish Narxi', default=0.0)
    image_1920 = fields.Image(string='Rasm')
    product_product_id = fields.Many2one(
        'product.product',
        string='Kassir POS Mahsuloti',
        copy=False,
        readonly=True,
        ondelete='set null',
        help="This standard Odoo POS product is auto-generated and kept in sync from the van product.",
    )
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Kassir POS Shabloni',
        related='product_product_id.product_tmpl_id',
        readonly=True,
        store=True,
    )

    # Optional fields for future use or metrics
    active = fields.Boolean(default=True, string='Faol')
    company_id = fields.Many2one('res.company', string='Korxona', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', store=True)

    sale_report_date_from = fields.Date(string='Sotuv Sana Dan')
    sale_report_date_to = fields.Date(string='Sotuv Sana Gacha')
    sale_report_agent_id = fields.Many2one('res.users', string='Sotuv Agenti')
    sale_report_partner_id = fields.Many2one('res.partner', string='Mijoz', domain=[('x_is_van_customer', '=', True)])
    sale_report_line_ids = fields.Many2many(
        'van.pos.order.line',
        compute='_compute_report_lines',
        string='Mahsulot Sotuv Hisoboti',
    )

    trip_report_date_from = fields.Date(string='Yuklash Sana Dan')
    trip_report_date_to = fields.Date(string='Yuklash Sana Gacha')
    trip_report_agent_id = fields.Many2one('res.users', string='Yuklash Agenti')
    trip_report_taminotchi_id = fields.Many2one('van.taminotchi', string='Taminotchi')
    trip_report_line_ids = fields.Many2many(
        'van.trip.line',
        compute='_compute_report_lines',
        string='Mahsulot Yuklash Hisoboti',
    )

    @api.depends(
        'sale_report_date_from', 'sale_report_date_to', 'sale_report_agent_id', 'sale_report_partner_id',
        'trip_report_date_from', 'trip_report_date_to', 'trip_report_agent_id', 'trip_report_taminotchi_id'
    )
    def _compute_report_lines(self):
        self._refresh_report_lines()

    @api.onchange(
        'sale_report_date_from', 'sale_report_date_to', 'sale_report_agent_id', 'sale_report_partner_id',
        'trip_report_date_from', 'trip_report_date_to', 'trip_report_agent_id', 'trip_report_taminotchi_id'
    )
    def _onchange_report_filters(self):
        self._refresh_report_lines()

    def _refresh_report_lines(self):
        user_tz = pytz.timezone(self.env.user.tz or self.env.context.get('tz') or 'UTC')
        for rec in self:
            order_domain = [('state', '=', 'done'), ('line_ids.product_id', '=', rec.id)]
            if rec.sale_report_agent_id:
                order_domain.append(('agent_id', '=', rec.sale_report_agent_id.id))
            if rec.sale_report_partner_id:
                order_domain.append(('partner_id', '=', rec.sale_report_partner_id.id))
            if rec.sale_report_date_from:
                utc_start = user_tz.localize(datetime.combine(rec.sale_report_date_from, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
                order_domain.append(('date', '>=', utc_start))
            if rec.sale_report_date_to:
                utc_end = user_tz.localize(datetime.combine(rec.sale_report_date_to, time.max)).astimezone(pytz.UTC).replace(tzinfo=None)
                order_domain.append(('date', '<=', utc_end))

            trip_domain = [('state', '=', 'done'), ('trip_line_ids.product_id', '=', rec.id)]
            if rec.trip_report_agent_id:
                trip_domain.append(('agent_id', '=', rec.trip_report_agent_id.id))
            if rec.trip_report_taminotchi_id:
                trip_domain.append(('taminotchi_id', '=', rec.trip_report_taminotchi_id.id))
            if rec.trip_report_date_from:
                utc_start = user_tz.localize(datetime.combine(rec.trip_report_date_from, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
                trip_domain.append(('date', '>=', utc_start))
            if rec.trip_report_date_to:
                utc_end = user_tz.localize(datetime.combine(rec.trip_report_date_to, time.max)).astimezone(pytz.UTC).replace(tzinfo=None)
                trip_domain.append(('date', '<=', utc_end))

            sale_lines = self.env['van.pos.order.line']
            sale_orders = self.env['van.pos.order'].search(order_domain, order='date desc, id desc')
            for order in sale_orders:
                sale_lines |= order.line_ids.filtered(lambda line: line.product_id.id == rec.id)

            trip_lines = self.env['van.trip.line']
            trips = self.env['van.trip'].search(trip_domain, order='date desc, id desc')
            for trip in trips:
                trip_lines |= trip.trip_line_ids.filtered(lambda line: line.product_id.id == rec.id)

            rec.sale_report_line_ids = [(6, 0, sale_lines.ids)]
            rec.trip_report_line_ids = [(6, 0, trip_lines.ids)]

    def _prepare_pos_template_vals(self):
        self.ensure_one()
        vals = {
            'name': self.name,
            'list_price': self.list_price,
            'standard_price': self.cost_price,
            'active': self.active,
            'sale_ok': True,
            'purchase_ok': False,
            'company_id': self.company_id.id or False,
            'image_1920': self.image_1920,
        }
        template_model = self.env['product.template']
        if 'available_in_pos' in template_model._fields:
            vals['available_in_pos'] = True
        if 'type' in template_model._fields:
            vals['type'] = 'consu'
        return vals

    def _sync_pos_product(self):
        for rec in self:
            if rec.product_product_id and not rec.product_product_id.exists():
                rec.product_product_id = False

            if rec.product_product_id:
                rec.product_product_id.product_tmpl_id.write(rec._prepare_pos_template_vals())
                continue

            template = self.env['product.template'].create(rec._prepare_pos_template_vals())
            rec.product_product_id = template.product_variant_id.id

    @api.model
    def action_sync_all_pos_products(self):
        self.search([])._sync_pos_product()
        return True

    def action_clear_sale_report_filters(self):
        for rec in self:
            rec.sale_report_date_from = False
            rec.sale_report_date_to = False
            rec.sale_report_agent_id = False
            rec.sale_report_partner_id = False
        self._refresh_report_lines()
        return True

    def action_apply_sale_report_filters(self):
        self._refresh_report_lines()
        return True

    def action_clear_trip_report_filters(self):
        for rec in self:
            rec.trip_report_date_from = False
            rec.trip_report_date_to = False
            rec.trip_report_agent_id = False
            rec.trip_report_taminotchi_id = False
        self._refresh_report_lines()
        return True

    def action_apply_trip_report_filters(self):
        self._refresh_report_lines()
        return True

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_pos_product()
        return records

    def write(self, vals):
        res = super().write(vals)
        if any(key in vals for key in ['name', 'list_price', 'cost_price', 'image_1920', 'active', 'company_id']):
            self._sync_pos_product()
        return res
