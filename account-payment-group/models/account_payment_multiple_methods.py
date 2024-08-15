# -*- coding: utf-8 -*-

from odoo import models, fields, api

class Account_payment_methods(models.Model):
    _name = 'account.payment.multiplemethods'
    _inherit = 'account.payment'
    