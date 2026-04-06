# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import os
import shutil
import logging
from odoo.modules.module import get_module_path
from odoo.tools.translate import translation_file_reader

_logger = logging.getLogger(__name__)

def post_init_hook(env):
    """
    Odoo 16+ requires translation files for core modules to be precisely inside 
    the core module's i18n directory in order to be processed for JavaScript 
    bundles. This hook ensures the uz_UZ.po file generated for point_of_sale 
    is copied into point_of_sale's directory.
    """
    _logger.info("Initializing Uzbek translations for Point of Sale...")
    
    # Paths
    my_module_path = get_module_path('pos_uz_translation')
    pos_module_path = get_module_path('point_of_sale')
    
    if not pos_module_path:
        _logger.error("Could not find point_of_sale module path.")
        return
        
    src_po = os.path.join(my_module_path, 'i18n', 'uz_UZ.po')
    dest_dir = os.path.join(pos_module_path, 'i18n')
    dest_po = os.path.join(dest_dir, 'uz_UZ.po')
    
    if not os.path.exists(src_po):
        _logger.error(f"Source translation file not found at {src_po}")
        return
        
    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir)
        
    try:
        shutil.copyfile(src_po, dest_po)
        _logger.info(f"Successfully copied Uzbek translation to {dest_po}")
    except Exception as e:
        _logger.error(f"Failed to copy translation file: {e}")
        return
        
    # Activate language
    langs = env['res.lang'].with_context(active_test=False).search([('code', '=', 'uz_UZ')])
    if not langs:
        _logger.info('Creating uz_UZ language manually.')
        langs = env['res.lang'].create({
            'name': 'Uzbek',
            'code': 'uz_UZ',
            'iso_code': 'uz',
            'url_code': 'uz',
            'active': True,
        })
    else:
        langs.active = True
    
    # Tell Odoo to load translations for point_of_sale
    langs = env['res.lang'].search([('code', '=', 'uz_UZ')])
    try:
        wizard = env['base.language.install'].create({
            'lang_ids': langs.ids,
            'overwrite': True
        })
        wizard.lang_install()
        _logger.info('Translations for uz_UZ have been synchronized into the database.')
    except Exception as e:
        _logger.error(f"Failed to run base.language.install wizard: {e}")
