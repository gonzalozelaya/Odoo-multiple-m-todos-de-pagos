# -*- coding: utf-8 -*-

from odoo import models, fields, api

class Account_payment_methods(models.Model):
    _name = 'account.payment.multiplemethods'
    _check_company_auto = True
    
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    company_currency_id = fields.Many2one(
        'res.currency',
        string='Company Currency',
        compute='_compute_currency_id',
        store=True
    )

    name = fields.Char(string='name')
    partner_type = fields.Selection([
        ('customer', 'Customer'),
        ('supplier', 'Vendor'),
    ], default='customer', tracking=True, required=True)
    payment_reference = fields.Char(string="Payment Reference", copy=False, tracking=True,
        help="Reference of the document used to issue this payment. Eg. check number, file name, etc.")
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string="Customer/Vendor",
        store=True, readonly=False, ondelete='restrict',
        tracking=True,)

    to_pay_move_line_ids = fields.Many2many(
            'account.move.line',
            'account_move_line_payment_to_pay_multiple_rel',
            'multiple_payment_id',
            'to_pay_line_id',
            string="To Pay Lines",
             store=True,
            help='This lines are the ones the user has selected to be paid.',
            copy=False,
            readonly=False,
        )
    state = fields.Selection([
        ('debts', 'Elegir Deudas'),
        ('payments', 'Añadir Pagos'),
        ('draft', 'Borrador'),
        ('posted', 'Publicado'),
        ('cancelled', 'Cancelado'),
    ], string='Status', default='debts', tracking=True)

    selected_debt = fields.Monetary(
        # string='To Pay lines Amount',
        string='Selected Debt',
        compute='_compute_selected_debt',
        currency_field='company_currency_id',
    )
    unreconciled_amount = fields.Monetary(
        string='Adjustment / Advance',
        currency_field='company_currency_id',
    )
    # reconciled_amount = fields.Monetary(compute='_compute_amounts')
    to_pay_amount = fields.Monetary(
        compute='_compute_to_pay_amount',
        inverse='_inverse_to_pay_amount',
        string='To Pay Amount',
        # string='Total To Pay Amount',
        readonly=True,
        tracking=True,
        currency_field='company_currency_id',
    )

    ###COMPUTE METHODS
    @api.depends('company_id')
    def _compute_currency_id(self):
        for record in self:
            record.company_currency_id = record.company_id.currency_id
            
    @api.depends('to_pay_move_line_ids', 'to_pay_move_line_ids.amount_residual')
    def _compute_selected_debt(self):
        for rec in self:
            # factor = 1
            rec.selected_debt = sum(rec.to_pay_move_line_ids._origin.mapped('amount_residual')) * (-1.0 if rec.partner_type == 'supplier' else 1.0)
            # TODO error en la creacion de un payment desde el menu?
            # if rec.payment_type == 'outbound' and rec.partner_type == 'customer' or \
            #         rec.payment_type == 'inbound' and rec.partner_type == 'supplier':
            #     factor = -1
            # rec.selected_debt = sum(rec.to_pay_move_line_ids._origin.mapped('amount_residual')) * factor

    @api.depends(
        'selected_debt', 'unreconciled_amount')
    def _compute_to_pay_amount(self):
        for rec in self:
            rec.to_pay_amount = rec.selected_debt + rec.unreconciled_amount

    @api.onchange('to_pay_amount')
    def _inverse_to_pay_amount(self):
        for rec in self:
            rec.unreconciled_amount = rec.to_pay_amount - rec.selected_debt


    def ConfirmDebts(self):
        return