import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

class VanTrip(models.Model):
    _name = 'van.trip'
    _description = 'Kun Sayohati (Van Trip)'
    _order = 'date desc, id desc'

    name = fields.Char(string='Sayohat Raqami', required=True, copy=False, readonly=True, default=lambda self: _('Yangi'))
    company_id = fields.Many2one('res.company', string='Korxona', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', store=True)

    taminotchi_id = fields.Many2one('van.taminotchi', string="Taminotchi (Yetkazib beruvchi)", required=True)
    agent_id = fields.Many2one('res.users', string='Savdo Agenti', required=True, default=lambda self: self.env.user)
    location_id = fields.Many2one(
        'stock.location',
        string='Mashina Ombori',
        required=True,
        domain=[('usage', '=', 'internal')],
        default=lambda self: self.env['stock.location'].search([('complete_name', 'ilike', 'WH/Stock')], limit=1)
    )

    
    date = fields.Datetime(string='Sana', required=True, default=fields.Datetime.now)
    
    state = fields.Selection([
        ('draft', 'Qoralama'),
        ('validated', 'Tasdiqlangan')
    ], string='Holat', default='draft', required=True, copy=False)

    trip_line_ids = fields.One2many('van.trip.line', 'trip_id', string='Yuklangan Mahsulotlar')

    # Quantities & Financials
    x_loaded_qty = fields.Float(string='Yuklangan Miqdor', compute='_compute_quantities')
    amount_cost_total = fields.Monetary(string="Jami Tan Narx", compute='_compute_quantities', currency_field='currency_id')

    note = fields.Text(string='Izoh')


    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Yangi')) == _('Yangi'):
                vals['name'] = self.env['ir.sequence'].next_by_code('van.trip') or _('Yangi')
        return super().create(vals_list)

    def unlink(self):
        for trip in self:
            # If trip has already affected agent summary inventory
            if trip.state == 'validated':
                summary = self.env['van.agent.summary'].search([
                    ('agent_id', '=', trip.agent_id.id),
                ], limit=1)
                
                if summary:
                    product_dict = {}
                    for line in trip.trip_line_ids:
                        product_dict[line.product_id.id] = product_dict.get(line.product_id.id, 0.0) + line.loaded_qty
                        
                    for p_id, qty in product_dict.items():
                        inv_line = self.env['van.agent.inventory.line'].search([
                            ('summary_id', '=', summary.id),
                            ('product_id', '=', p_id)
                        ], limit=1)
                        
                        if inv_line:
                            # Reverse the addition
                            inv_line.loaded_qty -= qty

        return super().unlink()

    @api.depends('trip_line_ids.loaded_qty', 'trip_line_ids.price_unit')
    def _compute_quantities(self):
        for trip in self:
            trip.x_loaded_qty = sum(trip.trip_line_ids.mapped('loaded_qty'))
            trip.amount_cost_total = sum(trip.trip_line_ids.mapped('price_subtotal'))

    def action_validate(self):
        for trip in self:
            if trip.state != 'draft':
                raise UserError(_("Sayohatni tasdiqlash uchun u 'Qoralama' holatda bo'lishi kerak!"))
            
            if not trip.trip_line_ids:
                raise UserError(_("Hech qanday mahsulot qo'shilmagan! Iltimos, oldin mahsulot qo'shing."))
                
            trip.state = 'validated'

            # Agent doimiy hisoboti profilini qidiramiz
            summary = self.env['van.agent.summary'].search([
                ('agent_id', '=', trip.agent_id.id),
            ], limit=1)

            if not summary:
                summary = self.env['van.agent.summary'].create({
                    'agent_id': trip.agent_id.id,
                })

            # Mahsulotlarni guruhlash (bir xil mahsulot 2 marta kiritilsa qo'shiladi)
            product_dict = {}
            for line in trip.trip_line_ids:
                if line.product_id.id not in product_dict:
                    product_dict[line.product_id.id] = {
                        'qty': 0.0,
                        'cost_price': line.price_unit,
                        'sale_price': line.sale_price_unit or line.product_id.list_price,
                    }
                product_dict[line.product_id.id]['qty'] += line.loaded_qty
                product_dict[line.product_id.id]['cost_price'] = line.price_unit
                product_dict[line.product_id.id]['sale_price'] = line.sale_price_unit or line.product_id.list_price

            # Inventar satrlarini yangilash
            for p_id, data in product_dict.items():
                try:
                    product = self.env['van.product'].browse(p_id)
                    if not product or not product.active:
                        _logger.warning(f"Yuklash {trip.name}: Mahsulot {p_id} o'chirilgan yoki topilmadi.")
                        continue
                        
                    existing_inv_line = self.env['van.agent.inventory.line'].search([
                        ('summary_id', '=', summary.id),
                        ('product_id', '=', p_id)
                    ], limit=1)

                    if existing_inv_line:
                        existing_inv_line.loaded_qty += data['qty']
                        if not existing_inv_line.price_unit:
                            existing_inv_line.price_unit = data['sale_price'] or product.list_price
                        if not existing_inv_line.cost_price:
                            existing_inv_line.cost_price = data['cost_price'] or product.cost_price
                    else:
                        self.env['van.agent.inventory.line'].create({
                            'summary_id': summary.id,
                            'product_id': p_id,
                            'price_unit': data['sale_price'] or product.list_price,
                            'cost_price': data['cost_price'] or product.cost_price,
                            'loaded_qty': data['qty'],
                        })
                except Exception as e:
                    _logger.error(f"Yuklash {trip.name}: Mahsulot {p_id} inventarga qo'shishda xatolik yuz berdi - Xatolik: {e}")
                    # Davom etamiz, bitta mahsulot butun yuklashni to'xtatmasligi kerak
                    continue
        return True

    def action_cancel(self):
        """ Bekor qilish: Yuklangan miqdorlarni Agent qoldig'idan ayirib tashlaydi """
        for trip in self:
            if trip.state != 'validated':
                raise UserError(_("Faqat tasdiqlangan sayohatni bekor qilish mumkin!"))
                
            summary = self.env['van.agent.summary'].search([
                ('agent_id', '=', trip.agent_id.id),
            ], limit=1)
            
            if summary:
                product_dict = {}
                for line in trip.trip_line_ids:
                    product_dict[line.product_id.id] = product_dict.get(line.product_id.id, 0.0) + line.loaded_qty
                    
                for p_id, qty in product_dict.items():
                    inv_line = self.env['van.agent.inventory.line'].search([
                        ('summary_id', '=', summary.id),
                        ('product_id', '=', p_id)
                    ], limit=1)
                    if inv_line:
                        inv_line.loaded_qty -= qty
                        
            trip.state = 'draft'
        return True

    def unlink(self):
        """ Allow deleting validated trips by gracefully cancelling them and rolling back Agent Inventory first. """
        for trip in self:
            if trip.state == 'validated':
                trip.action_cancel()
            elif trip.state == 'in_progress':
                raise UserError(_("Jarayondagi sayohatni o'chirish mumkin emas. Avval uni bekor qiling!"))
        return super(VanTrip, self).unlink()

    @api.model
    def create_material_request_from_pos(self, agent_id, lines_data):
        """
        Creates a 'draft' van.trip from the POS Material Request Popup.
        """
        agent = self.env['res.users'].browse(agent_id)
        
        # Odoo POS requires an internal location for a trip. 
        # We find their assigned default stock or fallback to a standard internal one.
        location = self.env['stock.location'].search([
            ('usage', '=', 'internal'), 
            ('company_id', 'in', [self.env.company.id, False])
        ], limit=1)
        
        if not location:
            raise UserError(_("Hech qanday ichki ombor topilmadi. Iltimos omborni sozlang."))
            
        if not agent.default_taminotchi_id:
            raise UserError(_("Sizga taminotchi biriktirilmagan. Iltimos, administratorga murojaat qiling."))
            
        trip_vals = {
            'agent_id': agent.id,
            'taminotchi_id': agent.default_taminotchi_id.id,
            'location_id': location.id,
            'state': 'draft',
            'trip_line_ids': [(0, 0, {
                'product_id': line['product_id'],
                'loaded_qty': line['qty'],
                'price_unit': self.env['van.product'].sudo().browse(line['product_id']).cost_price,
                'sale_price_unit': self.env['van.product'].sudo().browse(line['product_id']).list_price,
            }) for line in lines_data]
        }
        
        trip = self.sudo().create(trip_vals)
        # Sayohatni avtomatik tasdiqlash (Agent Qoldig'iga to'g'ridan to'g'ri yuklash)
        trip.sudo().action_validate()
        
        return trip.id

    @api.model
    def get_van_dashboard_data(self, date_from=False, date_to=False):
        """ Dashboard uchun moliya paneli ma'lumotlarini hisoblash RPC metodi. Date filtrlarni qo'llab quvvatlaydi. """
        import pytz
        from datetime import datetime, time
        
        # User timezone or UTC
        tz = pytz.timezone(self._context.get('tz') or 'UTC')
        today_local = datetime.now(tz).date()
        today_start = tz.localize(datetime.combine(today_local, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
        
        # Date Logic
        domain_pos = []
        domain_vp = []
        domain_foyda = [('state', '=', 'done')]
        domain_chiqim = [('payment_type', '=', 'out')]
        
        
        if date_from:
            dt_from = datetime.strptime(date_from, "%Y-%m-%d")
            s_date = tz.localize(datetime.combine(dt_from, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
            domain_pos.append(('date', '>=', s_date))
            domain_vp.append(('date', '>=', s_date))
            domain_foyda.append(('date', '>=', s_date))
            domain_chiqim.append(('date', '>=', s_date))
            
        if date_to:
            dt_to = datetime.strptime(date_to, "%Y-%m-%d")
            e_date = tz.localize(datetime.combine(dt_to, time.max)).astimezone(pytz.UTC).replace(tzinfo=None)
            domain_pos.append(('date', '<=', e_date))
            domain_vp.append(('date', '<=', e_date))
            domain_foyda.append(('date', '<=', e_date))
            domain_chiqim.append(('date', '<=', e_date))
            
        if not date_from and not date_to:
            domain_foyda.append(('date', '>=', today_start))
            domain_chiqim.append(('date', '>=', today_start))
        
        # 1. Total Global Nasiya + Agent Inventory at Cost
        # Customer debt remains the base, and we additionally include the
        # current agent inventory value at cost so the dashboard card reflects
        # both outstanding receivables and loaded stock value.
        partners = self.env['res.partner'].search([('x_is_van_customer', '=', True)])
        total_customer_nasiya = sum(partners.mapped('x_van_total_due'))
        inventory_lines = self.env['van.agent.inventory.line'].search([])
        total_inventory_cost_nasiya = sum(
            (line.remaining_qty or 0.0) * (line.cost_price or 0.0)
            for line in inventory_lines
        )
        total_global_nasiya = total_customer_nasiya + total_inventory_cost_nasiya

        # 2. POS Cash & Card (Filtered by Date or All-Time)
        pos_orders = self.env['van.pos.order'].search(domain_pos)
        t_cash = 0.0  # Will be filled from van.payment AND Naqt Savdo
        t_card = 0.0
        
        # --- POS Naqt Savdo (Cash Sales) ---
        t_cash += sum(o.amount_total for o in pos_orders.filtered(lambda x: x.sale_type == 'naqt' and x.state == 'done'))

        # 3. Add Kirim / Track Chiqim (Filtered by Date or All-Time)
        van_payments = self.env['van.payment'].search(domain_vp)
        
        for vp in van_payments:
            if vp.payment_type == 'in':
                if vp.payment_method == 'cash':
                    t_cash += vp.amount
            elif vp.payment_type == 'out':
                t_cash -= vp.amount  # Subtract chiqim so Naqt Pul equals agent's current balance
                
        # Independent Chiqim Calculation (Display exclusively Today if no filter is applied)
        t_chiqim_display = sum(self.env['van.payment'].search(domain_chiqim).mapped('amount'))

        # 4. Calculate Margin (Foyda) for Filtered sales
        margin_today = 0.0
        
        foyda_orders = self.env['van.pos.order'].search(domain_foyda)
        for order in foyda_orders:
            for line in order.line_ids:
                cost_unit = line.product_id.cost_price or 0.0
                margin_today += (line.price_unit - cost_unit) * line.qty

        # 5. Top Mijozlar va Agentlar (Filtered by Date, or All-Time if no date)
        # Using the same pos_orders variable as it's already filtered properly based on date_from/date_to
        monthly_orders = pos_orders.filtered(lambda o: o.state == 'done')

        customer_totals = {}
        agent_totals = {}
        product_totals = {}
        
        for mo in monthly_orders:
            # Products
            for line in mo.line_ids:
                if line.product_id:
                    p_id = line.product_id.id
                    p_name = line.product_id.name
                    if p_id not in product_totals:
                        product_totals[p_id] = {'name': p_name, 'total': 0.0}
                    product_totals[p_id]['total'] += line.subtotal
            # Customers (Aggregate by Name to merge duplicate partner records like "Yangi apteka")
            if mo.partner_id:
                c_name = mo.partner_id.name or "Noma'lum"
                c_key = c_name.strip().upper()
                if c_key not in customer_totals:
                    customer_totals[c_key] = {'name': c_name.strip(), 'total': 0.0}
                customer_totals[c_key]['total'] += mo.amount_total
                
            # Agents
            a_id = mo.agent_id.id
            a_name = mo.agent_id.name
            if a_id not in agent_totals:
                agent_totals[a_id] = {'name': a_name, 'total': 0.0}
            agent_totals[a_id]['total'] += mo.amount_total

        # Sort and take top 5
        top_customers = sorted(customer_totals.values(), key=lambda x: x['total'], reverse=True)[:5]
        top_agents = sorted(agent_totals.values(), key=lambda x: x['total'], reverse=True)[:5]
        top_products = sorted(product_totals.values(), key=lambda x: x['total'], reverse=True)[:5]

        # 6. Monthly Sales Chart Data (Last 6 Months)
        from dateutil.relativedelta import relativedelta
        import calendar
        
        chart_labels = []
        chart_data = []
        
        uzbek_months = {
            1: "Yanvar", 2: "Fevral", 3: "Mart", 4: "Aprel", 5: "May", 6: "Iyun",
            7: "Iyul", 8: "Avgust", 9: "Sentabr", 10: "Oktabr", 11: "Noyabr", 12: "Dekabr"
        }

        # Going back 5 months + current month = 6 months total
        for i in range(5, -1, -1):
            target_date = today_local - relativedelta(months=i)
            first_day = target_date.replace(day=1)
            last_day = target_date.replace(day=calendar.monthrange(target_date.year, target_date.month)[1])
            
            s_date = tz.localize(datetime.combine(first_day, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
            e_date = tz.localize(datetime.combine(last_day, time.max)).astimezone(pytz.UTC).replace(tzinfo=None)
            
            # Calculate sum using standard search and mapped to avoid read_group API changes
            domain = [('date', '>=', s_date), ('date', '<=', e_date), ('state', '=', 'done')]
            orders = self.env['van.pos.order'].search(domain)
            month_total = sum(orders.mapped('amount_total'))
            
            chart_labels.append(f"{uzbek_months[target_date.month]} {target_date.year}")
            chart_data.append(month_total)

        # Get view_ids for explicitly opening list views
        detail_view = self.env.ref('van_sales_pharma.view_van_dashboard_detail_list', raise_if_not_found=False)
        margin_view = self.env.ref('van_sales_pharma.view_van_pos_margin_list', raise_if_not_found=False)

        # 7. Total Taminotchi Balance (All-Time)
        taminotchilar = self.env['van.taminotchi'].sudo().search([])
        total_taminotchi_balance = sum(taminotchilar.mapped('balance'))

        # Calculate new metrics based on specifications
        jami = t_cash + total_global_nasiya
        sof_foyda = jami - total_taminotchi_balance

        return {
            'today_trips_count': len(pos_orders),
            'active_trips_count': len(pos_orders.filtered(lambda o: o.state == 'done')),
            'total_cash': t_cash,
            'total_card': t_card,
            'total_chiqim': t_chiqim_display,
            'total_global_nasiya': total_global_nasiya,
            'total_customer_nasiya': total_customer_nasiya,
            'total_inventory_cost_nasiya': total_inventory_cost_nasiya,
            'total_taminotchi_balance': total_taminotchi_balance,
            'jami': jami,
            'sof_foyda': sof_foyda,
            'margin_today': margin_today,
            'top_customers': top_customers,
            'top_agents': top_agents,
            'top_products': top_products,
            'chart_labels': chart_labels,
            'chart_data': chart_data,
            'detail_view_id': detail_view.id if detail_view else False,
            'margin_view_id': margin_view.id if margin_view else False,
            'currency_id': self.env.company.currency_id.id,
        }
