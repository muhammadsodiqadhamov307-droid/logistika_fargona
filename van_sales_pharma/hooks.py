from odoo import SUPERUSER_ID, api


def post_init_hook(env):
    if not isinstance(env, api.Environment):
        env = api.Environment(env.cr, SUPERUSER_ID, {})

    env['van.product'].sudo().action_sync_all_pos_products()
    env['pos.config'].sudo().action_ensure_default_kassa_config()
