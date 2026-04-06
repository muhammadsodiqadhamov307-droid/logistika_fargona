from odoo import models, fields, api, _
from datetime import datetime, time, date as _date
import pytz

class VanAgentSummary(models.Model):
    """
    Har bir savdo agenti uchun umumiy hisobot modeli.
    Bu model yagona (doimiy) profil bo'lib xizmat qiladi.
    Moliya va sotuvlar date_from va date_to ga asosan hisoblanadi.
    """
    _name = 'van.agent.summary'
    _description = 'Agent Hisobot (Doimiy)'
    _order = 'agent_id'
    _rec_name = 'agent_id'

    agent_id = fields.Many2one('res.users', string='Agent', required=True, index=True)
    # Filtrlash uchun sanalar (majburiy emas)
    date_from = fields.Date(string='Dastlabki Sana', default=fields.Date.context_today, store=True)
    date_to = fields.Date(string='Oxirgi Sana', default=fields.Date.context_today, store=True)

    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', store=True)

    oylik_balansi = fields.Monetary(string='Oylik Qoldig\'i', compute='_compute_oylik_balansi', currency_field='currency_id') # Changed label slightly, keeps value
    jami_nasiya = fields.Monetary(string='Jami Nasiya', compute='_compute_jami_nasiya', currency_field='currency_id')
    
    total_foyda = fields.Monetary(string='Foyda', compute='_compute_financials', currency_field='currency_id')
    qoladigan_pul = fields.Monetary(string='Agentdan Qoladigan', compute='_compute_agentdan_qoladigan', currency_field='currency_id')

    # NEW FIELDS FOR COMMISSION FIX:
    yalpi_balans = fields.Monetary(string='Yalpi Balans', compute='_compute_financials', currency_field='currency_id')
    agent_oyligi_earned = fields.Monetary(string='Agent Oyligi (Ishlab topilgan)', compute='_compute_oylik_balansi', currency_field='currency_id')
    oylik_olindi = fields.Monetary(string='Oylik Olindi', compute='_compute_oylik_balansi', currency_field='currency_id')
    oylik_qoldigi = fields.Monetary(string='Qolgan Oylik', compute='_compute_oylik_balansi', currency_field='currency_id')
    sof_balans = fields.Monetary(string='Sof Balans', compute='_compute_financials', currency_field='currency_id')


    # === Moliyaviy ko'rsatkichlar ===
    total_cash = fields.Monetary(string='Naqt Pul', currency_field='currency_id',
                                 compute='_compute_financials')
    total_nasiya = fields.Monetary(string='Nasiya (Qarz)', currency_field='currency_id',
                                   compute='_compute_financials')
    total_chiqim = fields.Monetary(string='Chiqim (Xarajat)', currency_field='currency_id',
                                  compute='_compute_financials')
    total_sales = fields.Monetary(string='Jami Sotuv', currency_field='currency_id',
                                  compute='_compute_financials')
    total_balance = fields.Monetary(string='Mavjud Balans', currency_field='currency_id',
                                   compute='_compute_financials',
                                   help="Ushbu oraliqdagi Naqt - Chiqim")

    # === Mahsulot inventariyasi ===
    inventory_line_ids = fields.One2many('van.agent.inventory.line', 'summary_id', string='Inventar')
    active_inventory_line_ids = fields.Many2many(
        'van.agent.inventory.line',
        compute='_compute_active_inventory',
        string="Faol Inventar"
    )
    inventory_count = fields.Integer(string='Mahsulotlar Soni', compute='_compute_active_inventory')

    total_inventory_qty = fields.Float(string='Jami Mahsulotlar Soni', compute='_compute_inventory_dashboard')
    total_inventory_value = fields.Monetary(string='Jami Summa (Sotuv)', currency_field='currency_id', compute='_compute_inventory_dashboard')
    total_inventory_cost_value = fields.Monetary(string='Jami Summa (Olish Narxida)', currency_field='currency_id', compute='_compute_inventory_dashboard')
    expected_net_profit = fields.Monetary(string='Kutilayotgan Foyda', currency_field='currency_id', compute='_compute_inventory_dashboard')

    @api.depends('inventory_line_ids.remaining_qty', 'inventory_line_ids.price_unit', 'inventory_line_ids.cost_price')
    def _compute_inventory_dashboard(self):
        for rec in self:
            qty = val = cost_val = profit = 0.0
            for line in rec.active_inventory_line_ids:
                qty += line.remaining_qty
                val += line.remaining_qty * line.price_unit
                cost = line.cost_price
                cost_val += line.remaining_qty * cost
                profit += (line.price_unit - cost) * line.remaining_qty
            rec.total_inventory_qty = qty
            rec.total_inventory_value = val
            rec.total_inventory_cost_value = cost_val
            rec.expected_net_profit = profit

    @api.depends('inventory_line_ids.remaining_qty')
    def _compute_active_inventory(self):
        for rec in self:
            active_lines = rec.inventory_line_ids.filtered(lambda l: l.remaining_qty > 0)
            rec.active_inventory_line_ids = active_lines
            rec.inventory_count = len(active_lines)

    # === Sotuv buyurtmalari ===
    pos_order_count = fields.Integer(string='Sotuvlar Soni', compute='_compute_financials')
    pos_order_ids = fields.Many2many('van.pos.order', compute='_compute_financials', string="Sotuvlar Ro'yxati")

    # === Chiqimlar ro'yxati (computed, for tab display & deletion) ===
    chiqim_ids = fields.Many2many(
        'van.payment',
        compute='_compute_financials',
        string='Chiqimlar',
    )
    
    # === Oylik To'lovlar ro'yxati (computed, for tab display) ===
    oylik_chiqim_ids = fields.Many2many(
        'van.payment',
        compute='_compute_financials',
        string='Oylik To\'lovlar',
    )
    
    # === Kirimlar ro'yxati (computed, for tab display) ===
    kirim_ids = fields.Many2many(
        'van.payment',
        compute='_compute_financials',
        string='Kirimlar',
    )

                    
    @api.depends('agent_id.mijoz_ids.x_van_total_due')
    def _compute_jami_nasiya(self):
        for rec in self:
            # Sum of all assigned clients' current debts (includes Sales, Payments, and Ostatka Qarzi)
            partners = rec.agent_id.mijoz_ids
            rec.jami_nasiya = sum(partners.mapped('x_van_total_due'))

    @api.depends('yalpi_balans', 'agent_id', 'date_from', 'date_to')
    def _compute_oylik_balansi(self):
        """Agent Oyligi = (Yalpi Balans × komissiya%) − oylik chiqimlar paid in period."""
        for rec in self:
            # Step 1: Earned commission based entirely on Yalpi Balans (Gross incoming cash)
            earned = rec.yalpi_balans * (rec.agent_id.komissiya_foizi / 100.0)

            # Step 2: Subtract oylik chiqimlar already paid in this period
            has_filter = bool(rec.date_from or rec.date_to)

            domain_chiqim = [
                ('agent_id', '=', rec.agent_id.id),
                ('payment_type', '=', 'out'),
                ('expense_type', '=', 'salary'),
            ]
            domain_payout = [
                ('agent_id', '=', rec.agent_id.id),
                ('payment_type', '=', 'out'),
                ('expense_type', '=', 'payout'),
            ]

            if has_filter:
                tz = pytz.timezone(self.env.user.tz or self.env.context.get('tz') or 'UTC')
                if rec.date_from:
                    utc_start = tz.localize(datetime.combine(rec.date_from, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
                    domain_chiqim.append(('date', '>=', utc_start))
                    domain_payout.append(('date', '>=', utc_start))
                if rec.date_to:
                    utc_end = tz.localize(datetime.combine(rec.date_to, time.max)).astimezone(pytz.UTC).replace(tzinfo=None)
                    domain_chiqim.append(('date', '<=', utc_end))
                    domain_payout.append(('date', '<=', utc_end))

            oylik_chiqimlar = self.env['van.payment'].search(domain_chiqim)
            # Include agent payouts from earlier models as well
            payouts = self.env['van.payment'].search(domain_payout)
            total_paid_salary = sum(oylik_chiqimlar.mapped('amount'))
            total_paid_payouts = sum(payouts.mapped('amount'))
            total_paid = total_paid_salary + total_paid_payouts

            rec.agent_oyligi_earned = earned
            rec.oylik_olindi = total_paid
            rec.oylik_qoldigi = earned - total_paid
            rec.oylik_balansi = rec.oylik_qoldigi



    @api.depends('total_foyda', 'agent_oyligi_earned')
    def _compute_agentdan_qoladigan(self):
        """Agentdan qoladigan = Foyda(filtered) - Oylik_earned(filtered)."""
        for rec in self:
            rec.qoladigan_pul = rec.total_foyda - rec.agent_oyligi_earned

    @api.depends('date_from', 'date_to', 'agent_id')
    def _compute_financials(self):
        for rec in self:
            tz = pytz.timezone(self.env.user.tz or self.env.context.get('tz') or 'UTC')
            
            has_filter = bool(rec.date_from or rec.date_to)
            
            # --- Group 1: Configurable Period ---
            # Used for: Sotuvlar, Jami Sotuv, Naqt, Chiqim, Balans, Foyda
            g1_order_domain = [('agent_id', '=', rec.agent_id.id), ('state', '=', 'done')]
            g1_payment_domain = [('agent_id', '=', rec.agent_id.id)]
            
            if has_filter:
                if rec.date_from:
                    utc_start = tz.localize(datetime.combine(rec.date_from, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
                    g1_order_domain.append(('date', '>=', utc_start))
                    g1_payment_domain.append(('date', '>=', utc_start))
                if rec.date_to:
                    utc_end = tz.localize(datetime.combine(rec.date_to, time.max)).astimezone(pytz.UTC).replace(tzinfo=None)
                    g1_order_domain.append(('date', '<=', utc_end))
                    g1_payment_domain.append(('date', '<=', utc_end))
            
            g1_orders = self.env['van.pos.order'].search(g1_order_domain)
            g1_all_payments = self.env['van.payment'].search(g1_payment_domain)
            
            g1_kirims = g1_all_payments.filtered(lambda p: p.payment_type == 'in')
            g1_chiqims = g1_all_payments.filtered(lambda p: p.payment_type == 'out' and p.expense_type not in ('salary', 'payout'))
            g1_oylik_chiqims = g1_all_payments.filtered(lambda p: p.payment_type == 'out' and p.expense_type in ('salary', 'payout'))
            
            # Group 1 Calcs
            rec.pos_order_ids = g1_orders
            rec.pos_order_count = len(g1_orders)
            rec.kirim_ids = g1_kirims
            rec.chiqim_ids = g1_chiqims
            rec.oylik_chiqim_ids = g1_oylik_chiqims
            
            total_sales = sum(g1_orders.mapped('amount_total'))
            naqt_savdo_total = sum(o.amount_total for o in g1_orders if o.sale_type == 'naqt')
            nasiya_sales = sum(o.amount_total for o in g1_orders if o.sale_type == 'nasiya')
            
            kirim_total = sum(g1_kirims.mapped('amount'))
            
            # To fix the gross balance, subtract out the salary portions of total chiqim
            total_paid_salary = sum(g1_oylik_chiqims.mapped('amount'))
            daily_chiqim = sum(g1_chiqims.mapped('amount'))
            
            cash = naqt_savdo_total + kirim_total
            
            rec.total_sales = total_sales
            rec.total_cash = cash
            rec.total_chiqim = daily_chiqim
            
            # Gross balance = cash - only daily expenses
            rec.yalpi_balans = cash - daily_chiqim
            
            # Net balance = Gross balance - salary advances taken
            rec.sof_balans = rec.yalpi_balans - total_paid_salary
            
            # Keep original total_balance matching sof_balans
            rec.total_balance = rec.sof_balans
            rec.total_nasiya = nasiya_sales - kirim_total
            
            margin = 0.0
            for order in g1_orders:
                for line in order.line_ids:
                    cost_unit = line.product_id.cost_price or 0.0
                    margin += (line.price_unit - cost_unit) * line.qty
            rec.total_foyda = margin

    def action_view_pos_orders(self):
        self.ensure_one()
        order_domain = [('agent_id', '=', self.agent_id.id)]
        tz = pytz.timezone(self.env.user.tz or self.env.context.get('tz') or 'UTC')
        
        if self.date_from:
            local_start = tz.localize(datetime.combine(self.date_from, time.min))
            utc_start = local_start.astimezone(pytz.UTC).replace(tzinfo=None)
            order_domain.append(('date', '>=', utc_start))
        if self.date_to:
            local_end = tz.localize(datetime.combine(self.date_to, time.max))
            utc_end = local_end.astimezone(pytz.UTC).replace(tzinfo=None)
            order_domain.append(('date', '<=', utc_end))

        orders = self.env['van.pos.order'].search(order_domain)
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.agent_id.name} - Sotuvlar',
            'res_model': 'van.pos.order',
            'view_mode': 'list,form',
            'domain': [('id', 'in', orders.ids)],
            'target': 'current',
        }

    # === Dastlabki/Oxirgi Sana Dashboard Button Actions ===
    def action_apply_filter(self):
        """
        Standard NO-OP. Odoo implicitly saves the form data (dates) before triggering this method, 
        so the @api.depends compute block automatically re-runs.
        """
        return True
        
    def action_clear_filter(self):
        """
        Wipes the custom dates to force them back to today's date.
        """
        today = fields.Date.context_today(self)
        for rec in self:
            rec.date_from = today
            rec.date_to = today
        return True
        
    @api.model
    def action_setup_summary(self):
        """
        Initializes agent summary records:
        1. Resets dates to today (timezone aware)
        2. Creates missing summary records for internal users
        Returns the action definition for opening the view.
        """
        today = fields.Date.context_today(self)
        self.search([]).write({
            'date_from': today,
            'date_to': today
        })
        
        # Auto-create missing summary records
        existing_agent_ids = self.search([]).mapped('agent_id.id')
        all_users = self.env['res.users'].search([('share', '=', False)])
        for user in all_users:
            if user.id not in existing_agent_ids:
                self.create({'agent_id': user.id})
                
        return {
            'name': _('Agentlar Hisoboti'),
            'type': 'ir.actions.act_window',
            'res_model': 'van.agent.summary',
            'view_mode': 'kanban,list,form',
            'view_ids': [
                (0, 0, {'view_mode': 'kanban', 'view_id': self.env.ref('van_sales_pharma.view_van_agent_summary_kanban').id}),
                (0, 0, {'view_mode': 'list', 'view_id': self.env.ref('van_sales_pharma.view_van_agent_summary_list').id}),
                (0, 0, {'view_mode': 'form', 'view_id': self.env.ref('van_sales_pharma.view_van_agent_summary_form').id})
            ],
            'context': {}
        }

    def action_refresh_data(self):
        """
        Acts exactly like a hard page reload for the compute fields.
        """
        return True

    def action_view_chiqimlar(self):
        self.ensure_one()
        domain = [('agent_id', '=', self.agent_id.id), ('payment_type', '=', 'out'), ('expense_type', 'not in', ('salary', 'payout'))]
        tz = pytz.timezone(self.env.user.tz or self.env.context.get('tz') or 'UTC')
        
        if self.date_from:
            local_start = tz.localize(datetime.combine(self.date_from, time.min))
            utc_start = local_start.astimezone(pytz.UTC).replace(tzinfo=None)
            domain.append(('date', '>=', utc_start))
        if self.date_to:
            local_end = tz.localize(datetime.combine(self.date_to, time.max))
            utc_end = local_end.astimezone(pytz.UTC).replace(tzinfo=None)
            domain.append(('date', '<=', utc_end))
            
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.agent_id.name} - Chiqimlar',
            'res_model': 'van.payment',
            'view_mode': 'list,form',
            'domain': domain,
            'target': 'current',
        }

    def action_view_kirimlar(self):
        self.ensure_one()
        domain = [('agent_id', '=', self.agent_id.id), ('payment_type', '=', 'in')]
        tz = pytz.timezone(self.env.user.tz or self.env.context.get('tz') or 'UTC')
        
        if self.date_from:
            local_start = tz.localize(datetime.combine(self.date_from, time.min))
            utc_start = local_start.astimezone(pytz.UTC).replace(tzinfo=None)
            domain.append(('date', '>=', utc_start))
        if self.date_to:
            local_end = tz.localize(datetime.combine(self.date_to, time.max))
            utc_end = local_end.astimezone(pytz.UTC).replace(tzinfo=None)
            domain.append(('date', '<=', utc_end))
            
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.agent_id.name} - Kirimlar',
            'res_model': 'van.payment',
            'view_mode': 'list,form',
            'domain': domain,
            'target': 'current',
        }

    def action_view_inventory_kanban(self):
        self.ensure_one()
        view_id = self.env.ref('van_sales_pharma.view_van_agent_summary_inventory_dashboard').id
        return {
            'type': 'ir.actions.act_window',
            'name': f"{self.agent_id.name} - Olib Yurgan Mahsulotlar",
            'res_model': 'van.agent.summary',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(view_id, 'form')],
            'target': 'current',
        }

    def action_rebuild_inventory(self):
        """
        Agentning barcha tasdiqlangan 'Yuklash' (Sayohat) hujjatlaridan foydalanib
        inventardagi 'Yuklangan Miqdor' (loaded_qty) va narxlarni noldan qayta hisoblab chiqadi.
        Sotilgan va qoldiq miqdorlar Odoo tomonidan avtomatik qayta hisoblanadi.
        """
        self.ensure_one()
        
        # Tasdiqlangan barcha yuklash (Sayohat) hujjatlarini topamiz
        trips = self.env['van.trip'].search([
            ('agent_id', '=', self.agent_id.id),
            ('state', '=', 'validated')
        ])
        
        # Har bir mahsulot bo'yicha hisob-kitob summarysi
        product_totals = {}
        for trip in trips:
            for line in trip.trip_line_ids:
                pid = line.product_id.id
                if pid not in product_totals:
                    product_totals[pid] = {
                        'qty': 0.0,
                        'price': line.sale_price_unit or line.product_id.list_price or 0.0,
                        'cost': line.price_unit or line.product_id.cost_price or 0.0
                    }
                # Q'oshilgan miqdorni yig'ib boramiz
                product_totals[pid]['qty'] += line.loaded_qty
                # Eng oxirgi narx bilan yangilaymiz (agar yangi yuklashda narx o'zgargan bo'lsa)
                product_totals[pid]['price'] = line.sale_price_unit or line.product_id.list_price or 0.0
                product_totals[pid]['cost'] = line.price_unit or line.product_id.cost_price or 0.0

        # Eski loaded_qty miqdorlarini tozalaymiz (agar chalkashlik bo'lsa)
        for inv_line in self.inventory_line_ids:
            inv_line.loaded_qty = 0.0

        updated_count = 0
        
        # Topilgan ma'lumotlarni agent summary_id ga biriktiramiz
        for pid, data in product_totals.items():
            if data['qty'] <= 0:
                continue
            
            updated_count += 1
            inv_line = self.env['van.agent.inventory.line'].search([
                ('summary_id', '=', self.id),
                ('product_id', '=', pid)
            ], limit=1)
            
            if inv_line:
                inv_line.loaded_qty = data['qty']
                if not inv_line.price_unit:
                    inv_line.price_unit = data['price']
                if not inv_line.cost_price:
                    inv_line.cost_price = data['cost']
            else:
                self.env['van.agent.inventory.line'].create({
                    'summary_id': self.id,
                    'product_id': pid,
                    'loaded_qty': data['qty'],
                    'price_unit': data['price'],
                    'cost_price': data['cost']
                })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': f"Inventar muvaffaqiyatli qayta tiklandi: jami {updated_count} ta mahsulot turi to'g'rilandi!",
                'type': 'success',
                'sticky': False
            }
        }

