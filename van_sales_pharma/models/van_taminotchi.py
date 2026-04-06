# -*- coding: utf-8 -*-
import datetime

from odoo import models, fields, api

class VanTaminotchi(models.Model):
    _name = 'van.taminotchi'
    _description = 'Taminotchi (Supplier)'
    
    name = fields.Char(string='Taminotchi Ismi/Kompaniyasi', required=True)
    phone = fields.Char(string='Telefon Raqami')
    address = fields.Text(string='Manzili')
    ostatka_qarzi = fields.Monetary(string="Ostatka Qarzi", currency_field='currency_id', help="Tizim o'rnatilishidan oldingi qarz miqdori")
    
    # Financial fields
    balance = fields.Monetary(string="Joriy Balans", compute="_compute_balance", currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Valyuta', default=lambda self: self.env.company.currency_id)
    
    # Relations
    trip_ids = fields.One2many('van.trip', 'taminotchi_id', string="Mahsulot Yuklashlar")
    payment_ids = fields.One2many('van.payment', 'taminotchi_id', string="To'lovlar (Chiqim)")

    # Date filter fields for Hisob-kitob tab
    hk_date_from = fields.Date(string='Dan', store=True)
    hk_date_to = fields.Date(string='Gacha', store=True)

    # Hisob-kitob HTML ledger
    hisob_kitob_html = fields.Html(
        string="Hisob-kitob",
        compute='_compute_hisob_kitob_html',
        sanitize=False,
    )

    @api.depends('trip_ids.amount_cost_total', 'payment_ids.amount', 'payment_ids.state', 'ostatka_qarzi')
    def _compute_balance(self):
        for rec in self:
            total_debt = sum(trip.amount_cost_total for trip in rec.trip_ids if trip.state == 'validated')
            total_paid = sum(pay.amount for pay in rec.payment_ids if pay.state == 'received' and pay.payment_type == 'out')
            rec.balance = rec.ostatka_qarzi + total_debt - total_paid

    @api.depends('trip_ids', 'trip_ids.state', 'trip_ids.date', 'trip_ids.amount_cost_total',
                 'payment_ids', 'payment_ids.amount', 'payment_ids.date', 'payment_ids.state',
                 'ostatka_qarzi', 'hk_date_from', 'hk_date_to')
    def _compute_hisob_kitob_html(self):
        for rec in self:
            date_from = rec.hk_date_from
            date_to = rec.hk_date_to
            transactions = []

            # 1. Boshlang'ich qarz (Ostatka) — always shown, no date filter
            if rec.ostatka_qarzi and rec.ostatka_qarzi != 0:
                transactions.append({
                    'date': fields.Date.today(),
                    'display_date': fields.Date.today(),
                    'turi': "🟠 Boshlang'ich qarz",
                    'summa': rec.ostatka_qarzi,
                    'is_debt': True,
                })

            # 2. Yuklashlar (van.trip — validated only)
            for trip in rec.trip_ids:
                if trip.state != 'validated' or trip.amount_cost_total <= 0:
                    continue
                trip_display_date = self._ledger_display_datetime(trip.date)
                trip_date = self._ledger_sort_date(trip_display_date)
                if date_from and trip_date < date_from:
                    continue
                if date_to and trip_date > date_to:
                    continue
                transactions.append({
                    'date': trip_date,
                    'display_date': trip_display_date or trip_date,
                    'turi': "📦 Yuklash",
                    'summa': trip.amount_cost_total,
                    'is_debt': True,
                    'trip_id': trip.id,
                    'lines': trip.trip_line_ids,
                    'agent_name': trip.agent_id.name,
                })

            # 3. Chiqimlar (van.payment out to this taminotchi)
            for pay in rec.payment_ids:
                if pay.state != 'received' or pay.payment_type != 'out' or pay.amount <= 0:
                    continue
                pay_display_date = self._ledger_display_datetime(pay.date)
                pay_date = self._ledger_sort_date(pay_display_date)
                if date_from and pay_date < date_from:
                    continue
                if date_to and pay_date > date_to:
                    continue
                transactions.append({
                    'date': pay_date,
                    'display_date': pay_display_date or pay_date,
                    'turi': "💵 Chiqim",
                    'summa': pay.amount,
                    'is_debt': False,
                })

            # Sort ascending for running balance
            transactions.sort(key=lambda x: x['date'])

            running_balance = 0.0
            for rx in transactions:
                if rx['is_debt']:
                    running_balance += rx['summa']
                else:
                    running_balance -= rx['summa']
                rx['computed_balance'] = running_balance

            # Reverse so newest is on top
            transactions.reverse()

            final_color = 'text-danger' if running_balance > 0 else 'text-success'
            filter_info = ''
            if date_from or date_to:
                f_str = date_from.strftime('%d.%m.%Y') if date_from else '...'
                t_str = date_to.strftime('%d.%m.%Y') if date_to else '...'
                filter_info = f'<small class="text-muted ms-3">({f_str} — {t_str})</small>'

            html = f"""
            <div class="mb-3 d-flex justify-content-between align-items-center">
                <h4 class="{final_color} fw-bold m-0">Jami Qarz: {running_balance:,.0f} so'm{filter_info}</h4>
            </div>
            <div class="table-responsive">
                <table class="table table-sm table-hover table-striped mb-0" style="border: 1px solid #dee2e6;">
                    <thead class="table-light">
                        <tr>
                            <th>Sana</th>
                            <th>Agent</th>
                            <th>Turi</th>
                            <th class="text-end">Summa</th>
                            <th class="text-end">Balans</th>
                        </tr>
                    </thead>
            """

            if not transactions:
                html += """
                    <tbody>
                        <tr>
                            <td colspan="5" class="text-center text-muted py-3">Ma'lumot topilmadi</td>
                        </tr>
                    </tbody>
                """

            for rx in transactions:
                d_str = self._ledger_format_display_date(rx.get('display_date') or rx['date'])
                bal_color = 'text-danger fw-bold' if rx['computed_balance'] > 0 else 'text-success fw-bold'

                if rx['is_debt']:
                    sum_html = f'<span class="text-danger fw-bold">+{rx["summa"]:,.0f}</span>'
                    turi_badge = f'<span class="badge rounded-pill bg-danger">{rx["turi"]}</span>'
                else:
                    sum_html = f'<span class="text-success fw-bold">-{rx["summa"]:,.0f}</span>'
                    turi_badge = f'<span class="badge rounded-pill bg-success">{rx["turi"]}</span>'

                if rx.get('turi') == "🟠 Boshlang'ich qarz":
                    turi_badge = f'<span class="badge rounded-pill bg-warning text-dark">{rx["turi"]}</span>'

                if rx.get('trip_id'):
                    html += f"""
                    <tbody>
                        <tr class="yuklash-row" onclick="var d=document.getElementById('trip-{rx['trip_id']}');if(d){{var h=(d.style.display===''||d.style.display==='none');d.style.display=h?'table-row-group':'none';var a=this.querySelector('.fold-arrow');if(a)a.textContent=h?'▼':'▶';}}" style="cursor:pointer;">
                            <td><span class="fold-arrow text-primary me-2" style="display:inline-block;width:15px;text-align:center;">▶</span>{d_str}</td>
                            <td>{rx.get('agent_name', '-')}</td>
                            <td>{turi_badge}</td>
                            <td class="text-end">{sum_html}</td>
                            <td class="text-end {bal_color}">{rx['computed_balance']:,.0f}</td>
                        </tr>
                    </tbody>
                    <tbody id="trip-{rx['trip_id']}" style="display:none;background-color:#f8f9fa;">
                    """
                    for line in rx['lines']:
                        prod_name = line.product_id.name or 'Unknown'
                        qty = line.loaded_qty
                        cost = line.product_id.cost_price or 0.0
                        subtotal = qty * cost
                        html += f"""
                        <tr>
                            <td colspan="1" class="ps-4 text-muted border-0"><small>&#x2514;&#x2500; {prod_name}</small></td>
                            <td class="text-muted border-0"><small>&#xD7; {qty:g}</small></td>
                            <td class="text-end text-muted border-0"><small>{cost:,.0f} so'm</small></td>
                            <td class="text-end text-muted border-0"><small>{subtotal:,.0f} so'm</small></td>
                        </tr>
                        """
                    html += '</tbody>'
                else:
                    html += f"""
                    <tbody>
                        <tr>
                            <td class="ps-4">{d_str}</td>
                            <td>{rx.get('agent_name', '-')}</td>
                            <td>{turi_badge}</td>
                            <td class="text-end">{sum_html}</td>
                            <td class="text-end {bal_color}">{rx['computed_balance']:,.0f}</td>
                        </tr>
                    </tbody>
                    """

            html += """
                </table>
            </div>
            """
            rec.hisob_kitob_html = html

    @api.model
    def _ledger_sort_date(self, value):
        if not value:
            return fields.Date.today()
        if isinstance(value, str):
            try:
                value = fields.Datetime.to_datetime(value)
            except Exception:
                try:
                    value = fields.Date.to_date(value)
                except Exception:
                    return fields.Date.today()
        if hasattr(value, 'date'):
            try:
                return value.date()
            except Exception:
                pass
        return value

    @api.model
    def _ledger_display_datetime(self, value):
        if not value:
            return fields.Date.today()
        if isinstance(value, str):
            try:
                return fields.Datetime.to_datetime(value)
            except Exception:
                try:
                    return fields.Date.to_date(value)
                except Exception:
                    return fields.Date.today()
        return value

    @api.model
    def _ledger_format_display_date(self, value):
        if not value:
            return ''
        if isinstance(value, str):
            parsed = self._ledger_display_datetime(value)
            return self._ledger_format_display_date(parsed)
        if isinstance(value, datetime.datetime):
            return value.strftime('%d.%m.%Y %H:%M')
        if isinstance(value, datetime.date):
            return value.strftime('%d.%m.%Y')
        return str(value)

    def action_view_ledger(self):
        self.ensure_one()
        return {
            'name': 'Taminotchi Hisoboti',
            'type': 'ir.actions.act_window',
            'res_model': 'van.taminotchi.ledger.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_taminotchi_id': self.id},
        }

    def action_apply_hk_filter(self):
        return True

    def action_clear_hk_filter(self):
        for rec in self:
            rec.hk_date_from = False
            rec.hk_date_to = False
        return True
