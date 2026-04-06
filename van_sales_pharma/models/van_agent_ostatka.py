from odoo import models, fields, api

class VanAgentOstatka(models.Model):
    """
    Agentning boshlang'ich (oldingi) mahsulot qoldig'i (Ostatka) ro'yxati.
    Bu tizimga ulanishdan oldingi mavjud inventarni kiritish uchun ishlatiladi.
    """
    _name = 'van.agent.ostatka'
    _description = 'Agent Ostatka (Boshlang\'ich qoldiq)'

    agent_id = fields.Many2one('res.users', string='Agent', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('van.product', string='Mahsulot', required=True)
    
    qty = fields.Float(string='Miqdor', required=True, default=1.0)
    kelish_narxi = fields.Float(string='Kelish narxi (Cost)', related='product_id.cost_price', readonly=False, store=True)
    sotish_narxi = fields.Float(string='Sotish narxi', related='product_id.list_price', readonly=False, store=True)
    
    currency_id = fields.Many2one('res.currency', related='agent_id.company_id.currency_id')
    jami = fields.Monetary(string='Jami', currency_field='currency_id', compute='_compute_jami', store=True)

    @api.depends('qty', 'kelish_narxi')
    def _compute_jami(self):
        for rec in self:
            rec.jami = rec.qty * rec.kelish_narxi

    # Agar mahsulot tanlansa uning narxlarini olib kelish
    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.kelish_narxi = self.product_id.cost_price
            self.sotish_narxi = self.product_id.list_price

    def _sync_to_inventory_line(self, ostatka_records):
        """
        Ostatka kiritilganda yoki o'zgartirilganda Agent Hisobotida 
        (van.agent.inventory.line) ushbu mahsulot qatori borligiga ishonch hosil qilish.
        Yo'q bo'lsa, yaratadi. Bor bo'lsa hech nima qilmaydi, 
        chunki _compute_remaining Ostatkani avtomat hisoblaydi.
        """
        for rec in ostatka_records:
            summary = self.env['van.agent.summary'].search([
                ('agent_id', '=', rec.agent_id.id),
            ], limit=1)
            
            if not summary:
                summary = self.env['van.agent.summary'].create({'agent_id': rec.agent_id.id})
                
            inv_line = self.env['van.agent.inventory.line'].search([
                ('summary_id', '=', summary.id),
                ('product_id', '=', rec.product_id.id)
            ], limit=1)
            
            if not inv_line:
                self.env['van.agent.inventory.line'].create({
                    'summary_id': summary.id,
                    'product_id': rec.product_id.id,
                    'price_unit': rec.sotish_narxi,
                    'cost_price': rec.kelish_narxi,
                    'loaded_qty': 0.0, # Loaded qty is from trips, ostatka is computed on top
                })
            else:
                # Update price if it was 0 or just ensure it exists
                if not inv_line.price_unit and rec.sotish_narxi:
                    inv_line.price_unit = rec.sotish_narxi
                if not inv_line.cost_price and rec.kelish_narxi:
                    inv_line.cost_price = rec.kelish_narxi

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self._sync_to_inventory_line(records)
        return records

    def write(self, vals):
        res = super().write(vals)
        self._sync_to_inventory_line(self)
        return res
