from odoo import api, fields, models, _


class PosConfig(models.Model):
    _inherit = 'pos.config'

    van_agent_id = fields.Many2one(
        'res.users',
        string='Van Agent',
        domain="[('share', '=', False)]",
        help="Standard POS will use this agent's van inventory and mirror paid sales into van.pos.order.",
    )

    @api.model
    def _ensure_kassa_user(self):
        login = 'kassa'
        agent_group = self.env.ref('van_sales_pharma.group_van_agent')
        pos_user_group = self.env.ref('point_of_sale.group_pos_user')
        company = self.env.company

        user = self.env['res.users'].with_context(active_test=False).search([
            ('login', '=', login),
        ], limit=1)
        if user:
            user.write({
                'company_id': company.id,
                'company_ids': [(4, company.id)],
                'group_ids': [
                    (4, agent_group.id),
                    (4, pos_user_group.id),
                ],
            })
            return user

        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Kassa',
            'login': login,
            'password': login,
            'company_id': company.id,
            'company_ids': [(6, 0, company.ids)],
            'group_ids': [
                (4, agent_group.id),
                (4, pos_user_group.id),
            ],
        })
        return user

    @api.model
    def action_ensure_default_kassa_config(self):
        company = self.env.company
        kassa_user = self._ensure_kassa_user()

        config = self.with_context(active_test=False).search([
            ('name', '=', 'Kassa'),
            ('company_id', '=', company.id),
        ], limit=1)

        values = {
            'van_agent_id': kassa_user.id,
        }

        if config:
            config.write(values)
            return config

        values.update({
            'name': 'Kassa',
            'company_id': company.id,
        })
        return self.create(values)
