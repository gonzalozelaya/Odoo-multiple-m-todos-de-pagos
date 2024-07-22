# -*- coding: utf-8 -*-

from odoo import models, fields, api

class Account_payment_methods(models.Model):
    _inherit = 'account.payment'
    
    to_pay_move_line_ids = fields.Many2many(
        comodel_name='account.move.line',
        relation='account_payment_methods_move_line_rel',
        column1='payment_method_id',
        column2='move_line_id',
        string='Move Lines to Pay'
    )
