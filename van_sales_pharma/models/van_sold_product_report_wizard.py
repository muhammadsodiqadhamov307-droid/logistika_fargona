from datetime import datetime, time

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class VanSoldProductReportWizard(models.TransientModel):
    _name = 'van.sold.product.report.wizard'
    _description = 'Sotilgan Tovarlar Hisoboti Wizard'

    date_from = fields.Date(
        string='Boshlanish Sana',
        required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1),
    )
    date_to = fields.Date(
        string='Tugash Sana',
        required=True,
        default=fields.Date.context_today,
    )
    line_ids = fields.One2many(
        'van.sold.product.report.wizard.line',
        'wizard_id',
        string='Hisobot Qatorlari',
    )
    total_qty = fields.Float(string='Jami Miqdor', compute='_compute_totals')
    total_standard_amount = fields.Monetary(string='Jami Sotish Narxida', compute='_compute_totals', currency_field='currency_id')
    total_cost_amount = fields.Monetary(string='Jami Tannarx', compute='_compute_totals', currency_field='currency_id')
    total_margin_amount = fields.Monetary(string='Jami Margin', compute='_compute_totals', currency_field='currency_id')
    total_actual_amount = fields.Monetary(string='Jami Amaldagi Sotuv', compute='_compute_totals', currency_field='currency_id')
    total_actual_margin_amount = fields.Monetary(string='Jami Amaldagi Margin', compute='_compute_totals', currency_field='currency_id')
    total_discount_amount = fields.Monetary(string='Jami Chegirma', compute='_compute_totals', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)

    @api.depends(
        'line_ids.qty',
        'line_ids.standard_amount',
        'line_ids.cost_amount',
        'line_ids.margin_amount',
        'line_ids.actual_amount',
        'line_ids.actual_margin_amount',
        'line_ids.discount_amount',
    )
    def _compute_totals(self):
        for wizard in self:
            wizard.total_qty = sum(wizard.line_ids.mapped('qty'))
            wizard.total_standard_amount = sum(wizard.line_ids.mapped('standard_amount'))
            wizard.total_cost_amount = sum(wizard.line_ids.mapped('cost_amount'))
            wizard.total_margin_amount = sum(wizard.line_ids.mapped('margin_amount'))
            wizard.total_actual_amount = sum(wizard.line_ids.mapped('actual_amount'))
            wizard.total_actual_margin_amount = sum(wizard.line_ids.mapped('actual_margin_amount'))
            wizard.total_discount_amount = sum(wizard.line_ids.mapped('discount_amount'))

    def action_generate_report(self):
        self.ensure_one()

        if self.date_from > self.date_to:
            raise UserError(_("Boshlanish sanasi tugash sanasidan katta bo'lishi mumkin emas."))

        user_tz = pytz.timezone(self.env.user.tz or self.env.context.get('tz') or 'UTC')
        utc_start = user_tz.localize(datetime.combine(self.date_from, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
        utc_end = user_tz.localize(datetime.combine(self.date_to, time.max)).astimezone(pytz.UTC).replace(tzinfo=None)

        pos_lines = self.env['van.pos.order.line'].search([
            ('order_id.state', '=', 'done'),
            ('order_id.date', '>=', utc_start),
            ('order_id.date', '<=', utc_end),
        ], order='product_id')

        aggregated = {}
        for line in pos_lines:
            product = line.product_id
            if not product:
                continue

            bucket = aggregated.setdefault(product.id, {
                'product_id': product.id,
                'qty': 0.0,
                'standard_amount': 0.0,
                'cost_amount': 0.0,
                'margin_amount': 0.0,
                'actual_amount': 0.0,
                'actual_margin_amount': 0.0,
                'discount_amount': 0.0,
            })

            standard_price = line.original_price_unit or product.list_price or line.price_unit
            standard_amount = line.standard_subtotal or (standard_price * line.qty)
            cost_amount = (line.cost_price or product.cost_price or 0.0) * line.qty
            actual_amount = line.subtotal
            discount_amount = line.discount_amount or max(standard_amount - actual_amount, 0.0)
            margin_amount = standard_amount - cost_amount
            actual_margin_amount = actual_amount - cost_amount

            bucket['qty'] += line.qty
            bucket['standard_amount'] += standard_amount
            bucket['cost_amount'] += cost_amount
            bucket['margin_amount'] += margin_amount
            bucket['actual_amount'] += actual_amount
            bucket['actual_margin_amount'] += actual_margin_amount
            bucket['discount_amount'] += discount_amount

        if not aggregated:
            raise UserError(_("Tanlangan davrda sotilgan mahsulot topilmadi."))

        line_commands = []
        for product_id in sorted(aggregated, key=lambda pid: self.env['van.product'].browse(pid).name or ''):
            values = aggregated[product_id]
            line_commands.append((0, 0, values))

        self.write({
            'line_ids': [(5, 0, 0)] + line_commands,
        })

        return {
            'type': 'ir.actions.act_window',
            'name': _('Sotilgan Tovarlar Hisoboti'),
            'res_model': 'van.sold.product.report.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
        }

    def action_clear_report(self):
        self.ensure_one()
        self.write({'line_ids': [(5, 0, 0)]})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sotilgan Tovarlar Hisoboti'),
            'res_model': 'van.sold.product.report.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
        }


class VanSoldProductReportWizardLine(models.TransientModel):
    _name = 'van.sold.product.report.wizard.line'
    _description = 'Sotilgan Tovarlar Hisoboti Qatori'
    _order = 'product_id'

    wizard_id = fields.Many2one('van.sold.product.report.wizard', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='wizard_id.currency_id', store=True)
    product_id = fields.Many2one('van.product', string='Mahsulot', required=True, readonly=True)
    qty = fields.Float(string='Miqdor', readonly=True)
    standard_amount = fields.Monetary(string='Summasi (Sotish Narxda)', currency_field='currency_id', readonly=True)
    cost_amount = fields.Monetary(string='Tannarx', currency_field='currency_id', readonly=True)
    margin_amount = fields.Monetary(string='Farq / Margin', currency_field='currency_id', readonly=True)
    actual_amount = fields.Monetary(string='Amaldagi Sotuv Summasi', currency_field='currency_id', readonly=True)
    actual_margin_amount = fields.Monetary(string='Amaldagi Margin', currency_field='currency_id', readonly=True)
    discount_amount = fields.Monetary(string='Chegirma', currency_field='currency_id', readonly=True)
