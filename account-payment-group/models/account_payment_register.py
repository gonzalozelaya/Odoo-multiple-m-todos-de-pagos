from odoo import models, fields

class CustomAccountPaymentRegister(models.TransientModel):
    _name = 'custom.account.payment.register'
    _inherit = 'account.payment.register'

    line_ids = fields.Many2many('account.move.line', 'account_payment_register_move_line_multiple_rel', 'wizard_id', 'line_id',
        string="Journal items", readonly=True, copy=False,)