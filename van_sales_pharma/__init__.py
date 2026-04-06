from .hooks import post_init_hook
from . import models
from . import wizards
from . import controllers

# --- Monkey Patch for Werkzeug WebSocket Connections on Odoo 17+ ---
import logging
_logger = logging.getLogger(__name__)

try:
    from odoo.service.server import RequestHandler
    from io import BytesIO

    def send_header_safe(self, keyword, value):
        headers = getattr(self, 'headers', {})
        if headers and headers.get('Upgrade') == 'websocket' and keyword == 'Connection' and value == 'close':
            self.close_connection = True
            return
        super(RequestHandler, self).send_header(keyword, value)

    def end_headers_safe(self, *a, **kw):
        super(RequestHandler, self).end_headers(*a, **kw)
        headers = getattr(self, 'headers', {})
        if headers and headers.get('Upgrade') == 'websocket':
            self.rfile = BytesIO()
            self.wfile = BytesIO()

    RequestHandler.send_header = send_header_safe
    RequestHandler.end_headers = end_headers_safe
    _logger.info("Successfully patched odoo.service.server.RequestHandler for websocket upgrade handling.")
except Exception as e:
    _logger.warning(f"Failed to patch RequestHandler for websocket: {e}")
# -------------------------------------------------------------------
