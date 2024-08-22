# -*- coding: utf-8 -*-

from odoo import models, fields, api, Command, _
from odoo.exceptions import ValidationError, UserError

class Account_payment_methods(models.Model):
    _name = 'account.payment.multiplemethods'
    date = fields.Date(string='Date')
    
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Empresa',
        required=True,
        default=lambda self: self.env.company,
    ) 
    company_currency_id = fields.Many2one(
        'res.currency',
        string='Divisa',
        compute='_compute_currency_id',
        store=True
    )
    name = fields.Char(string='',compute='_compute_name_sequence',readonly=True)
    sequence_used = fields.Char(String='Sequence',compute='_compute_name_sequence',readonly=True)
    partner_type = fields.Selection([
        ('customer', 'Cliente'),
        ('supplier', 'Proveedor'),
    ], default='supplier', required=True)
    
    payment_reference = fields.Char(string="Referencia de pago", copy=False, tracking=True,
        help="Reference of the document used to issue this payment. Eg. check number, file name, etc.")
    
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string="Proveedor",
        readonly=False)
    commercial_partner_id = fields.Many2one(
        'res.partner', string='Commercial Entity',
        compute='_compute_commercial_partner_id', store=True)
    to_pay_move_line_ids = fields.Many2many(
            'account.move.line',
            'account_move_line_payment_to_pay_multiple_rel',
            'multiple_payment_id',
            'to_pay_line_id',
            string="Lineas a pagar",
             store=True,
            help='This lines are the ones the user has selected to be paid.',
            copy=False,
            readonly=False,
            compute='_compute_to_pay_move_lines',
        )
    to_pay_payment_ids = fields.Many2many(
        'account.payment',
        'account_payment_payment_multiple_rel',
        'multiple_payment_id',
        'to_pay_payment_id',
        string='Pagos no conciliados', 
        domain="[('partner_id', '=', partner_id), ('state', '!=', 'reconciled'), ('partner_type', 'in', ['customer', 'supplier'])]"
    )
    withholding_line_ids = fields.One2many(
        'l10n_ar.payment.withholding', 'x_multiple_payment_id', string='Withholdings Lines',
        # compute='_compute_l10n_ar_withholding_line_ids', readonly=False, store=True
    )
    matched_move_line_ids = fields.Many2many(
        'account.move.line',
        compute='_compute_matched_move_line_ids',
        help='Lines that has been matched to payments, only available after '
        'payment validation',
    )
    state = fields.Selection([
        ('debts', 'Elegir Deudas'), 
        ('draft', 'Borrador'),
        ('posted', 'Publicado'), 
        ('cancelled', 'Cancelado'),
    ], string='Status', default='debts')

    selected_debt = fields.Monetary(
        # string='To Pay lines Amount',
        string='Deuda seleccionada',
        compute='_compute_selected_debt',
        currency_field='company_currency_id',
    )
    unreconciled_amount = fields.Monetary(
        string='Ajuste / Avance',
        currency_field='company_currency_id',
    )
    # reconciled_amount = fields.Monetary(compute='_compute_amounts')
    to_pay_amount = fields.Monetary(
        compute='_compute_to_pay_amount',
        inverse='_inverse_to_pay_amount',
        string='Monto a pagar',
        # string='Total To Pay Amount',
        readonly=True,
        currency_field='company_currency_id',
    )
    amount_company_currency_signed_pro = fields.Monetary(
        currency_field='company_currency_id', compute='_compute_amount_company_currency_signed_pro',)

    payment_total = fields.Monetary(
        compute='_compute_payment_total',
        string='Total a pagar',
        currency_field='company_currency_id'
    )
    payment_difference = fields.Monetary(
        compute='_compute_payment_difference',
        readonly=True,
        string="Diferencia",
        currency_field='company_currency_id',
        help="Difference between selected debt (or to pay amount) and "
        "payments amount"
    )
    last_journal_used = fields.Many2one(
        'account.journal',
        string='Último Diario Utilizado',
        compute='_compute_last_journal_used',
        store=True
    )
    last_payment_method_line_id = fields.Many2one('account.payment.method.line', string='Último método de pago',
        readonly=True,compute='_compute_last_payment_method_line_id')


    ###RETENCIONES
    retencion_ganancias = fields.Selection([
        # _get_regimen_ganancias,
        ('imposibilidad_retencion', 'Imposibilidad de Retención'),
        ('no_aplica', 'No Aplica'),
        ('nro_regimen', 'Nro Regimen'),
    ],
        string='Retención Ganancias',
        compute='_compute_retenciones_ganancias'
    )
    regimen_ganancias_id = fields.Many2one(
        'afip.tabla_ganancias.alicuotasymontos',
        'Regimen Ganancias',
        ondelete='restrict',
        compute='_compute_regimen_ganancias_id',
    )
    selected_debt_untaxed = fields.Monetary(
        # string='To Pay lines Amount',
        string='Selected Debt Untaxed',
        compute='_compute_selected_debt_untaxed',
        currency_field='company_currency_id',
    )
    withholdable_advanced_amount = fields.Monetary(
        'Adjustment / Advance (untaxed)',
        help='Used for withholdings calculation',
        currency_field='company_currency_id',
    )
    """"
    matched_amount_untaxed = fields.Monetary(
        compute='_compute_matched_amount_untaxed',
        currency_field='currency_id',
    )
    matched_amount = fields.Monetary(
        compute='_compute_matched_amounts',
        currency_field='company_currency_id',
    )
    unmatched_amount = fields.Monetary(
        compute='_compute_matched_amounts',
        currency_field='currency_id',
    )
    """

    ###COMPUTE METHODS
    @api.depends('state')
    def _compute_name_sequence(self):
        for record in self:
            if record.state == 'debts':
                record.name = 'New'
                if record.sequence_used:
                    record.sequence_used == record.sequence_used
            elif record.state == 'draft':
                record.name = 'Borrador'
                if record.sequence_used:
                    record.sequence_used == record.sequence_used
            elif record.state == 'posted':
                record.name = self.env['ir.sequence'].next_by_code('x_reporte_de_pagos') or 'New'
                if record.sequence_used == False:
                    record.sequence_used = record.name

    @api.depends('state')
    def _compute_matched_move_line_ids(self):
        for record in self:
            if record.state == 'posted':
                payment_lines_accumulated = self.env['account.move.line']
                for rec in record.to_pay_payment_ids:
                    payment_lines = rec.line_ids.filtered(lambda x: x.account_type in self._get_valid_payment_account_types())
                    debit_moves = payment_lines.mapped('matched_debit_ids.debit_move_id')
                    credit_moves = payment_lines.mapped('matched_credit_ids.credit_move_id')
                    debit_lines_sorted = debit_moves.filtered(lambda x: x.date_maturity != False).sorted(key=lambda x: (x.date_maturity, x.move_id.name))
                    credit_lines_sorted = credit_moves.filtered(lambda x: x.date_maturity != False).sorted(key=lambda x: (x.date_maturity, x.move_id.name))
                    debit_lines_without_date_maturity = debit_moves - debit_lines_sorted
                    credit_lines_without_date_maturity = credit_moves - credit_lines_sorted
                    payment_lines_accumulated |= payment_lines
                record.matched_move_line_ids = ((debit_lines_sorted + debit_lines_without_date_maturity) | (credit_lines_sorted + credit_lines_without_date_maturity)) - payment_lines_accumulated
            else:
                record.matched_move_line_ids = False
    @api.depends('to_pay_payment_ids')
    def _compute_last_payment_method_line_id(self):
        for record in self:
            if record.to_pay_payment_ids:
                last_payment = record.to_pay_payment_ids[-1]
                record.last_payment_method_line_id = last_payment.payment_method_line_id
            else:
                record.last_payment_method_line_id = False
    @api.depends('to_pay_payment_ids')
    def _compute_last_journal_used(self):
        for record in self:
            if record.to_pay_payment_ids:
                # Obtener el último pago en la lista to_pay_payment_ids
                last_payment = record.to_pay_payment_ids[-1]
                record.last_journal_used = last_payment.journal_id
            else:
                record.last_journal_used = False
                
    @api.depends('partner_id')
    def _compute_retenciones_ganancias(self):
        for rec in self:
            if rec.partner_id.imp_ganancias_padron == 'AC':
                rec.retencion_ganancias = 'nro_regimen'
            else:
                rec.retencion_ganancias = 'no_aplica'

    @api.depends('retencion_ganancias')
    def _compute_regimen_ganancias_id(self):
        for rec in self:
            if rec.partner_id and rec.retencion_ganancias == 'nro_regimen':
                rec.regimen_ganancias_id = rec.partner_id.default_regimen_ganancias_id
            else:
                rec.regimen_ganancias_id = False

    @api.depends('amount_company_currency_signed_pro')
    def _compute_payment_total(self):
        for rec in self:
            rec.payment_total = rec.amount_company_currency_signed_pro + sum(rec.withholding_line_ids.mapped('amount'))
        
    @api.depends('to_pay_payment_ids')
    def _compute_amount_company_currency_signed_pro(self):
        """ new field similar to amount_company_currency_signed but:
        1. is positive for payments to suppliers
        2. we use the new field amount_company_currency instead of amount_total_signed, because amount_total_signed is
        computed only after saving
        We use l10n_ar prefix because this is a pseudo backport of future l10n_ar_withholding module """
        for rec in self:
            rec.amount_company_currency_signed_pro = 0
            for payment in rec.to_pay_payment_ids:
                if payment.payment_type == 'outbound' and payment.partner_type == 'customer' or \
                        payment.payment_type == 'inbound' and payment.partner_type == 'supplier':
                    rec.amount_company_currency_signed_pro += -payment.amount_company_currency
                else:
                    rec.amount_company_currency_signed_pro += payment.amount_company_currency
                    
    @api.depends('payment_total', 'to_pay_amount', 'amount_company_currency_signed_pro')
    def _compute_payment_difference(self):
        for rec in self:
            rec.payment_difference = rec._get_payment_difference() - sum(self.withholding_line_ids.mapped('amount'))             
    def _get_payment_difference(self):
        return self.to_pay_amount - self.amount_company_currency_signed_pro
       
    @api.depends(
        'to_pay_move_line_ids.amount_residual',
        'to_pay_move_line_ids.amount_residual_currency',
        'to_pay_move_line_ids.currency_id',
        'to_pay_move_line_ids.move_id',
        'date',
        'company_currency_id',
    )
    def _compute_selected_debt_untaxed(self):
        for rec in self:
            selected_debt_untaxed = 0.0
            for line in rec.to_pay_move_line_ids._origin:
                # factor for total_untaxed
                invoice = line.move_id
                factor = invoice and invoice._get_tax_factor() or 1.0
                selected_debt_untaxed += line.amount_residual * factor
            rec.selected_debt_untaxed = selected_debt_untaxed * (rec.partner_type == 'supplier' and -1.0 or 1.0)
    @api.depends('partner_id', 'partner_type', 'company_id')
    def _compute_to_pay_move_lines(self):
        # TODO ?
        # # if payment group is being created from a payment we dont want to compute to_pay_move_lines
        # if self._context.get('created_automatically'):
        #     return

        # Se recomputan las lienas solo si la deuda que esta seleccionada solo si
        # cambio el partner, compania o partner_type
        for rec in self:
            if rec.partner_id != rec._origin.partner_id or rec.partner_type != rec._origin.partner_type or \
                    rec.company_id != rec._origin.company_id:
                rec.add_all()

    @api.depends('partner_id')
    def _compute_commercial_partner_id(self):
        for record in self:
            record.commercial_partner_id = record.partner_id.commercial_partner_id
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
            
    def _get_to_pay_move_lines_domain(self):
        self.ensure_one()
        return [
            ('partner_id.commercial_partner_id', '=', self.partner_id.commercial_partner_id.id),
            ('company_id', '=', self.company_id.id), ('move_id.state', '=', 'posted'),
            ('account_id.reconcile', '=', True), ('reconciled', '=', False), ('full_reconcile_id', '=', False),
            ('account_id.account_type', '=', 'asset_receivable' if self.partner_type == 'customer' else 'liability_payable'),
        ]

    def add_all(self):
        for rec in self:
            rec.to_pay_move_line_ids = [Command.clear(), Command.set(self.env['account.move.line'].search(rec._get_to_pay_move_lines_domain()).ids)]

    def remove_all(self):
        self.to_pay_move_line_ids = False
        
    def confirm_debts(self):
        for record in self:
            record.state = 'draft'
            record._compute_withholdings()
    def compute_withholdingss(self):
        for rec in self:
            rec._compute_withholdings()
        return
    def reset_to_draft(self):
        for record in self:
            for payment in record.to_pay_payment_ids:
                payment.action_draft()
            record.state='draft'
        return
    def cancel_payments(self):
        return
    
    def add_payment(self):
        self.ensure_one()
        # Crear el asistente y llenar line_ids con to_pay_move_line_ids
        payment_register = self.env['custom.account.payment.register'].create({
            'line_ids': [(6, 0, self.to_pay_move_line_ids.ids)],
            'multiple_payment_id': self.id,# Aquí asignamos el ID del primer modelo
            'amount_received' : self.payment_difference,
            'journal_id':self.last_journal_used.id,
            'payment_method_line_id':self.last_payment_method_line_id.id,
        })
    
        # Devolver la acción para abrir el asistente en una ventana modal
        return {
            'name': 'Registrar Pago',
            'type': 'ir.actions.act_window',
            'res_model': 'custom.account.payment.register',
            'view_mode': 'form',
            'view_id': self.env.ref('account-payment-group.view_custom_account_payment_register_form').id,  # Reemplaza con el ID de la vista del asistente
            'target': 'new',
            'res_id': payment_register.id,
            'context': {
                'default_multiple_payment_id': self.id,
                'default_amount_received' : self.payment_difference,
                **self.env.context,
            },
        }
    def action_reconcile_payments(self):
        self.ensure_one()

        invoices = self.to_pay_move_line_ids.filtered(lambda line: not line.reconciled).sorted(key=lambda line: line.date)
        payments = self.to_pay_payment_ids.filtered(lambda payment: payment.state == 'draft')

        if not invoices or not payments:
            raise UserError("No hay facturas o pagos pendientes para conciliar.")
        first_payment = True  # Variable para marcar el primer pago
        # Conciliar secuencialmente
        for payment in payments:
            remaining_amount = payment.amount

            for invoice_line in invoices:
                invoice_balance = invoice_line.amount_residual

                # Siempre agregar la línea de factura al campo to_pay_move_line_ids del pago
                payment.write({
                        'to_pay_move_line_ids': [(4, invoice_line.id)]
                    })

                # Determinar el monto a conciliar
                amount_to_reconcile = min(remaining_amount, invoice_balance)

                remaining_amount -= amount_to_reconcile

                # Si la factura aún tiene un saldo después de este pago, se seguirá utilizando en el próximo pago
                if remaining_amount <= 0:
                    break
            if first_payment and self.withholding_line_ids:
                payment.write({
                    'l10n_ar_withholding_line_ids': [(4, tax.id) for tax in self.withholding_line_ids]
                })
            payment.action_post()
        # Publicar los pagos que han sido conciliados
        #payments.action_post()
        self.state = 'posted'
        return


    ###RETENCIONES
    def _compute_withholdings(self):
        # chequeamos lineas a pagar antes de computar impuestos para evitar trabajar sobre base erronea
        self._check_to_pay_lines_account()
        for rec in self:
            if rec.partner_type != 'supplier':
                continue
            # limpiamos el type por si se paga desde factura ya que el en ese
            # caso viene in_invoice o out_invoice y en search de tax filtrar
            # por impuestos de venta y compra (y no los nuestros de pagos
            # y cobros)
            taxes = self.env['account.tax'].with_context(type=None).search([
                    ('type_tax_use', '=', 'none'),
                    ('l10n_ar_withholding_payment_type', '=', rec.partner_type),
                    ('company_id', '=', rec.company_id.id),
                ])
            rec._upadte_withholdings(taxes)

    def compute_withholdings(self):
        checks_payments = self.filtered(lambda x: x.payment_method_code in ['in_third_party_checks', 'out_third_party_checks'])
        (self - checks_payments)._compute_withholdings()
        for rec in checks_payments.with_context(skip_account_move_synchronization=True):
            #rec.set_withholdable_advanced_amount()
            rec._compute_withholdings()
            # dejamos 230 porque el hecho de estar usando valor de "$2" abajo y subir de a un centavo hace podamos necesitar
            # 200 intento solo en esa seccion
            # deberiamos ver de ir aproximando de otra manera
            remining_attemps = 230
            while not rec.company_currency_id.is_zero(rec.payment_difference):
                if remining_attemps == 0:
                    raise UserError(
                        'Máximo de intentos alcanzado. No pudimos computar el importe a pagar. El último importe a pagar'
                        'al que llegamos fue "%s"' % rec.to_pay_amount)
                remining_attemps -= 1
                # el payment difference es negativo, para entenderlo mejor lo pasamos a postivo
                # por ahora, arbitrariamente, si la diferencia es mayor a 2 vamos sumando la payment difference
                # para llegar mas rapido al numero
                # cuando ya estamos cerca del numero empezamos a sumar de a 1 centavo.
                # no lo hacemos siempre sumando el difference porque podria ser que por temas de redondeo o escalamiento
                # nos pasemos del otro lado
                # TODO ver si conviene mejor hacer una ponderacion porcentual
                if -rec.payment_difference > 2:
                    rec.to_pay_amount -= rec.payment_difference
                elif -rec.payment_difference > 0:
                    rec.to_pay_amount += 0.01
                elif rec.to_pay_amount > rec.amount:
                    # este caso es por ej. si el cliente ya habia pre-completado con un to_pay_amount mayor al amount
                    # del pago
                    rec.to_pay_amount = 0.0
                else:
                    raise UserError(
                        'Hubo un error al querer computar el importe a pagar. Llegamos a estos valores:\n'
                        '* to_pay_amount: %s\n'
                        '* payment_difference: %s\n'
                        '* amount: %s'
                        % (rec.to_pay_amount, rec.payment_difference, rec.amount))
                rec.set_withholdable_advanced_amount()
                rec._compute_withholdings()
            rec.with_context(skip_account_move_synchronization=False)._synchronize_to_moves({'l10n_ar_withholding_line_ids'})

    def _upadte_withholdings(self, taxes):
        self.ensure_one()
        commands = []
        for tax in taxes:
            if (
                    tax.withholding_user_error_message and
                    tax.withholding_user_error_domain):
                try:
                    domain = literal_eval(tax.withholding_user_error_domain)
                except Exception as e:
                    raise ValidationError(_(
                        'Could not eval rule domain "%s".\n'
                        'This is what we get:\n%s' % (tax.withholding_user_error_domain, e)))
                domain.append(('id', '=', self.id))
                if self.search(domain):
                    raise ValidationError(tax.withholding_user_error_message)
            vals = tax.get_withholding_vals(self)

            # we set computed_withholding_amount, hacemos round porque
            # si no puede pasarse un valor con mas decimales del que se ve
            # y terminar dando error en el asiento por debitos y creditos no
            # son iguales, algo parecido hace odoo en el compute_all de taxes
            currency = self.company_currency_id
            period_withholding_amount = currency.round(vals.get('period_withholding_amount', 0.0))
            previous_withholding_amount = currency.round(vals.get('previous_withholding_amount'))
            # withholding can not be negative
            computed_withholding_amount = max(0, (period_withholding_amount - previous_withholding_amount))

            payment_withholding = self.withholding_line_ids.filtered(lambda x: x.tax_id == tax)
            if not computed_withholding_amount:
                # if on refresh no more withholding, we delete if it exists
                if payment_withholding:
                    commands.append(Command.delete(payment_withholding.id))
                continue

            # we copy withholdable_base_amount on base_amount
            # al final vimos con varios clientes que este monto base
            # debe ser la base imponible de lo que se está pagando en este
            # voucher
            vals['base_amount'] = vals.get('withholdable_advanced_amount') + vals.get('withholdable_invoiced_amount')
            vals['amount'] = computed_withholding_amount
            vals['computed_withholding_amount'] = computed_withholding_amount

            # por ahora no imprimimos el comment, podemos ver de llevarlo a
            # otro campo si es de utilidad
            vals.pop('comment')
            if payment_withholding:
                commands.append(Command.update(payment_withholding.id, vals))
                # payment_withholding.write(vals)
            else:
                # TODO implementar devoluciones de retenciones
                # TODO en vez de pasarlo asi usar un command create
                vals['payment_id'] = self.id
                commands.append(Command.create(vals))
        self.withholding_line_ids = commands

    def _check_to_pay_lines_account(self):
        """ TODO ver si esto tmb lo llevamos a la UI y lo mostramos como un warning.
        tmb podemos dar mas info al usuario en el error """
        for rec in self:
            accounts = rec.to_pay_move_line_ids.mapped('account_id')
            if len(accounts) > 1:
                raise ValidationError(_('To Pay Lines must be of the same account!'))
    def _get_withholdable_amounts(
            self, withholding_amount_type, withholding_advances):
        """ Method to help on getting withholding amounts from account.tax
        """
        self.ensure_one()
        # Por compatibilidad con public_budget aceptamos
        # pagos en otros estados no validados donde el matched y
        # unmatched no se computaron, por eso agragamos la condición
        if self.state == 'posted':
            untaxed_field = 'matched_amount_untaxed'
            total_field = 'matched_amount'
        else:
            untaxed_field = 'selected_debt_untaxed'
            total_field = 'selected_debt'

        if withholding_amount_type == 'untaxed_amount':
            withholdable_invoiced_amount = self[untaxed_field]
        else:
            withholdable_invoiced_amount = self[total_field]

        withholdable_advanced_amount = 0.0
        # if the unreconciled_amount is negative, then the user wants to make
        # a partial payment. To get the right untaxed amount we need to know
        # which invoice is going to be paid, we only allow partial payment
        # on last invoice.
        # If the payment is posted the withholdable_invoiced_amount is
        # the matched amount
        if self.withholdable_advanced_amount < 0.0 and \
                self.to_pay_move_line_ids and self.state != 'posted':
            withholdable_advanced_amount = 0.0

            sign = self.partner_type == 'supplier' and -1.0 or 1.0
            sorted_to_pay_lines = sorted(
                self.to_pay_move_line_ids,
                key=lambda a: a.date_maturity or a.date)

            # last line to be reconciled
            partial_line = sorted_to_pay_lines[-1]
            if sign * partial_line.amount_residual < \
                    sign * self.withholdable_advanced_amount:
                raise ValidationError(_(
                    'Seleccionó deuda por %s pero aparentente desea pagar '
                    ' %s. En la deuda seleccionada hay algunos comprobantes de'
                    ' mas que no van a poder ser pagados (%s). Deberá quitar '
                    ' dichos comprobantes de la deuda seleccionada para poder '
                    'hacer el correcto cálculo de las retenciones.' % (
                        self.selected_debt,
                        self.to_pay_amount,
                        partial_line.move_id.display_name,
                        )))

            if withholding_amount_type == 'untaxed_amount' and \
                    partial_line.move_id:
                invoice_factor = partial_line.move_id._get_tax_factor()
            else:
                invoice_factor = 1.0

            # si el adelanto es negativo estamos pagando parcialmente una
            # factura y ocultamos el campo sin impuesto ya que lo sacamos por
            # el proporcional descontando de el iva a lo que se esta pagando
            withholdable_invoiced_amount -= (
                sign * self.unreconciled_amount * invoice_factor)
        elif withholding_advances:
            # si el pago esta publicado obtenemos los valores de los importes
            # conciliados (porque el pago pudo prepararse como adelanto
            # pero luego haberse conciliado y en ese caso lo estariamos sumando
            # dos veces si lo usamos como base de otros pagos). Si estan los
            # campos withholdable_advanced_amount y unreconciled_amount le
            # sacamos el proporcional correspondiente
            if self.state == 'posted':
                if self.unreconciled_amount and \
                   self.withholdable_advanced_amount:
                    withholdable_advanced_amount = self.amount_residual * (
                        self.withholdable_advanced_amount /
                        self.unreconciled_amount)
                else:
                    withholdable_advanced_amount = self.amount_residual
            else:
                withholdable_advanced_amount = \
                    self.withholdable_advanced_amount
        return (withholdable_advanced_amount, withholdable_invoiced_amount)

    @api.model
    def _get_valid_payment_account_types(self):
        return ['asset_receivable', 'liability_payable']
class l10nArPaymentRegisterWithholding(models.Model):
    _inherit = 'l10n_ar.payment.withholding'
    multiple_payment_id = fields.Many2one('account.payment.multiplemethods', required=True, ondelete='cascade')


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    def delete_payment(self):
        self.ensure_one()
        self.unlink()