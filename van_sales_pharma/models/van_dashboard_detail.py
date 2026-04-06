import logging
from odoo import models, fields, tools

_logger = logging.getLogger(__name__)

class VanDashboardDetail(models.Model):
    _name = 'van.dashboard.detail'
    _description = 'Moliya Paneli Tafsilotlari (Kirim / Chiqim / Savdo)'
    _auto = False
    _order = 'date desc, id desc'

    name = fields.Char('Hujjat Raqami', readonly=True)
    date = fields.Datetime('Sana', readonly=True)
    partner_id = fields.Many2one('res.partner', 'Mijoz_Obyekt', readonly=True)
    partner_name = fields.Char('Mijoz', readonly=True)
    agent_id = fields.Many2one('res.users', 'Agent', readonly=True)
    amount = fields.Float('Summa', readonly=True)
    payment_method = fields.Selection([
        ('cash', 'Naqt'),
        ('card', 'Karta'),
        ('nasiya', 'Nasiya')
    ], 'To\'lov Usuli', readonly=True)
    transaction_type = fields.Selection([
        ('sale', 'Savdo (POS)'),
        ('kirim', 'Kirim (+)'),
        ('chiqim', 'Chiqim (-)')
    ], 'Amaliyot Turi', readonly=True)
    note = fields.Text('Izoh', readonly=True)
    
    company_id = fields.Many2one('res.company', 'Korxona', readonly=True)
    currency_id = fields.Many2one('res.currency', 'Valyuta', readonly=True)
    
    res_id = fields.Integer('Resurs ID', readonly=True)
    res_model = fields.Char('Resurs Modeli', readonly=True)

    def action_open_record(self):
        """ Redirect to the actual record form view """
        self.ensure_one()
        if not self.res_id or not self.res_model:
            return False
            
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.res_model,
            'res_id': self.res_id,
            'view_mode': 'form',
            'target': 'current',
        }

    def unlink(self):
        """ Delete the actual underlying record (van.pos.order or van.payment) """
        for rec in self:
            if rec.res_model and rec.res_id:
                real_record = self.env[rec.res_model].browse(rec.res_id)
                if real_record.exists():
                    real_record.unlink()
        return True

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW van_dashboard_detail AS (
                -- 1. Mobile POS Sales
                SELECT 
                    po.id + 1000000 AS id, 
                    po.name AS name,
                    po.agent_id AS agent_id,
                    po.date AS date,
                    po.partner_id AS partner_id,
                    COALESCE((SELECT name FROM res_partner WHERE id = po.partner_id), 'Naqt savdo') AS partner_name,
                    po.amount_total AS amount,
                    po.payment_type AS payment_method,
                    'sale' AS transaction_type,
                    po.note AS note,
                    rc.id AS company_id,
                    rc.currency_id AS currency_id,
                    po.id AS res_id,
                    'van.pos.order' AS res_model
                FROM van_pos_order po
                JOIN res_users ru ON po.agent_id = ru.id
                JOIN res_company rc ON ru.company_id = rc.id
                WHERE po.state = 'done'

                UNION ALL

                -- 2. Van Payments (Kirim/Chiqim)
                SELECT 
                    vp.id + 2000000 AS id,
                    vp.name AS name,
                    vp.agent_id AS agent_id,
                    vp.date AS date,
                    vp.partner_id AS partner_id,
                    COALESCE((SELECT name FROM res_partner WHERE id = vp.partner_id), 'Naqt yig''im') AS partner_name,
                    vp.amount AS amount,
                    vp.payment_method AS payment_method,
                    CASE WHEN vp.payment_type = 'in' THEN 'kirim' ELSE 'chiqim' END AS transaction_type,
                    vp.note AS note,
                    vp.company_id AS company_id,
                    vp.currency_id AS currency_id,
                    vp.id AS res_id,
                    'van.payment' AS res_model
                FROM van_payment vp
            )
        """)
