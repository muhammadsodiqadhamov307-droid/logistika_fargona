# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

class VanSalesPWA(http.Controller):


    @http.route('/van/app', type='http', auth='public')
    def van_app_entry(self, **kw):
        # Redirect unauthenticated users to login, with return URL set back to /van/app
        if not request.session.uid:
            return request.redirect('/web/login?redirect=/van/app')
            
        user = request.env.user
        is_admin = user.has_group('van_sales_pharma.group_van_admin') or user.has_group('base.group_system')
        is_agent = user.has_group('van_sales_pharma.group_van_agent')
        
        # Agents go strictly to Mobile POS
        if is_agent and not is_admin:
            return request.redirect('/web#action=van_sales_pharma.action_van_mobile_pos_app')
            
        # Admins or others go to the Van Sales Dashboard
        return request.redirect('/web#action=van_sales_pharma.action_van_sales_dashboard')