class VanAgentInventoryLine(models.Model):
    """
    Agentning mashina omboridagi mahsulotlar ro'yxati.
    """
    _name = 'van.agent.inventory.line'
    _description = 'Agent Inventar Satri'

    summary_id = fields.Many2one('van.agent.summary', required=True, ondelete='cascade')
    product_id = fields.Many2one('van.product', string='Mahsulot', required=True)
    price_unit = fields.Float(string='Narx (So\'m)')
    cost_price = fields.Float(string='Kelish narxi')

    loaded_qty = fields.Float(string='Yuklangan')
    # Not stored — always recomputes live so sold/remaining values reflect new POS orders immediately
    sold_qty = fields.Float(string='Sotilgan', compute='_compute_remaining')
    returned_qty = fields.Float(string='Qaytarilgan', compute='_compute_remaining')
    remaining_qty = fields.Float(string='Qoldiq', compute='_compute_remaining')

    currency_id = fields.Many2one('res.currency', related='summary_id.currency_id')
    subtotal_sold = fields.Monetary(string='Sotuv Summasi', currency_field='currency_id',
                                    compute='_compute_remaining')

    @api.depends('summary_id.date_from', 'summary_id.date_to', 'summary_id.agent_id', 'product_id', 'loaded_qty')
    def _compute_remaining(self):
        """
        Compute sold, returned and remaining quantities for each inventory line.
        Uses optimized search to reflect current POS state.
        """
        for line in self:
            agent_id = line.summary_id.agent_id.id
            date_from = line.summary_id.date_from
            date_to = line.summary_id.date_to
            product_id = line.product_id.id

            # Common domain parts
            base_domain = [
                ('order_id.agent_id', '=', agent_id),
                ('order_id.state', '=', 'done'),
                ('product_id', '=', product_id),
            ]

            # 1. All-time sold qty 
            fast_pos_lines = self.env['van.pos.order.line'].search(base_domain)
            all_time_sold = sum(fast_pos_lines.mapped('qty'))

            # 2. Period sold qty (shown in the 'Sotilgan' column for the chosen date range)
            period_sold = 0.0
            if date_from or date_to:
                tz = pytz.timezone(self.env.user.tz or self.env.context.get('tz') or 'UTC')
                period_domain = list(base_domain)
                if date_from:
                    local_start = tz.localize(datetime.combine(date_from, time.min))
                    utc_start = local_start.astimezone(pytz.UTC).replace(tzinfo=None)
                    period_domain.append(('order_id.date', '>=', utc_start))
                if date_to:
                    local_end = tz.localize(datetime.combine(date_to, time.max))
                    utc_end = local_end.astimezone(pytz.UTC).replace(tzinfo=None)
                    period_domain.append(('order_id.date', '<=', utc_end))
                
                period_lines = self.env['van.pos.order.line'].search(period_domain)
                period_sold = sum(period_lines.mapped('qty'))

            # 3. Ostatka qty
            ostatka_records = self.env['van.agent.ostatka'].search([
                ('agent_id', '=', agent_id),
                ('product_id', '=', product_id)
            ])
            ostatka_qty = sum(ostatka_records.mapped('qty'))

            line.sold_qty = period_sold
            line.returned_qty = 0.0
            line.remaining_qty = max(0.0, (line.loaded_qty + ostatka_qty) - all_time_sold)
            line.subtotal_sold = period_sold * line.price_unit
