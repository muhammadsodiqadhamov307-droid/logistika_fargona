import xmlrpc.client
url = 'http://localhost:8069'
db = 'default'
username = 'admin'
password = '1'

odoo_code = """
import datetime
# test date vs datetime sorting
lines = [{'date': datetime.date(2026, 3, 3)}, {'date': datetime.datetime(2026, 3, 3, 10, 5)}]
try:
    lines.sort(key=lambda x: x['date'])
    print("Sort Success")
except TypeError as e:
    print("Sort Error:", e)
"""
with open('/tmp/test_sort.py', 'w') as f:
    f.write(odoo_code)
