from odoo import http, fields, _
from odoo.http import request
from odoo.exceptions import UserError
import logging
import datetime

_logger = logging.getLogger(__name__)

class VanPosController(http.Controller):

    def _get_agent_id(self):
        """Returns the acting agent ID if an admin has selected one, otherwise the actual user ID."""
        user = request.env.user
        is_admin = user.has_group('van_sales_pharma.group_van_admin') or user.has_group('base.group_system')
        if is_admin:
            acting_id = request.session.get('acting_as_agent_id')
            if acting_id:
                acting_user = request.env['res.users'].sudo().browse(int(acting_id))
                if acting_user.exists():
                    return acting_user.id
        return request.env.uid

    @http.route('/van/mobile-pos', type='http', auth='user')
    def mobile_pos_entry(self):
        user = request.env.user
        is_admin = user.has_group('van_sales_pharma.group_van_admin') or user.has_group('base.group_system')
        
        if is_admin:
            acting_agent_id = request.session.get('acting_as_agent_id')
            if not acting_agent_id:
                agent_group = request.env.ref('van_sales_pharma.group_van_agent')
                request.env.cr.execute("SELECT uid FROM res_groups_users_rel WHERE gid = %s", (agent_group.id,))
                user_ids = [row[0] for row in request.env.cr.fetchall()]
                agents = request.env['res.users'].sudo().browse(user_ids)
                return request.render('van_sales_pharma.agent_select_template', {'agents': agents})
                
        # If normal agent, or admin with an already selected agent session, boot the OWL app
        return request.redirect('/web#action=van_sales_pharma.action_van_mobile_pos_app')

    @http.route('/van/mobile-pos/select-agent', type='http', auth='user', methods=['GET'], csrf=False)
    def select_agent(self, agent_id=None, **kwargs):
        user = request.env.user
        is_admin = user.has_group('van_sales_pharma.group_van_admin') or user.has_group('base.group_system')
        if not is_admin:
            return request.redirect('/van/mobile-pos')
        if agent_id:
            request.session['acting_as_agent_id'] = int(agent_id)
        return request.redirect('/van/mobile-pos')

    @http.route('/van/mobile-pos/change-agent', type='http', auth='user')
    def mobile_pos_change_agent(self):
        if request.session.get('acting_as_agent_id'):
            del request.session['acting_as_agent_id']
        return request.redirect('/van/mobile-pos')

    @http.route('/van/pos/get_agents', type='jsonrpc', auth='user')
    def get_agents(self):
        """Returns list of all agent users. Admin only."""
        user = request.env.user
        is_admin = user.has_group('van_sales_pharma.group_van_admin') or user.has_group('base.group_system')
        if not is_admin:
            return []
        agent_group = request.env.ref('van_sales_pharma.group_van_agent')
        request.env.cr.execute("SELECT uid FROM res_groups_users_rel WHERE gid = %s", (agent_group.id,))
        user_ids = [row[0] for row in request.env.cr.fetchall()]
        agents = request.env['res.users'].sudo().browse(user_ids)
        return [{
            'id': a.id,
            'name': a.name,
            'image_url': f'/web/image?model=res.users&id={a.id}&field=avatar_128',
        } for a in agents]

    @http.route('/van/pos/set_agent_session', type='jsonrpc', auth='user')
    def set_agent_session(self, agent_id):
        """Sets acting_as_agent_id in session for admin users."""
        user = request.env.user
        is_admin = user.has_group('van_sales_pharma.group_van_admin') or user.has_group('base.group_system')
        if not is_admin:
            return {'success': False}
        if agent_id:
            request.session['acting_as_agent_id'] = int(agent_id)
        return {'success': True}

    @http.route('/van/pos/get_client_report', type='jsonrpc', auth='user')
    def get_client_report(self, client_id, date_from=None, date_to=None):
        """Returns client transaction history with running balance for Mobile POS Hisob-kitob."""
        try:
            import pytz
            user_tz = pytz.timezone(request.env.user.tz or 'Asia/Tashkent')
            acting_agent_id = self._get_agent_id()

            if int(client_id) == 0:
                # Support "Naqt Savdo" (virtual client)
                partner = None
                client_name = "Naqt savdo (Mijozisiz)"
                total_due = 0.0
            else:
                partner = request.env['res.partner'].sudo().browse(int(client_id))
                if not partner.exists():
                    return {'success': False, 'error': 'Mijoz topilmadi'}
                client_name = partner.name
                total_due = partner.x_van_total_due or 0.0

            transactions = []

            # 1. Boshlang'ich qarz (Ostatka Qarzi) - only for real partners
            if partner:
                for ostatka in partner.x_van_ostatka_ids:
                    if ostatka.amount > 0:
                        transactions.append({
                            'id': ostatka.id,
                            'date_obj': user_tz.localize(datetime.datetime.combine(ostatka.date or datetime.date.today(), datetime.time.min)),
                            'date_label': (ostatka.date or datetime.date.today()).strftime('%d.%m.%Y'),
                            'turi': "boshlangich_qarz",
                            'turi_label': "Boshlang'ich qarz",
                            'summa': ostatka.amount,
                            'is_debt': True,
                            'lines': [],
                        })

            # 2. Sotuvlar (POS Orders)
            order_domain = [('partner_id', '=', partner.id if partner else False), ('state', '=', 'done')]
            if partner:
                order_domain.append(('sale_type', '=', 'nasiya'))
            else:
                order_domain.append(('sale_type', '=', 'naqt'))
            if not partner:
                order_domain.append(('agent_id', '=', acting_agent_id))
            if date_from:
                order_domain.append(('date', '>=', date_from + ' 00:00:00'))
            if date_to:
                order_domain.append(('date', '<=', date_to + ' 23:59:59'))
            orders = request.env['van.pos.order'].sudo().search(order_domain, order='date asc')
            for order in orders:
                if order.amount_total > 0:
                    local_dt = pytz.utc.localize(order.date).astimezone(user_tz)
                    lines = []
                    for l in order.line_ids:
                        lines.append({
                            'id': l.id,
                            'product_id': l.product_id.id,
                            'name': l.product_id.name or '',
                            'qty': l.qty,
                            'price': l.price_unit,
                            'subtotal': l.qty * l.price_unit,
                        })
                    transactions.append({
                        'id': order.id,
                        'date_obj': local_dt,
                        'date_label': local_dt.strftime('%d.%m.%Y %H:%M:%S'),
                        'turi': 'sotuv',
                        'turi_label': '🛒 Sotuv',
                        'summa': order.amount_total,
                        'is_debt': True,
                        'lines': lines,
                    })

            # 3. Kirimlar (Payments)
            pay_domain = [('partner_id', '=', partner.id if partner else False), ('payment_type', '=', 'in')]
            if not partner:
                pay_domain.append(('agent_id', '=', acting_agent_id))
            if date_from:
                pay_domain.append(('date', '>=', date_from + ' 00:00:00'))
            if date_to:
                pay_domain.append(('date', '<=', date_to + ' 23:59:59'))
            payments = request.env['van.payment'].sudo().search(pay_domain, order='date asc')
            for payment in payments:
                if payment.amount > 0:
                    local_dt = pytz.utc.localize(payment.date).astimezone(user_tz)
                    transactions.append({
                        'id': payment.id,
                        'date_obj': local_dt,
                        'date_label': local_dt.strftime('%d.%m.%Y %H:%M:%S'),
                        'turi': 'kirim',
                        'turi_label': '💵 Kirim',
                        'summa': payment.amount,
                        'is_debt': False,
                        'lines': [],
                    })

            # Sort chronologically by date_obj to compute running balance
            transactions.sort(key=lambda x: x['date_obj'] if isinstance(x['date_obj'], (datetime.datetime, datetime.date)) else datetime.datetime.min)
            running_balance = 0.0
            for tx in transactions:
                if tx['is_debt']:
                    running_balance += tx['summa']
                else:
                    running_balance -= tx['summa']
                tx['balance'] = running_balance
                # clean up date_obj for JSON serialization
                if 'date_obj' in tx: del tx['date_obj']

            # Reverse for display (newest first)
            transactions.reverse()

            return {
                'success': True,
                'client_name': client_name,
                'total_due': total_due,
                'telegram_chat_id': partner.telegram_chat_id if partner else '',
                'transactions': transactions,
            }
        except Exception as e:
            _logger.error(f"get_client_report error: {e}")
            return {'success': False, 'error': str(e)}

    @http.route('/van/pos/update_client_telegram_chat_id', type='jsonrpc', auth='user')
    def update_client_telegram_chat_id(self, client_id, telegram_chat_id=''):
        """Updates Telegram Chat ID for a real client from Mobile POS."""
        try:
            client_id = int(client_id or 0)
            if not client_id:
                return {'success': False, 'error': "Naqt savdo uchun Telegram Chat ID saqlanmaydi"}

            partner = request.env['res.partner'].sudo().browse(client_id)
            if not partner.exists():
                return {'success': False, 'error': 'Mijoz topilmadi'}

            chat_id = (telegram_chat_id or '').strip()
            partner.write({'telegram_chat_id': chat_id})

            return {
                'success': True,
                'telegram_chat_id': partner.telegram_chat_id or '',
                'message': "Telegram Chat ID saqlandi",
            }
        except Exception as e:
            _logger.error(f"update_client_telegram_chat_id error: {e}")
            return {'success': False, 'error': str(e)}

    @http.route('/van/pos/create_client', type='jsonrpc', auth='user')
    def create_client(self, name, phone, telegram_chat_id=''):
        """Creates a new client directly from Mobile POS and assigns it to current agent."""
        try:
            name = (name or '').strip()
            phone = (phone or '').strip()
            
            if not name:
                return {'success': False, 'error': 'Mijoz nomi kiritilmagan'}
            if not phone:
                return {'success': False, 'error': 'Telefon raqami kiritilmagan'}

            # Validate duplicate phone
            existing = request.env['res.partner'].sudo().search([('phone', '=', phone)], limit=1)
            if existing:
                return {'success': False, 'error': 'Bu telefon raqami bilan mijoz allaqachon mavjud'}

            agent_id = self._get_agent_id()
            
            new_client = request.env['res.partner'].sudo().create({
                'name': name,
                'phone': phone,
                'telegram_chat_id': telegram_chat_id or '',  # This is the correct field name found in res_partner.py
                'x_is_van_customer': True, # Ensure it gets picked up
                'van_agent_id': agent_id,
                'user_id': agent_id, # Optional standard assignment
            })
            
            # Make sure it's linked in the custom logic if necessary (mijoz_ids)
            # The get_clients logic looks for x_is_van_customer=True, or agent.mijoz_ids.
            agent = request.env['res.users'].sudo().browse(agent_id)
            if hasattr(agent, 'mijoz_ids'):
                # Many2many relation
                agent.write({'mijoz_ids': [(4, new_client.id)]})

            return {
                'success': True,
                'client_id': new_client.id,
                'client_name': new_client.name,
                'message': 'Mijoz muvaffaqiyatli qo\'shildi'
            }
        except Exception as e:
            _logger.error(f"Error creating client: {e}")
            return {'success': False, 'error': str(e)}

    @http.route('/van/pos/get_clients', type='jsonrpc', auth='user')
    def get_clients(self):
        agent_id = self._get_agent_id()
        agent = request.env['res.users'].sudo().browse(agent_id)
        partners = agent.mijoz_ids
            
        # recompute balances based on new nasiya
        partners.sudo()._compute_van_nasiya_stats()
        
        # Get partner IDs for SQL query
        partner_ids = partners.ids
        if partner_ids:
            import pytz
            user_tz = pytz.timezone(request.env.user.tz or 'Asia/Tashkent')
            # Use SQL for efficient sorting by last transaction date (Sale OR Kirim)
            query = """
                SELECT p.id, GREATEST(MAX(o.date), MAX(pay.date)) as last_transaction_date
                FROM res_partner p
                LEFT JOIN van_pos_order o ON o.partner_id = p.id AND o.agent_id = %s AND o.state = 'done'
                LEFT JOIN van_payment pay ON pay.partner_id = p.id AND pay.agent_id = %s AND pay.payment_type = 'in'
                WHERE p.id IN %s
                GROUP BY p.id
                ORDER BY last_transaction_date DESC NULLS LAST, p.name ASC
            """
            request.env.cr.execute(query, (agent_id, agent_id, tuple(partner_ids)))
            sorted_partner_data = request.env.cr.fetchall()
            
            # Map partners to ensure we keep the ones we found
            partner_map = {p.id: p for p in partners}
            client_list = []
            for pid, last_tx in sorted_partner_data:
                p = partner_map.get(pid)
                if p:
                    last_tx_str = ''
                    if last_tx:
                        if hasattr(last_tx, 'strftime'):
                            last_tx_str = pytz.utc.localize(last_tx).astimezone(user_tz).strftime('%Y-%m-%d %H:%M')
                    client_list.append({
                        'id': p.id,
                        'name': p.name,
                        'balance': p.x_van_balance,
                        'total_due': p.x_van_total_due,
                        'last_transaction_date': last_tx_str
                    })
        else:
            client_list = []
        
        # Always Prepend "Naqt savdo (Mijozisiz)"
        client_list.insert(0, {
            'id': 0,
            'name': "Naqt savdo (Mijozisiz)",
            'balance': 0.0,
            'total_due': 0.0,
            'is_cash_sale': True,
            'last_transaction_date': ''
        })
        
        # Add explicit sort_order for frontend persistence
        for idx, client in enumerate(client_list):
            client['sort_order'] = idx
            
        return client_list

    @http.route('/van/pos/get_inventory', type='jsonrpc', auth='user')
    def get_inventory(self):
        agent_id = self._get_agent_id()
        summary = request.env['van.agent.summary'].with_context(lang='uz_UZ').search([('agent_id', '=', agent_id)], limit=1)
        if not summary:
            return []

        sold_qty_by_product = {}
        sold_lines = request.env['van.pos.order.line'].sudo().search([
            ('order_id.agent_id', '=', agent_id),
            ('order_id.state', '=', 'done'),
        ])
        for sold_line in sold_lines:
            product_id = sold_line.product_id.id
            sold_qty_by_product[product_id] = sold_qty_by_product.get(product_id, 0.0) + (sold_line.qty or 0.0)

        sorted_lines = sorted(
            summary.active_inventory_line_ids,
            key=lambda line: (
                -(sold_qty_by_product.get(line.product_id.id, 0.0)),
                line.product_id.display_name or ''
            )
        )

        items = []
        for idx, line in enumerate(sorted_lines):
            items.append({
                'product_id': line.product_id.id,
                'name': line.product_id.display_name,
                'price': line.price_unit,
                'remaining': line.remaining_qty,
                'image_url': f'/web/image?model=van.product&id={line.product_id.id}&field=image_1920',
                'sort_order': idx,
                'sold_qty': sold_qty_by_product.get(line.product_id.id, 0.0),
            })
        return items

    @http.route('/van/pos/get_all_products', type='jsonrpc', auth='user')
    def get_all_products(self):
        products = request.env['van.product'].with_context(lang='uz_UZ').sudo().search([('active', '=', True)])
        return [{
            'product_id': p.id,
            'name': p.display_name,
            'price': p.list_price,
            'sale_price': p.list_price,
            'cost_price': p.cost_price,
            'image_url': f'/web/image?model=van.product&id={p.id}&field=image_1920',
        } for p in products]

    @http.route('/van/pos/sync_offline', type='jsonrpc', auth='user')
    def sync_offline(self, transactions=None):
        """
        Batches offline transactions (sales, kirim, chiqim).
        Ensures idempotency using 'offline_id'.
        Input format: [{'type': 'sale', 'offline_id': 'abc...', 'data': {...}}, ...]
        """
        if not transactions:
            return {'status': 'success', 'synced': [], 'errors': []}
            
        synced_ids = []
        errors = []
        
        env = request.env
        
        for idx, tx in enumerate(transactions):
            tx_type = tx.get('type')
            offline_id = tx.get('offline_id')
            data = tx.get('data', {})
            
            if not offline_id:
                errors.append({'index': idx, 'error': 'Missing offline_id'})
                continue
                
            try:
                if tx_type == 'sale':
                    # Check Idempotency
                    existing = env['van.pos.order'].sudo().search([('offline_id', '=', offline_id)], limit=1)
                    if existing:
                        synced_ids.append(offline_id)
                        continue
                        
                    partner_id = data.get('partner_id')
                    part_agent_id = self._get_agent_id()
                    agent_id = part_agent_id
                    lines = data.get('lines', [])
                    
                    if not lines:
                        raise ValueError("No products in sale")
                        
                    # Create Order
                    order_vals = {
                        'partner_id': partner_id,
                        'agent_id': agent_id,
                        'offline_id': offline_id,
                        'line_ids': [(0, 0, {
                            'product_id': l['product_id'],
                            'qty': l['qty'],
                            'price_unit': l['price'],
                        }) for l in lines]
                    }
                    
                    # Apply historical date if provided
                    tx_date = tx.get('timestamp')
                    if tx_date:
                        # Convert ISO String '2026-03-07T12:51:35.386Z' to '%Y-%m-%d %H:%M:%S'
                        if 'T' in tx_date:
                            tx_date = tx_date.split('.')[0].replace('T', ' ')
                        order_vals['date'] = tx_date
                        
                    order = env['van.pos.order'].sudo().create(order_vals)
                    order.action_confirm_order()
                    synced_ids.append(offline_id)
                    
                elif tx_type in ['kirim', 'chiqim']:
                    # Check Idempotency
                    existing = env['van.payment'].sudo().search([('offline_id', '=', offline_id)], limit=1)
                    if existing:
                        synced_ids.append(offline_id)
                        continue
                        
                    payment_type = 'in' if tx_type == 'kirim' else 'out'
                    vals = {
                        'payment_type': payment_type,
                        'agent_id': self._get_agent_id(),
                        'offline_id': offline_id,
                        'amount': float(data.get('amount', 0)),
                        'note': data.get('note', ''),
                        'payment_method': data.get('payment_method', 'cash')
                    }
                    
                    if payment_type == 'in':
                        vals['partner_id'] = data.get('partner_id')
                    else:
                        vals['expense_type'] = data.get('expense_type', 'daily')
                        
                    if tx.get('timestamp'):
                        tx_date = tx.get('timestamp')
                        if 'T' in tx_date:
                            tx_date = tx_date.split('.')[0].replace('T', ' ')
                        vals['date'] = tx_date
                        
                    env['van.payment'].sudo().create(vals)
                    synced_ids.append(offline_id)
                    
                else:
                    errors.append({'offline_id': offline_id, 'error': f"Unknown type {tx_type}"})
                    
            except Exception as e:
                _logger.error(f"Error syncing offline transaction {offline_id}: {str(e)}")
                errors.append({'offline_id': offline_id, 'error': str(e)})
                
        return {
            'status': 'success' if len(errors) == 0 else 'partial_success',
            'synced': synced_ids,
            'errors': errors
        }

    @http.route('/van/pos/submit_order', type='jsonrpc', auth='user')
    def submit_order(self, partner_id, lines):
        """
        lines = [{'product_id': ID, 'qty': QTY, 'price': PRICE}]
        """
        try:
            order_vals = {
                'agent_id': self._get_agent_id(),
                'partner_id': partner_id if partner_id else False,
                'line_ids': [(0, 0, {
                    'product_id': l['product_id'],
                    'qty': l['qty'],
                    'price_unit': l['price']
                }) for l in lines]
            }
            order = request.env['van.pos.order'].create(order_vals)
            order.action_confirm_order()
            
            return {
                'success': True,
                'order_id': order.id,
                'nasiya_id': order.nasiya_id.id,
                'nasiya_amount': order.nasiya_id.amount_total
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route('/van/pos/submit_kirim', type='jsonrpc', auth='user')
    def submit_kirim(self, nasiya_id, amount, payment_method='cash'):
        nasiya = request.env['van.nasiya'].browse(nasiya_id)
        if not nasiya.exists():
            return {'success': False, 'error': 'Nasiya not found'}
            
        payment = request.env['van.payment'].create({
            'partner_id': nasiya.partner_id.id,
            'agent_id': self._get_agent_id(),
            'nasiya_id': nasiya.id,
            'payment_type': 'in',
            'payment_method': payment_method,
            'amount': amount,
        })
        
        return {'success': True, 'payment_id': payment.id}

    @http.route('/van/pos/submit_quick_action', type='jsonrpc', auth='user')
    def submit_quick_action(self, type, amount, note='', partner_id=None, expense_type='daily'):
        try:
            payment_vals = {
                'agent_id': self._get_agent_id(),
                'payment_type': 'in' if type == 'kirim' else 'out',
                'expense_type': expense_type if type == 'chiqim' else False,
                'amount': float(amount),
                'payment_method': 'cash',
                'note': note,
            }
            if partner_id and type == 'kirim':
                payment_vals['partner_id'] = partner_id
                
            payment = request.env['van.payment'].create(payment_vals)
            return {'success': True, 'payment_id': payment.id}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route('/van/pos/get_requests', type='jsonrpc', auth='user')
    def get_requests(self):
        try:
            import pytz
            user_tz = pytz.timezone(request.env.user.tz or 'Asia/Tashkent')
            # Filter by current agent so each agent sees only their own requests in Mobile POS
            agent_id = self._get_agent_id()
            domain = [('agent_id', '=', agent_id)]
            reqs = request.env['van.request'].sudo().search(domain, order='date desc', limit=200)
            res = []
            for req in reqs:
                lines = []
                total_amount = 0.0
                for l in req.line_ids:
                    # Use stored price if available, otherwise fall back to list_price
                    price = l.price if l.price else (l.product_id.list_price or 0.0)
                    subtotal = l.subtotal if l.subtotal else (price * l.qty)
                    total_amount += subtotal
                    lines.append({
                        'product_id': l.product_id.id,          # CRITICAL: must be included
                        'product_name': l.product_id.name,
                        'qty': l.qty,
                        'price': price,
                        'subtotal': subtotal,
                        'image_url': f'/web/image?model=van.product&id={l.product_id.id}&field=image_1920'
                    })

                local_date_str = ''
                if req.date:
                    local_dt = pytz.utc.localize(req.date).astimezone(user_tz)
                    local_date_str = local_dt.strftime('%Y-%m-%d %H:%M:%S')

                res.append({
                    'id': req.id,
                    'name': req.name,
                    'agent_id': req.agent_id.id if req.agent_id else False,
                    'date': local_date_str,
                    'partner_id': req.partner_id.id if req.partner_id else False,
                    'partner_name': req.partner_id.name if req.partner_id else '',
                    'state': req.state,
                    'total_amount': total_amount,
                    'lines': lines,
                    'notes': req.notes or ''
                })
            return {'success': True, 'requests': res}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route('/van/pos/update_request_state', type='jsonrpc', auth='user')
    def update_request_state(self, request_id, state):
        try:
            # Sudo allows agents to update any request state, even if they didn't create it
            req = request.env['van.request'].sudo().search([('id', '=', int(request_id))])
            if req:
                req.sudo().write({'state': state})
                return {'success': True}
            return {'success': False, 'error': "So'rov topilmadi yoki ruxsat yo'q"}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route('/van/pos/submit_request', type='jsonrpc', auth='user')
    def submit_request(self, partner_id, lines, notes=''):
        try:
            if not partner_id:
                return {'success': False, 'error': "Mijozni tanlash so'rov qoldirish uchun majburiy!"}

            request_vals = {
                'agent_id': self._get_agent_id(),
                'partner_id': partner_id,
                'notes': notes,
                'line_ids': [(0, 0, {
                    'product_id': l['product_id'],
                    'qty': float(l['qty'])
                }) for l in lines]
            }
            # Use sudo() to bypass strict creation rules for POS users
            new_request = request.env['van.request'].sudo().create(request_vals)
            return {'success': True, 'request_id': new_request.id}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route('/van/pos/fulfill_request', type='jsonrpc', auth='user')
    def fulfill_request(self, request_id):
        """Mark a So'rov as fulfilled. Called after the sale is already created via submit_order."""
        try:
            req = request.env['van.request'].sudo().search([('id', '=', int(request_id))])
            if not req:
                return {'success': False, 'error': "So'rov topilmadi"}
            if req.state == 'done':
                return {'success': True}  # Already done, idempotent
            req.sudo().write({
                'state': 'done',
                'fulfilled_date': fields.Datetime.now(),
            })
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route('/van/pos/update_request', type='jsonrpc', auth='user')
    def update_request(self, request_id, lines):
        try:
            req = request.env['van.request'].sudo().search([('id', '=', int(request_id))])
            if not req:
                return {'success': False, 'error': "So'rov topilmadi"}

            if req.state != 'draft':
                return {'success': False, 'error': "Faqat kutilayotgan so'rovlarni o'zgartirish mumkin"}

            # Validate all lines have product_id before doing anything
            for l in lines:
                pid = l.get('product_id')
                if not pid:
                    return {'success': False, 'error': "Barcha qatorlarda mahsulot bo'lishi kerak!"}

            # Rebuild lines via ORM commands: (5,0,0) clears existing, then add new
            line_commands = [(5, 0, 0)]
            for l in lines:
                line_commands.append((0, 0, {
                    'product_id': int(l['product_id']),
                    'qty': float(l.get('qty', 1)),
                    'price': float(l.get('price', 0.0))
                }))

            req.sudo().write({'line_ids': line_commands})
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route('/van/pos/get_current_agent', type='jsonrpc', auth='user')
    def get_current_agent(self):
        try:
            agent_id = self._get_agent_id()
            user = request.env['res.users'].sudo().browse(agent_id)
            if user.has_group('van_sales_pharma.group_van_agent') or user.has_group('base.group_system'):
                # Get the summary ID for this agent
                summary = request.env['van.agent.summary'].sudo().search([('agent_id', '=', user.id)], limit=1)
                if not summary:
                    summary = request.env['van.agent.summary'].sudo().create({'agent_id': user.id})
                summary_id = summary.id
                
                # Check if currently acting as an admin
                is_admin = request.env.user.has_group('van_sales_pharma.group_van_admin') or request.env.user.has_group('base.group_system')
                is_admin_mode = bool(is_admin and request.session.get('acting_as_agent_id'))

                return {
                    'id': user.id,
                    'summary_id': summary_id,
                    'name': user.name,
                    'phone': user.phone or '',
                    'oylik_balansi': user.oylik_balansi,
                    'default_taminotchi_id': user.default_taminotchi_id.id if user.default_taminotchi_id else False,
                    'default_taminotchi_name': user.default_taminotchi_id.name if user.default_taminotchi_id else '',
                    'image_url': f'/web/image?model=res.users&id={user.id}&field=avatar_128',
                    'is_admin_mode': is_admin_mode,
                    'is_admin': is_admin
                }
            return None
        except Exception as e:
            return None

    @http.route('/van/pos/get_taminotchis', type='jsonrpc', auth='user')
    def get_taminotchis(self):
        taminotchis = request.env['van.taminotchi'].sudo().search([])
        return [{
            'id': t.id,
            'name': t.name,
        } for t in taminotchis]

    @http.route('/van/pos/submit_trip', type='jsonrpc', auth='user')
    def submit_trip(self, agent_id, date, note, lines, taminotchi_id=None):
        try:
            if not agent_id:
                return {'success': False, 'error': "Agentni tanlash majburiy!"}
            if not lines:
                return {'success': False, 'error': "Hech qanday mahsulot tanlanmadi!"}

            # Get internal location for the trip
            location = request.env['stock.location'].sudo().search([
                ('usage', '=', 'internal'), 
                ('company_id', 'in', [request.env.company.id, False])
            ], limit=1)

            if not location:
                return {'success': False, 'error': "Ombor topilmadi!"}

            # Fetch Taminotchi
            if taminotchi_id:
                taminotchi = request.env['van.taminotchi'].sudo().browse(int(taminotchi_id))
            else:
                agent = request.env['res.users'].sudo().browse(int(agent_id))
                taminotchi = agent.default_taminotchi_id
            
            if not taminotchi or not taminotchi.exists():
                return {'success': False, 'error': "Sizga taminotchi biriktirilmagan. Iltimos, taminotchini tanlang yoki administratorga murojaat qiling."}

            if date and len(date) == 10:
                current_time = datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M:%S')
                date = f"{date} {current_time}"

            trip_vals = {
                'taminotchi_id': taminotchi.id,
                'agent_id': int(agent_id),
                'location_id': location.id,
                'date': date,
                'note': note or '',
                'state': 'draft',
                'trip_line_ids': [(0, 0, {
                    'product_id': l['product_id'],
                    'loaded_qty': float(l['qty']),
                    'price_unit': request.env['van.product'].sudo().browse(l['product_id']).cost_price,
                    'sale_price_unit': request.env['van.product'].sudo().browse(l['product_id']).list_price,
                }) for l in lines]
            }
            
            # Sudo is needed because agents may not natively have creation rights on other agents
            new_trip = request.env['van.trip'].sudo().create(trip_vals)
            
            # Auto validate the trip to push quantities into van.agent.inventory
            new_trip.sudo().action_validate()
            
            return {'success': True, 'trip_id': new_trip.id}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route('/van/pos/get_trips', type='jsonrpc', auth='user')
    def get_trips(self):
        try:
            import pytz
            user_tz = pytz.timezone(request.env.user.tz or 'Asia/Tashkent')
            
            # Fetch trips associated with the current agent
            agent_id = self._get_agent_id()
            trips = request.env['van.trip'].sudo().search([('agent_id', '=', agent_id)], order='date desc, id desc', limit=100)
            res = []
            
            for trip in trips:
                local_date_str = ''
                if trip.date:
                    if isinstance(trip.date, datetime.datetime):
                        local_dt = pytz.utc.localize(trip.date).astimezone(user_tz)
                        local_date_str = local_dt.strftime('%Y-%m-%d %H:%M')
                    else:
                        local_date_str = trip.date.strftime('%Y-%m-%d %H:%M')
                        
                res.append({
                    'id': trip.id,
                    'name': trip.name,
                    'date': local_date_str,
                    'agent_name': trip.agent_id.name if trip.agent_id else '',
                    'state': trip.state,
                    'total_cost': trip.amount_cost_total,
                    'total_qty': trip.x_loaded_qty,
                    'lines': [{
                        'product_name': l.product_id.name,
                        'qty': l.loaded_qty,
                        'price': l.price_unit,
                        'subtotal': l.loaded_qty * l.product_id.cost_price, # Cost subtotal
                        'image_url': f'/web/image?model=van.product&id={l.product_id.id}&field=image_1920'
                    } for l in trip.trip_line_ids],
                    'note': trip.note or ''
                })
            return {'success': True, 'trips': res}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ==========================================
    # CLIENT TELEGRAM WEB APP ROUTES (PUBLIC)
    # ==========================================

    @http.route('/van/public/image/<int:product_id>', type='http', auth='public', cors='*')
    def public_product_image(self, product_id, **kwargs):
        """Serve product images to public WebApp without session auth restrictions"""
        product = request.env['van.product'].sudo().browse(product_id)
        if not product.exists() or not product.image_1920:
            return request.not_found()
            
        import base64
        try:
            image_base64 = base64.b64decode(product.image_1920)
            headers = [
                ('Content-Type', 'image/jpeg'),
                ('Content-Length', str(len(image_base64)))
            ]
            return request.make_response(image_base64, headers)
        except Exception:
            return request.not_found()

    @http.route('/van/client/request', type='http', auth='public', website=True, cors='*')
    def client_request_page(self, chat_id=None, **kwargs):
        if not chat_id:
            return "Telegram Chat ID is missing. Iltimos bot orqali kiring."
            
        # Validate partner
        partner = request.env['res.partner'].sudo().search([('telegram_chat_id', '=', str(chat_id))], limit=1)
        if not partner:
            return "Kechirasiz, sizning hisobingiz topilmadi. Iltimos botdan qayta ro'yxatdan o'ting."
            
        base_url = request.env['ir.config_parameter'].sudo().get_param('van_telegram_odoo_url', request.env['ir.config_parameter'].sudo().get_param('web.base.url', ''))
        if not base_url.startswith('http'):
            base_url = "https://" + base_url.lstrip('/')
        elif base_url.startswith('http://') and not ('localhost' in base_url or '127.0.0.1' in base_url):
            base_url = base_url.replace('http://', 'https://')
        base_url = base_url.rstrip('/')
        
        # Get active products in the client's language to prevent translation mismatches
        products = request.env['van.product'].sudo().with_context(lang='uz_UZ').search([])
        product_data = []
        for p in products:
            product_data.append({
                'id': p.id,
                'name': p.name,
                'price': p.list_price,
                'price_str': f"{p.list_price:,.0f}",
                'image_url': f"{base_url}/van/public/image/{p.id}" if p.image_1920 else ""
            })
            
        import json
        products_dict = {p['id']: p for p in product_data}
        values = {
            'partner_id': partner.id,
            'partner_name': partner.name,
            'products': product_data,
            'products_json': json.dumps(products_dict),
            'odoo_url': base_url
        }
        
        headers = [
            ('Cache-Control', 'no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0'),
            ('Pragma', 'no-cache'),
            ('Expires', '0')
        ]
        return request.render('van_sales_pharma.client_request_template', values, headers=headers)

    @http.route('/van/client/submit_request', type='jsonrpc', auth='public', csrf=False, cors='*')
    def client_submit_request(self, partner_id, lines, notes=''):
        try:
            if not partner_id:
                return {'success': False, 'error': 'Missing partner ID'}
            
            partner = request.env['res.partner'].sudo().browse(int(partner_id))
            if not partner.exists():
                return {'success': False, 'error': 'Partner not found'}
                
            # Create request without an agent originally. 
            # Later we can assign to an active agent in that region or leave it generic for office.
            # We'll assign it to the admin User for now, or just leave agent_id empty if schema permits.
            # Usually we need an agent_id. Let's find the first valid agent.
            admin = request.env.ref('base.user_admin')
            
            request_vals = {
                'agent_id': admin.id, 
                'partner_id': partner.id,
                'notes': f"TELEGRAM WEB APP ORQALI:\n{notes}",
                'line_ids': [(0, 0, {
                    'product_id': l['product_id'],
                    'qty': float(l['qty'])
                }) for l in lines]
            }
            
            new_request = request.env['van.request'].sudo().create(request_vals)
            
            # Attach Web App Button for Zakaz Berish
            base_url = request.env['ir.config_parameter'].sudo().get_param('van_telegram_odoo_url', request.env['ir.config_parameter'].sudo().get_param('web.base.url', ''))
            if not base_url.startswith('http'):
                base_url = "https://" + base_url.lstrip('/')
            elif base_url.startswith('http://') and not ('localhost' in base_url or '127.0.0.1' in base_url):
                base_url = base_url.replace('http://', 'https://')
            base_url = base_url.rstrip('/')
            
            import time
            web_app_url = f"{base_url}/van/client/request?chat_id={partner.telegram_chat_id}&v={int(time.time())}"
            button = {"text": "🛒 Zakaz berish", "web_app": {"url": web_app_url}}
            reply_markup = {"inline_keyboard": [[button]]}

            # Send confirmation message to client
            msg = f"✅ <b>Sizning so'rovingiz qabul qilindi!</b>\n\n🔖 Raqam: #{new_request.id}\nBiz tez orada siz bilan bog'lanamiz."
            request.env['van.telegram.utils'].sudo().send_message(partner.telegram_chat_id, msg, reply_markup=reply_markup)
            
            return {'success': True, 'request_id': new_request.id}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route('/van/mijoz/edit-kirim', type='jsonrpc', auth='user')
    def edit_kirim(self, payment_id, new_amount):
        """Edits an existing Kirim payment amount"""
        try:
            payment = request.env['van.payment'].sudo().browse(int(payment_id))
            if not payment.exists() or payment.payment_type != 'in':
                return {'success': False, 'error': 'To\'lov topilmadi yoki bu kirim emas.'}
            
            # Allow admin or the agent who created it
            agent_id = self._get_agent_id()
            user = request.env.user
            is_admin = user.has_group('van_sales_pharma.group_van_admin') or user.has_group('base.group_system')
            
            if not is_admin and payment.agent_id.id != agent_id:
                return {'success': False, 'error': 'Faqat o\'zingizning kiritgan to\'lovingizni tahrirlay olasiz.'}

            try:
                new_amount = float(new_amount)
                if new_amount < 0:
                    raise ValueError
            except:
                return {'success': False, 'error': 'Noto\'g\'ri summa kiritildi.'}

            payment.sudo().write({'amount': new_amount})
            
            # Recompute balances since payment changed
            if payment.partner_id:
                payment.partner_id.sudo()._compute_van_nasiya_stats()
                
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route('/van/mijoz/delete-kirim', type='jsonrpc', auth='user')
    def delete_kirim(self, payment_id):
        """Deletes an existing Kirim payment"""
        try:
            payment = request.env['van.payment'].sudo().browse(int(payment_id))
            if not payment.exists() or payment.payment_type != 'in':
                return {'success': False, 'error': 'To\'lov topilmadi yoki bu kirim emas.'}
            
            # Allow admin or the agent who created it
            agent_id = self._get_agent_id()
            user = request.env.user
            is_admin = user.has_group('van_sales_pharma.group_van_admin') or user.has_group('base.group_system')
            
            if not is_admin and payment.agent_id.id != agent_id:
                return {'success': False, 'error': 'Faqat o\'zingizning kiritgan to\'lovingizni o\'chira olasiz.'}

            partner = payment.partner_id
            payment.sudo().unlink()
            
            # Recompute balances since payment was deleted
            if partner:
                partner.sudo()._compute_van_nasiya_stats()
                
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}


    @http.route('/van/mijoz/edit-sotuv', type='jsonrpc', auth='user')
    def edit_sotuv(self, order_id, lines):
        """
        Edits an existing Sotuv.
        lines = [{'line_id': ID, 'qty': QTY, 'price': PRICE}]
        Lines not included are assumed unchanged, except we will update lines provided.
        """
        try:
            order = request.env['van.pos.order'].sudo().browse(int(order_id))
            if not order.exists():
                return {'success': False, 'error': 'Sotuv topilmadi.'}
            
            agent_id = self._get_agent_id()
            user = request.env.user
            is_admin = user.has_group('van_sales_pharma.group_van_admin') or user.has_group('base.group_system')
            
            if not is_admin and order.agent_id.id != agent_id:
                return {'success': False, 'error': 'Faqat o\'zingizning sotuvingizni tahrirlay olasiz.'}

            if order.state != 'done':
                 return {'success': False, 'error': 'Faqat tasdiqlangan sotuvlarni tahrirlash mumkin.'}

            # Group the incoming updates
            updates = {int(l['line_id']): {'qty': float(l['qty']), 'price': float(l['price'])} for l in lines if 'line_id' in l}

            for line in order.line_ids:
                if line.id in updates:
                    new_qty = updates[line.id]['qty']
                    new_price = updates[line.id]['price']
                    
                    if new_qty < 0:
                        return {'success': False, 'error': 'Miqdor manfiy bo\'lishi mumkin emas.'}
                    if new_price < 0:
                        return {'success': False, 'error': 'Narx manfiy bo\'lishi mumkin emas.'}

                    # Diff to adjust stock
                    qty_diff = new_qty - line.qty
                    
                    if qty_diff != 0:
                        summary = request.env['van.agent.summary'].sudo().search([
                            ('agent_id', '=', order.agent_id.id)
                        ], limit=1)
                        inv = request.env['van.agent.inventory.line'].sudo().search([
                            ('summary_id', '=', summary.id),
                            ('product_id', '=', line.product_id.id)
                        ], limit=1) if summary else request.env['van.agent.inventory.line']
                        
                        if qty_diff > 0:
                            available_qty = inv.remaining_qty if inv else 0.0
                            if available_qty < qty_diff:
                                return {'success': False, 'error': f"Agentda {line.product_id.name} uchun yetarli qoldiq yo'q."}
                        
                    # Also write cost_price logic to update subtotal cost
                    line.sudo().write({'qty': new_qty, 'price_unit': new_price})

            # Recompute total amount manually and partner balances
            order.sudo()._compute_amount_total()
            if order.nasiya_id:
                order.nasiya_id.sudo().write({'amount_total': order.amount_total})
            if order.partner_id:
                order.partner_id.sudo()._compute_van_nasiya_stats()
                
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route('/van/mijoz/delete-sotuv', type='jsonrpc', auth='user')
    def delete_sotuv(self, order_id):
        """Deletes an existing Sotuv without any legacy inventory writes."""
        try:
            order = request.env['van.pos.order'].sudo().browse(int(order_id))
            if not order.exists():
                return {'success': False, 'error': 'Sotuv topilmadi.'}
            
            agent_id = self._get_agent_id()
            user = request.env.user
            is_admin = user.has_group('van_sales_pharma.group_van_admin') or user.has_group('base.group_system')
            
            if not is_admin and order.agent_id.id != agent_id:
                return {'success': False, 'error': 'Faqat o\'zingizning sotuvingizni o\'chira olasiz.'}

            partner = order.partner_id

            # Explicitly break linked debt records first so the mobile delete path
            # stays independent from any legacy inventory rollback logic.
            if order.nasiya_id:
                nasiya = order.nasiya_id.sudo()
                order.sudo().write({'nasiya_id': False})
                nasiya.unlink()

            if order.line_ids:
                order.line_ids.sudo().unlink()

            order.sudo().unlink()
            
            # Recompute balances since sale was deleted
            if partner:
                partner.sudo()._compute_van_nasiya_stats()
                
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route('/van/debug/check-inventory', type='http', auth='user')
    def check_agent_inventory(self, agent_id=None):
        """
        Diagnose inventory mismatch. Compares reconstructed 'Yuklash' history vs actual loaded_qty.
        Only accessible by admins.
        """
        if not request.env.user.has_group('van_sales_pharma.group_van_admin'):
            return "Huquq yetarli emas"
            
        agent = request.env['res.users'].sudo().browse(int(agent_id)) if agent_id else request.env.user
        
        # 1. Calculate Expected from Trips
        trips = request.env['van.trip'].sudo().search([
            ('agent_id', '=', agent.id),
            ('state', '=', 'validated')
        ])
        
        expected_loader = {}
        for trip in trips:
            for line in trip.trip_line_ids:
                pid = line.product_id.id
                if pid not in expected_loader:
                    expected_loader[pid] = {'name': line.product_id.name, 'qty': 0}
                expected_loader[pid]['qty'] += line.loaded_qty
                
        # 2. Extract Actual from Inventory Profile
        summary = request.env['van.agent.summary'].sudo().search([('agent_id', '=', agent.id)], limit=1)
        actual_loader = {}
        if summary:
            for inv_line in summary.inventory_line_ids:
                actual_loader[inv_line.product_id.id] = inv_line.loaded_qty
                
        # 3. Render HTML Table
        html = f"<html><head><style>table, th, td {{border: 1px solid black; border-collapse: collapse; padding: 5px;}} th {{background-color: #f2f2f2;}} .err {{color: red; font-weight: bold;}}</style></head><body>"
        html += f"<h2>[{agent.name}] Inventar Diagnostikasi</h2>"
        html += "<p><b>Diqqat:</b> Ushbu jadval baza tarixi (Sayohatlar) va tizimdagi joriy 'Yuklangan Miqdor' o'rtasidagi farqni ko'rsatadi.</p>"
        html += "<table><tr><th>ID</th><th>Mahsulot nomi</th><th>Kutilyotgan (Sayohatlardan)</th><th>Haqiqiy (Bazadagi)</th><th>Farq</th></tr>"
        
        all_pids = set(expected_loader.keys()).union(set(actual_loader.keys()))
        has_error = False
        
        for pid in sorted(list(all_pids)):
            exp = expected_loader.get(pid, {}).get('qty', 0.0)
            name = expected_loader.get(pid, {}).get('name', 'Noma\'lum')
            if pid not in expected_loader and pid in actual_loader:
                name = request.env['van.product'].sudo().browse(pid).name
            
            act = actual_loader.get(pid, 0.0)
            diff = exp - act
            
            err_class = "err" if diff != 0 else ""
            if diff != 0:
                has_error = True
                
            html += f"<tr><td>{pid}</td><td>{name}</td><td>{exp}</td><td>{act}</td><td class='{err_class}'>{diff}</td></tr>"
            
        html += "</table><br/>"
        if has_error:
            html += "<p style='color:red;'><b>DIQQAT: Farq topildi!</b> Buni to'g'irlash uchun 'Sotuvlar' menegeridan Agent sahifasiga o'tib 'Inventarni Qayta Tiklash' tugmasini bosing.</p>"
        else:
            html += "<p style='color:green;'><b>Barcha ma'lumotlar to'g'ri!</b> Baza qoldiqlari tarix bilan mos keladi.</p>"
            
        html += "</body></html>"
        html += "</body></html>"
        return request.make_response(html)

    # ==========================
    # POS CRUD For Payment History
    # ==========================
    @http.route('/van/pos/get_payments', type='jsonrpc', auth='user')
    def get_pos_payments(self, payment_type, **kw):
        """
        payment_type: 'in' (Kirim) or 'out' (Chiqim)
        Returns the history of payments for the current agent.
        """
        try:
            import pytz
            agent_id = self._get_agent_id()
            user_tz = pytz.timezone(request.env.user.tz or 'Asia/Tashkent')
            domain = [('agent_id', '=', agent_id), ('payment_type', '=', payment_type)]
            payments = request.env['van.payment'].sudo().search(domain, order='date desc')
            
            res = []
            for p in payments:
                local_date_str = ''
                if p.date:
                    if getattr(p.date, 'tzinfo', None):
                        local_dt = p.date.astimezone(user_tz)
                    else:
                        local_dt = pytz.utc.localize(p.date).astimezone(user_tz)
                    local_date_str = local_dt.strftime('%Y-%m-%d %H:%M')
                res.append({
                    'id': p.id,
                    'name': p.name,
                    'amount': p.amount,
                    'date': local_date_str,
                    'note': p.note or '',
                    'expense_type': p.expense_type if payment_type == 'out' else False,
                    'partner_id': p.partner_id.id if p.partner_id else False,
                    'partner_name': p.partner_id.name if p.partner_id else '',
                    'state': p.state,
                })
            return {'success': True, 'payments': res}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route('/van/pos/save_payment', type='jsonrpc', auth='user')
    def save_pos_payment(self, payment_type, amount, note='', payment_id=False, partner_id=False, expense_type='daily', **kw):
        """ Creates or updates a van.payment record (Kirim/Chiqim) """
        try:
            agent_id = self._get_agent_id()
            amount = float(amount)
            if amount <= 0:
                return {'success': False, 'error': "Summa noto'g'ri kiritildi."}
                
            name = _('Payment')
            if payment_type == 'in':
                name = _('Kirim (Mobile POS)')
            elif payment_type == 'out':
                name = _('Chiqim (Mobile POS)')

            if payment_id:
                # Update
                payment = request.env['van.payment'].sudo().browse(int(payment_id))
                if payment.agent_id.id != agent_id: # Use agent_id from _get_agent_id()
                    return {'success': False, 'error': "Ruxsat yo'q!"}
                
                vals = {
                    'name': name,
                    'amount': amount,
                    'note': note,
                    'partner_id': int(partner_id) if partner_id else False,
                    'expense_type': expense_type if payment_type == 'out' else False,
                }
                payment.sudo().write(vals)
                return {'success': True, 'payment_id': payment.id}
            else:
                # Create
                payment = request.env['van.payment'].sudo().create({
                    'name': name,
                    'agent_id': agent_id,
                    'partner_id': int(partner_id) if partner_id else False,
                    'payment_type': payment_type,
                    'amount': amount,
                    'date': fields.Datetime.now(),
                    'note': note,
                    'expense_type': expense_type if payment_type == 'out' else False,
                    'state': 'received'
                })
                return {'success': True, 'payment_id': payment.id}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route('/van/pos/delete_payment', type='jsonrpc', auth='user')
    def delete_pos_payment(self, payment_id, **kw):
        try:
            agent_id = self._get_agent_id()
            payment = request.env['van.payment'].sudo().browse(int(payment_id))
            if payment.agent_id.id != agent_id:
                return {'success': False, 'error': "Sizda bu yozuvni o'chirish huquqi yo'q!"}
            if payment.state == 'confirmed':
                return {'success': False, 'error': "Tasdiqlangan to'lovni o'chirib bo'lmaydi!"}
            
            partner = payment.partner_id
            payment.sudo().unlink()
            
            # Recalculate debt if it was a client Kirim
            if partner:
                partner.sudo()._compute_van_nasiya_stats()
                
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}
