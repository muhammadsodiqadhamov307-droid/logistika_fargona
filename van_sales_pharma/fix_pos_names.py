import xmlrpc.client
url = 'http://localhost:8069'
db = 'default'
username = 'admin'
password = '1'

common = xmlrpc.client.ServerProxy('{}/xmlrpc/2/common'.format(url))
try:
    uid = common.authenticate(db, username, password, {})
    if uid:
        models = xmlrpc.client.ServerProxy('{}/xmlrpc/2/object'.format(url))
        orders = models.execute_kw(db, uid, password, 'van.pos.order', 'search_read', [[['name', '=', 'New']]], {'fields': ['id']})
        for order in orders:
            # We can't easily call next_by_code via external API without a custom method.
            # But wait, we can just run odoo shell instead of xmlrpc!
            pass
except Exception as e:
    pass
