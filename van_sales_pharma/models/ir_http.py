# -*- coding: utf-8 -*-
from odoo import models
from odoo.http import request

class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        result = super(IrHttp, self).session_info()
        # Ensure we don't crash if called outside a request context
        if request and request.session.uid:
            user = request.env.user
            # Check if this user is purely an agent (no admin rights)
            is_admin = user.has_group('van_sales_pharma.group_van_admin') or user.has_group('base.group_system')
            is_agent = user.has_group('van_sales_pharma.group_van_agent')
            
            result['is_van_agent'] = is_agent and not is_admin
        else:
            result['is_van_agent'] = False
            
        return result
