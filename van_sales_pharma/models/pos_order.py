from odoo import fields, models, _
from odoo.exceptions import UserError


class PosOrder(models.Model):
    _inherit = 'pos.order'

    van_pos_order_id = fields.Many2one(
        'van.pos.order',
        string='Van Sales Mirror Order',
        readonly=True,
        copy=False,
        ondelete='set null',
    )

    def _get_van_agent(self):
        self.ensure_one()
        return self.session_id.config_id.van_agent_id

    def _get_van_product_map(self):
        self.ensure_one()
        products = self.lines.mapped('product_id')
        van_products = self.env['van.product'].search([
            ('product_product_id', 'in', products.ids),
        ])
        return {rec.product_product_id.id: rec for rec in van_products}

    def _validate_van_inventory(self):
        for order in self:
            agent = order._get_van_agent()
            if not agent:
                continue

            summary = self.env['van.agent.summary'].search([
                ('agent_id', '=', agent.id),
            ], limit=1)
            if not summary:
                raise UserError(_("Van agent '%s' uchun inventar hisoboti topilmadi.") % agent.name)

            van_product_map = order._get_van_product_map()
            qty_by_van_product = {}
            for line in order.lines:
                van_product = van_product_map.get(line.product_id.id)
                if not van_product:
                    raise UserError(_("POS mahsuloti '%s' van mahsulotiga bog'lanmagan.") % line.product_id.display_name)
                qty_by_van_product[van_product.id] = qty_by_van_product.get(van_product.id, 0.0) + line.qty

            for van_product_id, qty in qty_by_van_product.items():
                if qty <= 0:
                    continue
                inv_line = self.env['van.agent.inventory.line'].search([
                    ('summary_id', '=', summary.id),
                    ('product_id', '=', van_product_id),
                ], limit=1)
                if not inv_line:
                    raise UserError(_("Mahsulot inventarda topilmadi: %s") % self.env['van.product'].browse(van_product_id).display_name)
                if inv_line.remaining_qty < qty:
                    raise UserError(
                        _("'%s' uchun yetarli zaxira yo'q. Qoldiq: %s, So'ralgan: %s") % (
                            inv_line.product_id.display_name,
                            inv_line.remaining_qty,
                            qty,
                        )
                    )

    def _prepare_van_order_line_vals(self, pos_line, van_product):
        unit_price = pos_line.price_unit
        if pos_line.qty:
            subtotal_incl = getattr(pos_line, 'price_subtotal_incl', False)
            if subtotal_incl is not False:
                unit_price = subtotal_incl / pos_line.qty

        return (0, 0, {
            'product_id': van_product.id,
            'qty': pos_line.qty,
            'price_unit': unit_price,
            'original_price_unit': van_product.list_price,
        })

    def _sync_to_van_pos_order(self):
        for order in self:
            agent = order._get_van_agent()
            if not agent or order.state == 'cancel':
                continue

            van_product_map = order._get_van_product_map()
            line_commands = []
            for line in order.lines:
                van_product = van_product_map.get(line.product_id.id)
                if not van_product:
                    continue
                line_commands.append(order._prepare_van_order_line_vals(line, van_product))

            original_price_total = sum(
                (van_product_map.get(line.product_id.id).list_price if van_product_map.get(line.product_id.id) else 0.0) * line.qty
                for line in order.lines
            )

            vals = {
                'company_id': order.company_id.id,
                'agent_id': agent.id,
                'partner_id': order.partner_id.id or False,
                'date': order.date_order,
                'state': 'done',
                'sale_type': 'naqt',
                'source': 'native_pos',
                'native_pos_order_id': order.id,
                'note': f"Kassir oynasi: {order.name}",
                'line_ids': line_commands,
                'commission_amount': original_price_total * (agent.komissiya_foizi / 100.0),
            }

            if order.van_pos_order_id:
                order.van_pos_order_id.write({
                    **vals,
                    'line_ids': [(5, 0, 0)] + line_commands,
                })
            else:
                mirror = self.env['van.pos.order'].with_company(order.company_id).create(vals)
                order.van_pos_order_id = mirror.id

    def _process_saved_order(self, draft):
        if not draft:
            self._validate_van_inventory()

        result = super()._process_saved_order(draft)

        if not draft and self.state != 'cancel':
            self._sync_to_van_pos_order()

        return result
