from odoo import api, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.model
    def _get_van_agent_from_pos_config(self, config):
        if config and getattr(config, 'van_agent_id', False):
            return config.van_agent_id

        session = config.current_session_id if config else False
        cashier = session.user_id if session else self.env.user
        return cashier

    @api.model
    def _get_van_inventory_lines_for_pos(self, config):
        agent = self._get_van_agent_from_pos_config(config)
        if not agent:
            return self.env['van.agent.inventory.line']

        summary = self.env['van.agent.summary'].search([
            ('agent_id', '=', agent.id),
        ], limit=1)
        return summary.inventory_line_ids.filtered(lambda l: l.remaining_qty > 0) if summary else self.env['van.agent.inventory.line']

    @api.model
    def _load_pos_data_domain(self, data, config):
        inventory_lines = self._get_van_inventory_lines_for_pos(config)
        allowed_tmpl_ids = inventory_lines.mapped('product_id.product_tmpl_id').ids
        if not allowed_tmpl_ids:
            return [('id', 'in', [])]

        return [
            ('sale_ok', '=', True),
            ('company_id', 'in', [self.env.company.id, False]),
            ('id', 'in', allowed_tmpl_ids),
        ]

    def get_product_info_pos(self, price, quantity, pos_config_id, product_variant_id=False):
        res = super().get_product_info_pos(price, quantity, pos_config_id, product_variant_id)

        config = self.env['pos.config'].browse(pos_config_id)
        agent = self._get_van_agent_from_pos_config(config)
        inventory_lines = self._get_van_inventory_lines_for_pos(config).filtered(
            lambda l: l.product_id.product_tmpl_id.id == self.id
        )
        remaining = sum(inventory_lines.mapped('remaining_qty'))

        if agent:
            res['warehouses'] = [{
                'id': 99999,
                'name': f"{agent.name} - Mashina Ombori",
                'available_quantity': remaining,
                'free_qty': remaining,
                'forecasted_quantity': remaining,
                'uom': self.uom_name,
            }]
        return res


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model
    def _load_pos_data_domain(self, data, config):
        inventory_lines = self.env['product.template']._get_van_inventory_lines_for_pos(config)
        allowed_product_ids = inventory_lines.mapped('product_id.product_product_id').ids
        if not allowed_product_ids:
            return [('id', 'in', [])]

        return [
            ('sale_ok', '=', True),
            ('company_id', 'in', [self.env.company.id, False]),
            ('id', 'in', allowed_product_ids),
        ]

