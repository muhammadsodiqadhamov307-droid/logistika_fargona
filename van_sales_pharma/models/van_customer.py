from odoo import models, fields, api


class ResPartnerVanCustomer(models.Model):
    """
    Van Sales Mijozlar — res.partner ni kengaytirish.
    x_is_van_customer = True bo'lgan kontaktlar POS da ham ko'rinadi.
    """
    _inherit = 'res.partner'

    x_is_van_customer = fields.Boolean(
        string='Van Sales Mijozi',
        default=False,
        index=True,
        help="Bu kontakt Van Sales tizimiga tegishli Mijoz (Apteka).",
    )
    x_latitude = fields.Float(string='Kenglik (Lat)', digits=(10, 7))
    x_longitude = fields.Float(string='Uzunlik (Lng)', digits=(10, 7))
    x_google_maps_url = fields.Char(
        string='Google Maps',
        compute='_compute_google_maps_url',
        store=False,
    )

    @api.depends('x_latitude', 'x_longitude')
    def _compute_google_maps_url(self):
        for rec in self:
            if rec.x_latitude and rec.x_longitude:
                rec.x_google_maps_url = (
                    f'https://www.google.com/maps?q={rec.x_latitude},{rec.x_longitude}'
                )
            else:
                rec.x_google_maps_url = False

    @api.model
    def _load_pos_data_domain(self, data, config):
        """POS faqat Van Sales mijozlarini yuklashi kerak, hamda joriy foydalanuvchini."""
        return ['|', ('x_is_van_customer', '=', True), ('id', '=', self.env.user.partner_id.id)]

    @api.model
    def _load_pos_data_fields(self, config):
        """GPS maydonlarini POS frontendga uzatamiz."""
        fields = super()._load_pos_data_fields(config)
        fields += ['x_latitude', 'x_longitude', 'x_google_maps_url']
        return fields

    @api.model_create_multi
    def create(self, vals_list):
        """Van Sales Mijozlar doimo 'customer_rank' = 1 bo'lishi kerak."""
        for vals in vals_list:
            if vals.get('x_is_van_customer'):
                vals['customer_rank'] = max(vals.get('customer_rank', 0), 1)
        return super().create(vals_list)
