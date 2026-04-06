# -*- coding: utf-8 -*-
{
    'name': 'Point of Sale - Uzbek Translation',
    'version': '1.0',
    'category': 'Sales/Point of Sale',
    'summary': 'Provides Uzbek translation for the Point of Sale module.',
    'author': 'Logistika',
    'description': """
This module provides the Uzbek translation for the core Point of Sale module.
Install this standalone app on any Odoo instance to automatically apply the translations to the POS app.
    """,
    'depends': ['point_of_sale'],
    'data': [
        # Translations are automatically loaded from the i18n directory.
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'post_init_hook': 'post_init_hook',
}
