# -*- coding: utf-8 -*-

from odoo import models, fields, api

class Account_payment_methods(models.Model):
    _name = 'account.payment_methods'
    
    _inherit = 'account.payment'
