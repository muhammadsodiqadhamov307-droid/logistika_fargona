# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class VanSalaryPayout(models.Model):
    _name = 'van.salary.payout'
    _description = 'Agent Oylik To\'lovi'
    _order = 'date desc, id desc'

    agent_id = fields.Many2one('res.users', string='Agent', required=True, ondelete='cascade')
    date = fields.Date(string='Sana', default=fields.Date.context_today, required=True)
    summa = fields.Monetary(string='Summa', required=True, currency_field='currency_id')
    notes = fields.Text(string='Izoh')
    admin_id = fields.Many2one('res.users', string='Kim tomonidan', default=lambda self: self.env.user, readonly=True)
    currency_id = fields.Many2one('res.currency', string='Valyuta', default=lambda self: self.env.company.currency_id)
    chiqim_id = fields.Many2one('van.payment', string='Bog\'langan To\'lov', ondelete='cascade')

    def unlink(self):
        for record in self:
            # 1. Delete the linked Chiqimlar record
            # Deleting the payment will automatically trigger the compute field update for oylik_balansi
            if record.chiqim_id:
                record.chiqim_id.unlink()
        return super(VanSalaryPayout, self).unlink()

    def action_delete_payout(self):
        self.ensure_one()
        return self.unlink()

class VanSalaryPayoutWizard(models.TransientModel):
    _name = 'van.salary.payout.wizard'
    _description = 'Oylik Yopish Wizard'

    agent_id = fields.Many2one('res.users', string='Agent', required=True)
    amount = fields.Monetary(string='To\'lanadigan Summa', currency_field='currency_id', readonly=True)
    notes = fields.Text(string='Izoh')
    currency_id = fields.Many2one('res.currency', string='Valyuta', related='agent_id.x_currency_id')

    def action_confirm_payout(self):
        self.ensure_one()
        if self.amount <= 0:
            return

        # 1. Create Payout Record (for history table in Oyliklar menu)
        payout = self.env['van.salary.payout'].create({
            'agent_id': self.agent_id.id,
            'summa': self.amount,
            'notes': self.notes,
            'date': fields.Date.context_today(self),
            'admin_id': self.env.user.id,
        })

        # 2. Create Payment Record (to decrease 'Naqt pul' and show in Chiqimlar)
        payment_vals = {
            'agent_id': self.agent_id.id,
            'payment_type': 'out',
            'expense_type': 'payout',
            'amount': self.amount,
            'payment_method': 'cash',
            'date': fields.Datetime.now(),
            'note': f"Oylik To'lovi (Yopish): {self.notes or ''}"
        }
        payment = self.env['van.payment'].create(payment_vals)
        
        # 3. Link Payment to Payout
        payout.write({'chiqim_id': payment.id})
        
        return {'type': 'ir.actions.act_window_close'}
