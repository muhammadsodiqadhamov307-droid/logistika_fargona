# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import datetime

class VanLedgerReportWizard(models.TransientModel):
    _name = 'van.ledger.report.wizard'
    _description = 'Mijozlar Hisoboti Wizard'

    partner_id = fields.Many2one('res.partner', string="Mijoz (Partner)", required=True, domain=[('x_is_van_customer', '=', True)])
    date_from = fields.Date(string="Sana dan", required=True, default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(string="Sana gacha", required=True, default=fields.Date.context_today)
    report_html = fields.Html(string="Hisobot", sanitize=False, readonly=True)

    def action_generate_report(self):
        self.ensure_one()
        
        partner = self.partner_id
        date_from = self.date_from
        date_to = self.date_to
        
        # 0. Find Nasiyas created by POS Orders (to exclude them from Nasiya sums)
        all_pos_orders = self.env['van.pos.order'].search([
            ('partner_id', '=', partner.id),
            ('state', '=', 'done')
        ])
        excluded_nasiya_ids = all_pos_orders.mapped('nasiya_id').ids

        # 1. Calculate Initial Balance Setup (Before date_from)
        # 1a. ALL Ostatka Qarzi (Opening Debts) - Regardless of date
        ostatkas = self.env['van.ostatka.qarzi'].search([('partner_id', '=', partner.id)])
        total_ostatka = sum(o.amount for o in ostatkas)
        
        # 1b. Historical POS Orders (Debit/Qarz for Client)
        past_pos_orders = self.env['van.pos.order'].search([
            ('partner_id', '=', partner.id),
            ('state', '=', 'done'),
            ('date', '<', str(date_from))
        ])
        past_sales = sum(o.amount_total for o in past_pos_orders)
        
        # 1c. Nasiya historically (already converted to payments if paid or outstanding). 
        # Using the same Nasiya logic as partner:
        domain_past_nasiyas = [('partner_id', '=', partner.id), ('date', '<', date_from)]
        if excluded_nasiya_ids:
            domain_past_nasiyas.append(('id', 'not in', excluded_nasiya_ids))
        past_nasiyas = self.env['van.nasiya'].search(domain_past_nasiyas)
        past_nasiya_total = sum(n.amount_total for n in past_nasiyas)
        
        # 1d. Historical Payments (Credit/To'lov for Client)
        past_payments = self.env['van.payment'].search([
            ('partner_id', '=', partner.id),
            ('date', '<', date_from),
            ('state', '=', 'received')
        ])
        past_kirim = sum(p.amount for p in past_payments if p.payment_type == 'in')
        past_chiqim = sum(p.amount for p in past_payments if p.payment_type == 'out')
        
        # Initial Balance (Positive means the client owes us - Qarz)
        # Balans = (Ostatka + Past Sales + Past Nasiyas + Past Chiqim) - Past Kirim
        opening_balance = total_ostatka + past_sales + past_nasiya_total + past_chiqim - past_kirim

        # 2. Fetch Records within Range
        lines = []
        
        # Ostatka is completely removed from range lines since it's all in opening balance
            
        # Nasiya in range (As debt/Debit)
        domain_range_nasiyas = [
            ('partner_id', '=', partner.id),
            ('date', '>=', date_from),
            ('date', '<=', date_to)
        ]
        if excluded_nasiya_ids:
            domain_range_nasiyas.append(('id', 'not in', excluded_nasiya_ids))
        range_nasiyas = self.env['van.nasiya'].search(domain_range_nasiyas)
        for n in range_nasiyas:
            lines.append({
                'date': n.date,
                'ref': n.name or 'Nasiya Savdo',
                'type': 'Sotuv (Nasiya)',
                'debit': n.amount_total,
                'credit': 0.0,
                'is_foldable': False, # Nasiya doesn't have product lines natively by default in this logic
            })
            
        # POS Orders in range (As debt/Debit)
        range_pos = self.env['van.pos.order'].search([
            ('partner_id', '=', partner.id),
            ('state', '=', 'done'),
            ('date', '>=', str(date_from)),
            ('date', '<=', str(date_to) + " 23:59:59")
        ])
        for pos in range_pos:
            product_details = []
            for line in pos.line_ids:
                product_details.append({
                    'name': line.product_id.name,
                    'qty': line.qty,
                    'price': line.price_unit,
                    'subtotal': line.subtotal
                })
            lines.append({
                'date': pos.date, # keep full datetime
                'ref': pos.name,
                'type': 'Sotuv (POS)',
                'debit': pos.amount_total,
                'credit': 0.0,
                'is_foldable': True,
                'products': product_details
            })
            
        # Payments in range (Kirim as Credit, Chiqim as Debit)
        range_payments = self.env['van.payment'].search([
            ('partner_id', '=', partner.id),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('state', '=', 'received')
        ])
        for pay in range_payments:
            is_kirim = pay.payment_type == 'in'
            lines.append({
                'date': pay.date,
                'ref': pay.name or 'To\'lov',
                'type': 'Kirim' if is_kirim else 'Chiqim (Qaytarildi)',
                'debit': 0.0 if is_kirim else pay.amount,
                'credit': pay.amount if is_kirim else 0.0,
                'is_foldable': False,
            })
            
        # 3. Sort chronologically
        # Ensure all dates are compared properly whether they are date or datetime objects
        import datetime
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
            
            .col-date {{ white-space: nowrap; }}
            .col-num {{ text-align: right; white-space: nowrap; }}
            .text-success {{ color: #16a34a; font-weight: bold; }}
            .text-danger {{ color: #dc2626; font-weight: bold; }}
            .text-primary {{ color: #2563eb; font-weight: bold; }}
            
            summary {{ outline: none; cursor: pointer; list-style: none; font-weight: 600; color: #0f172a; width: 100%; box-sizing: border-box; }}
            summary::-webkit-details-marker {{ display: none; }}
            .summary-content {{ display: flex; align-items: center; width: 100%; }}
            .summary-icon {{ font-size: 10px; color: #94a3b8; margin-right: 6px; transition: transform 0.2s; display: inline-block; }}
            details[open] summary .summary-icon {{ transform: rotate(90deg); }}
            
            .drilled-down-table {{ width: 95%; margin: 10px auto; background-color: #fef9c3; border-radius: 6px; box-shadow: inset 0 1px 3px rgba(0,0,0,0.05); border: 1px solid #fde047; }}
            .drilled-down-table td {{ padding: 6px 12px; font-size: 13px; border-bottom: 1px dashed #fde047; }}
            .drilled-down-table tr:last-child td {{ border-bottom: none; }}
            .muted {{ color: #64748b; font-size: 12px; }}
            .badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 12px; text-align: center; white-space: nowrap; }}
        </style>
        
        <div style="background: white; padding: 20px; border-radius: 8px; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
            <div style="display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 20px; padding-bottom: 15px; border-bottom: 1px solid #e2e8f0;">
                <div>
                    <h2 style="margin: 0; color: #0f172a; font-size: 20px;">{partner.name} - Hisob-kitob Daftari</h2>
                    <p style="margin: 5px 0 0 0; color: #64748b; font-size: 14px;"><strong>Davr:</strong> {date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}</p>
                </div>
            </div>
            
            <table class="ledger-table">
                <thead>
                    <tr>
                        <th style="width: 17%;">Sana</th>
                        <th style="width: 23%;">Hujjat</th>
                        <th style="width: 15%; text-align: center;">Turi</th>
                        <th class="col-num" style="width: 15%;">Qarz / Sotuv (+)</th>
                        <th class="col-num" style="width: 15%;">Kirim / To'lov (-)</th>
                        <th class="col-num" style="width: 15%;">Qoldiq Balans</th>
                    </tr>
                </thead>
                <tbody>
                    <!-- Opening Balance Row -->
                    <tr style="background-color: #f8fafc; font-weight: bold; border-bottom: 2px solid #cbd5e1;">
                        <td class="col-date">{date_from.strftime('%d.%m.%Y')}</td>
                        <td style="word-wrap: break-word;">Davr Boshidagi Qoldiq</td>
                        <td style="text-align: center;">-</td>
                        <td class="col-num">-</td>
                        <td class="col-num">-</td>
                        <td class="col-num {'text-danger' if opening_balance > 0 else 'text-success'}">{opening_balance:,.0f} so'm</td>
                    </tr>
        """
        
        # Iteratively build rows
        current_balance = opening_balance
        import pytz
        user_tz = pytz.timezone(self.env.user.tz or 'Asia/Tashkent')
        
        for line in lines:
            current_balance = current_balance + line['debit'] - line['credit']
            
            # Format date with time if it's a datetime object, otherwise just date
            import datetime
            if isinstance(line['date'], datetime.datetime):
                # Convert UTC to local
                local_dt = pytz.utc.localize(line['date']).astimezone(user_tz)
                date_str = local_dt.strftime('%d.%m.%Y %H:%M')
            else:
                date_str = line['date'].strftime('%d.%m.%Y')
                
            debit_str = f"{line['debit']:,.0f}" if line['debit'] else ""
            credit_str = f"{line['credit']:,.0f}" if line['credit'] else ""
            balance_str = f"{current_balance:,.0f}"
            balance_class = "text-danger" if current_balance > 0 else "text-success" if current_balance < 0 else ""
            
            if line['is_foldable'] and line.get('products'):
                # Foldable row
                html += f"""
                    <tr class="ledger-row">
                        <td colspan="6" style="padding: 0;">
                            <details>
                                <summary style="padding: 10px 0;">
                                    <div class="summary-content">
                                        <div style="width: 17%; white-space: nowrap; padding-left: 8px;"><span class="summary-icon">▶</span> {date_str}</div>
                                        <div style="width: 23%; word-wrap: break-word; padding: 0 8px;">{line['ref']}</div>
                                        <div style="width: 15%; text-align: center;"><span class="badge" style="background:#e0f2fe; color:#0369a1;">{line['type']}</span></div>
                                        <div style="width: 15%; padding: 0 8px;" class="col-num text-danger">{debit_str}</div>
                                        <div style="width: 15%; padding: 0 8px;" class="col-num text-success">{credit_str}</div>
                                        <div style="width: 15%; padding: 0 8px;" class="col-num {balance_class}">{balance_str}</div>
                                    </div>
                                </summary>
                                <table class="drilled-down-table">
                """
                for p in line['products']:
                    html += f"""
                                    <tr>
                                        <td width="55%" style="padding-left: 25px;"><b>• {p['name']}</b></td>
                                        <td width="20%" class="muted">{p['qty']} x {p['price']:,.0f}</td>
                                        <td width="25%" style="text-align:right;"><b>{p['subtotal']:,.0f} so'm</b></td>
                                    </tr>
                    """
                html += """
                                </table>
                            </details>
                        </td>
                    </tr>
                """
            else:
                # Flat row
                type_badge = f"<span class='badge' style='background:#f1f5f9; color:#334155;'>{line['type']}</span>"
                if 'Kirim' in line['type']:
                    type_badge = f"<span class='badge' style='background:#dcfce7; color:#166534;'>{line['type']}</span>"
                
                html += f"""
                    <tr class="ledger-row">
                        <td class="col-date">{date_str}</td>
                        <td style="word-wrap: break-word;">{line['ref']}</td>
                        <td style="text-align: center;">{type_badge}</td>
                        <td class="col-num text-danger">{debit_str}</td>
                        <td class="col-num text-success">{credit_str}</td>
                        <td class="col-num {balance_class}">{balance_str}</td>
                    </tr>
                """
        
        # Final Closing Balance Row
        final_balance_class = "text-danger" if current_balance > 0 else "text-success" if current_balance < 0 else ""
        html += f"""
                    <!-- Closing Balance Row -->
                    <tr style="background-color: #f8fafc; border-top: 2px solid #cbd5e1; font-weight: bold;">
                        <td class="col-date">{date_to.strftime('%d.%m.%Y')}</td>
                        <td style="word-wrap: break-word;">Davr Oxiridagi Qoldiq</td>
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
        
        # Return the same view, but with the HTML populated. We can use a special form view for this or simply reload.
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'van.ledger.report.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }
