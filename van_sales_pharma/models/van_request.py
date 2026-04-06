from odoo import models, fields, api, _

class VanRequest(models.Model):
    _name = 'van.request'
    _description = "Mijoz So'rovi"
    _order = 'date desc, id desc'

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True, index=True, default=lambda self: _('New'))
    agent_id = fields.Many2one('res.users', string='Agent', default=lambda self: self.env.user, required=True, readonly=True)
    partner_id = fields.Many2one('res.partner', string='Mijoz', required=True)
    line_ids = fields.One2many('van.request.line', 'request_id', string='Mahsulotlar')
    state = fields.Selection([
        ('draft', 'Yangi'),
        ('done', 'Bajarildi'),
        ('cancel', 'Bekor qilindi'),
    ], string='Holati', readonly=True, default='draft')
    date = fields.Datetime(string='Sana', default=fields.Datetime.now, required=True)
    notes = fields.Text(string='Izoh')
    
    total_amount = fields.Float(string='Jami Summa', compute='_compute_total', store=True)
    fulfilled_date = fields.Datetime(string='Bajarilgan Sana', readonly=True)
    sale_order_id = fields.Many2one('van.pos.order', string='Savdo', readonly=True)

    @api.depends('line_ids.subtotal')
    def _compute_total(self):
        for record in self:
            record.total_amount = sum(record.line_ids.mapped('subtotal'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('van.request') or _('New')
        return super(VanRequest, self).create(vals_list)

    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancel'})

    def action_draft(self):
        self.write({'state': 'draft'})
        
    def action_xarid(self):
        """Convert So'rov to sale (van.pos.order)"""
        self.ensure_one()
        
        if self.state != 'draft':
            raise models.ValidationError("Faqat 'Yangi' holatidagi so'rovlarni bajarish mumkin!")
        
        # Create sale order lines
        order_lines = []
        for line in self.line_ids:
            order_lines.append((0, 0, {
                'product_id': line.product_id.id,
                'qty': line.qty,
                'price_unit': line.price,
            }))
        
        # Create van.pos.order
        sale = self.env['van.pos.order'].create({
            'agent_id': self.agent_id.id,
            'partner_id': self.partner_id.id,
            'date': fields.Datetime.now(),
            'line_ids': order_lines,
            'note': f"So'rov {self.name} asosida yaratildi",
            'request_id': self.id
        })
        
        # Mark So'rov as fulfilled
        self.write({
            'state': 'done',
            'fulfilled_date': fields.Datetime.now(),
            'sale_order_id': sale.id
        })
        
        # Redirect to sale order
        return {
            'type': 'ir.actions.act_window',
            'name': 'Savdo',
            'res_model': 'van.pos.order',
            'res_id': sale.id,
            'view_mode': 'form',
            'target': 'current'
        }

class VanRequestLine(models.Model):
    _name = 'van.request.line'
    _description = "Mijoz So'rovi Mahsuloti"

    request_id = fields.Many2one('van.request', string="So'rov", required=True, ondelete='cascade')
    product_id = fields.Many2one('van.product', string='Mahsulot', required=True)
    qty = fields.Float(string='Soni', required=True, default=1.0)
    price = fields.Float(string='Narxi')
    subtotal = fields.Float(string='Summa', compute='_compute_subtotal', store=True)

    @api.depends('qty', 'price')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.qty * line.price
            
    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.price = self.product_id.list_price
