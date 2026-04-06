from odoo import models, api

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.model
    def _load_pos_data_domain(self, data, config):
        domain = super()._load_pos_data_domain(data, config)
        
        # If the user is an agent, restrict products based on their active van inventory
        agent_summary = self.env['van.agent.summary'].search([('agent_id', '=', self.env.user.id)], limit=1)
        if agent_summary:
            # Gather IDs of product templates that exist in active_inventory_line_ids
            # active_inventory_line_ids already filters for remaining_qty > 0 and type != service
            allowed_tmpl_ids = agent_summary.active_inventory_line_ids.mapped('product_id.product_tmpl_id').ids
            
            # Additional safety: maybe there are NO products loaded with > 0 qty. 
            # In that case, allowed_tmpl_ids is empty, and the domain must return nothing.
            # We append the constraint.
            domain.append(('id', 'in', allowed_tmpl_ids))
            
        return domain
