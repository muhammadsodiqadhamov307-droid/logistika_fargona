# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import datetime
import pytz

class VanTaminotchiLedgerWizard(models.TransientModel):
    _name = 'van.taminotchi.ledger.wizard'
    _description = 'Taminotchi Hisoboti Wizard'

    taminotchi_id = fields.Many2one('van.taminotchi', string="Taminotchi", required=True)
    date_from = fields.Date(string="Sana dan", required=True, default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(string="Sana gacha", required=True, default=fields.Date.context_today)
    report_html = fields.Html(string="Hisobot", sanitize=False, readonly=True)

    def action_generate_report(self):
        self.ensure_one()
        
        taminotchi = self.taminotchi_id
        date_from = self.date_from
        date_to = self.date_to
        
        # 1. Calculate Initial Balance Setup (Before date_from)
        
        # 1a. Historical Trips (Increases Debt to Supplier)
        past_trips = self.env['van.trip'].search([
            ('taminotchi_id', '=', taminotchi.id),
            ('state', '=', 'validated'),
            ('date', '<', str(date_from))
        ])
        past_debt = sum(t.amount_cost_total for t in past_trips)
        
        # 1b. Historical Payments (Decreases Debt to Supplier)
        past_payments = self.env['van.payment'].search([
            ('taminotchi_id', '=', taminotchi.id),
            ('state', '=', 'received'),
            ('payment_type', '=', 'out'),
            ('date', '<', date_from)
        ])
        past_paid = sum(p.amount for p in past_payments)
        
        # Initial Balance (Positive means we owe them, including opening debt)
        opening_balance = taminotchi.ostatka_qarzi + past_debt - past_paid

        # 2. Fetch Records within Range
        lines = []
        
        # Range Trips (As Debit/Debt Increase)
        range_trips = self.env['van.trip'].search([
            ('taminotchi_id', '=', taminotchi.id),
            ('state', '=', 'validated'),
            ('date', '>=', str(date_from)),
            ('date', '<=', str(date_to))
        ])
        for trip in range_trips:
            product_details = []
            for line in trip.trip_line_ids:
                cost = line.product_id.cost_price or 0.0
                product_details.append({
                    'name': line.product_id.name,
                    'qty': line.loaded_qty,
                    'cost_price': cost,
                    'subtotal': line.loaded_qty * cost
                })
            lines.append({
                'date': datetime.datetime.combine(trip.date, datetime.datetime.min.time()),
                'ref': trip.name,
                'agent': trip.agent_id.name,
                'type': 'Mahsulot yuklash',
                'debit': trip.amount_cost_total,  # We owe them this much
                'credit': 0.0,
                'is_foldable': True,
                'products': product_details
            })
            
        # Payments in range (Credit/Paid to them)
        range_payments = self.env['van.payment'].search([
            ('taminotchi_id', '=', taminotchi.id),
            ('state', '=', 'received'),
            ('payment_type', '=', 'out'),
            ('date', '>=', date_from),
            ('date', '<=', date_to)
        ])
        for pay in range_payments:
            lines.append({
                'date': pay.date,
                'ref': pay.name or 'To\'lov',
                'type': 'To\'lov',
                'debit': 0.0,
                'credit': pay.amount,
                'is_foldable': False,
            })
            
        # 3. Sort chronologically
        def normalize_date(d):
            if isinstance(d, datetime.datetime):
                return d
            return datetime.datetime.combine(d, datetime.time())
            
        lines.sort(key=lambda x: normalize_date(x['date']))
        
        # 4. Generate HTML
        html = f"""
        <style>
            .ledger-table {{ width: 100%; table-layout: fixed; border-collapse: collapse; margin-top: 15px; font-family: -apple-system, sans-serif; }}
            .ledger-table th {{ background-color: #f1f5f9; color: #334155; padding: 12px 8px; text-align: left; font-size: 13px; text-transform: uppercase; border-bottom: 2px solid #cbd5e1; }}
            .ledger-table td {{ padding: 10px 8px; border-bottom: 1px solid #e2e8f0; font-size: 14px; vertical-align: middle; }}
            .ledger-row:hover {{ background-color: #f8fafc; }}
            
            .col-date {{ white-space: nowrap; width: 15%; }}
            .col-num {{ text-align: right; white-space: nowrap; width: 17%; }}
            .text-success {{ color: #16a34a; font-weight: bold; }}
            .text-danger {{ color: #dc2626; font-weight: bold; }}
            
            summary {{ outline: none; cursor: pointer; list-style: none; font-weight: 600; color: #0f172a; width: 100%; box-sizing: border-box; display: block; }}
            summary::-webkit-details-marker {{ display: none; }}
            .summary-content {{ display: flex; align-items: center; width: 100%; }}
            .summary-icon {{ font-size: 10px; color: #94a3b8; margin-right: 6px; transition: transform 0.2s; display: inline-block; }}
            details[open] summary .summary-icon {{ transform: rotate(90deg); }}
            details summary:hover {{ background-color: #f8fafc; }}
            
            .drilled-down-table {{ width: 95%; margin: 10px auto; background-color: #f8fafc; border-radius: 6px; box-shadow: inset 0 1px 3px rgba(0,0,0,0.05); border: 1px solid #e2e8f0; border-collapse: collapse; }}
            .drilled-down-table td, .drilled-down-table th {{ padding: 8px 12px; font-size: 13px; border-bottom: 1px dashed #cbd5e1; text-align: left; }}
            .drilled-down-table tr:last-child td {{ border-bottom: none; }}
            .drilled-down-table th {{ color: #64748b; font-weight: normal; text-transform: uppercase; font-size: 11px; }}
            .badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 12px; text-align: center; white-space: nowrap; }}
        </style>
        
        <div style="background: white; padding: 20px; border-radius: 8px; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
            <div style="display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 20px; padding-bottom: 15px; border-bottom: 1px solid #e2e8f0;">
                <div>
                    <h2 style="margin: 0; color: #0f172a; font-size: 20px;">{taminotchi.name} - Hisob-kitob Daftari</h2>
                    <p style="margin: 5px 0 0 0; color: #64748b; font-size: 14px;"><strong>Davr:</strong> {date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}</p>
                </div>
            </div>
            
            <table class="ledger-table">
                <thead>
                    <tr>
                        <th class="col-date" style="width: 15%;">Sana</th>
                        <th style="width: 20%;">Hujjat</th>
                        <th style="width: 15%;">Agent (Kimga)</th>
                        <th style="width: 12%; text-align: center;">Turi</th>
                        <th class="col-num" style="width: 12%;">Qarz / Yuk(+)</th>
                        <th class="col-num" style="width: 12%;">To'lov (-)</th>
                        <th class="col-num" style="width: 14%;">Qoldiq Balans</th>
                    </tr>
                </thead>
                <tbody>
                    <!-- Opening Balance Row -->
                    <tr style="background-color: #f8fafc; font-weight: bold; border-bottom: 2px solid #cbd5e1;">
                        <td class="col-date">{date_from.strftime('%d.%m.%Y')}</td>
                        <td style="word-wrap: break-word;">Davr Boshidagi Qoldiq</td>
                        <td>-</td>
                        <td style="text-align: center;">-</td>
                        <td class="col-num">-</td>
                        <td class="col-num">-</td>
                        <td class="col-num {'text-danger' if opening_balance > 0 else 'text-success'}">{opening_balance:,.0f} so'm</td>
                    </tr>
        """
        
        current_balance = opening_balance
        user_tz = pytz.timezone(self.env.user.tz or 'Asia/Tashkent')
        
        for line in lines:
            current_balance = current_balance + line['debit'] - line['credit']
            
            if isinstance(line['date'], datetime.datetime):
                local_dt = pytz.utc.localize(line['date']).astimezone(user_tz)
                date_str = local_dt.strftime('%d.%m.%Y %H:%M')
            else:
                date_str = line['date'].strftime('%d.%m.%Y')
                
            debit_str = f"{line['debit']:,.0f}" if line['debit'] else ""
            credit_str = f"{line['credit']:,.0f}" if line['credit'] else ""
            balance_str = f"{current_balance:,.0f}"
            balance_class = "text-danger" if current_balance > 0 else "text-success" if current_balance < 0 else ""
            
            if line['is_foldable'] and line.get('products'):
                html += f"""
                    <tr class="ledger-row" style="border-bottom: 1px solid #e2e8f0;">
                        <td colspan="6" style="padding: 0;">
                            <details>
                                <summary style="padding: 10px 8px;">
                                    <div class="summary-content">
                                        <div style="width: 15%; white-space: nowrap;"><span class="summary-icon">▶</span> {date_str}</div>
                                        <div style="width: 20%; word-wrap: break-word; padding: 0 8px;">{line['ref']}</div>
                                        <div style="width: 15%; padding: 0 8px;">{line.get('agent', '-')}</div>
                                        <div style="width: 12%; text-align: center;"><span class="badge" style="background:#fee2e2; color:#b91c1c;">{line['type']}</span></div>
                                        <div style="width: 12%; padding: 0 8px;" class="col-num text-danger">{debit_str}</div>
                                        <div style="width: 12%; padding: 0 8px;" class="col-num text-success">{credit_str}</div>
                                        <div style="width: 14%; padding: 0 8px;" class="col-num {balance_class}">{balance_str}</div>
                                    </div>
                                </summary>
                                <div style="padding: 0 10px 10px 10px;">
                                    <table class="drilled-down-table">
                                        <thead>
                                            <tr>
                                                <th style="width: 45%;">Mahsulot Nomi</th>
                                                <th style="width: 20%; text-align: right;">Miqdor</th>
                                                <th style="width: 15%; text-align: right;">Kelish Narxi</th>
                                                <th style="width: 20%; text-align: right;">Jami</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                """
                for p in line['products']:
                    html += f"""
                                            <tr>
                                                <td><b>{p['name']}</b></td>
                                                <td style="text-align: right;">{p['qty']}</td>
                                                <td style="text-align: right; color: #64748b;">{p['cost_price']:,.0f}</td>
                                                <td style="text-align: right;"><b>{p['subtotal']:,.0f} so'm</b></td>
                                            </tr>
                    """
                html += """
                                        </tbody>
                                    </table>
                                </div>
                            </details>
                        </td>
                    </tr>
                """
            else:
                html += f"""
                    <tr class="ledger-row">
                        <td class="col-date">{date_str}</td>
                        <td style="word-wrap: break-word;">{line['ref']}</td>
                        <td>{line.get('agent', '-')}</td>
                        <td style="text-align: center;"><span class="badge" style="background:#dcfce7; color:#166534;">{line['type']}</span></td>
                        <td class="col-num text-danger">{debit_str}</td>
                        <td class="col-num text-success">{credit_str}</td>
                        <td class="col-num {balance_class}">{balance_str}</td>
                    </tr>
                """
        
        final_balance_class = "text-danger" if current_balance > 0 else "text-success" if current_balance < 0 else ""
        html += f"""
                    <tr style="background-color: #f8fafc; border-top: 2px solid #cbd5e1; font-weight: bold;">
                        <td class="col-date">{date_to.strftime('%d.%m.%Y')}</td>
                        <td style="word-wrap: break-word;">Davr Oxiridagi Qoldiq</td>
                        <td>-</td>
                        <td style="text-align: center;">-</td>
                        <td class="col-num">-</td>
                        <td class="col-num">-</td>
                        <td class="col-num {final_balance_class}">{current_balance:,.0f} so'm</td>
                    </tr>
                </tbody>
            </table>
        </div>
        """
        
        self.report_html = html
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'van.taminotchi.ledger.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }
