from odoo import models, fields, api, Command, _
from odoo.exceptions import ValidationError, UserError

class CustomAccountPaymentRegister(models.TransientModel):
    _name = 'custom.account.payment.register'
    #_inherit = 'account.payment.register'
    
    payment_date = fields.Date(string="Payment Date", required=True,
        default=fields.Date.context_today)
    amount = fields.Monetary(currency_field='currency_id', store=True, readonly=False,
        compute='_compute_amount')

    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        compute='_compute_currency_id', store=True, readonly=False, precompute=True,
        help="The payment's currency.")
    company_currency_id = fields.Many2one('res.currency', string="Company Currency",
        related='company_id.currency_id')
    journal_id = fields.Many2one(
        comodel_name='account.journal',
        store=True, readonly=False,
        domain="[('id', 'in', available_journal_ids)]")
    
    available_journal_ids = fields.Many2many(
        comodel_name='account.journal',
        compute='_compute_available_journal_ids'
    )
    available_partner_bank_ids = fields.Many2many(
        comodel_name='res.partner.bank',
    )

    payment_type = fields.Selection([
        ('outbound', 'Send Money'),
        ('inbound', 'Receive Money'),
    ], string='Payment Type', store=True, copy=False,)
    partner_type = fields.Selection([
        ('customer', 'Customer'),
        ('supplier', 'Vendor'),
    ], store=True, copy=False,)
    source_amount = fields.Monetary(
        string="Amount to Pay (company currency)", store=True, copy=False,
        currency_field='company_currency_id',)
    company_id = fields.Many2one('res.company', store=True, copy=False,)
    partner_id = fields.Many2one('res.partner',
        string="Customer/Vendor", store=True, copy=False, ondelete='restrict')
    
    amount_received = fields.Monetary(currency_field='currency_id', store=True, readonly=True)
    payment_difference = fields.Monetary(
        compute='_compute_payment_difference')
    line_ids = fields.Many2many('account.move.line', 'account_payment_register_move_line_multiple_rel', 'wizard_id', 'line_id',
        string="Journal items", readonly=True, copy=False,)
    multiple_payment_id = fields.Many2one('account.payment.multiplemethods', required=True, ondelete='cascade')
    can_edit_wizard = fields.Boolean(default=True)
    l10n_latam_check_number = fields.Char(string='Número de cheque')
    l10n_latam_check_payment_date = fields.Date(string="Fecha de pago del cheque")
    l10n_latam_check_id = fields.Many2one(
        comodel_name='account.payment',
        string='Check', 
        copy=False,
        check_company=True,
    )
    l10n_latam_manual_checks = fields.Boolean(
        related='journal_id.l10n_latam_manual_checks',
    )
    can_group_payments = fields.Boolean(store=True, copy=False,)
    payment_method_code = fields.Char(
        related='payment_method_line_id.code')
    payment_method_line_id = fields.Many2one('account.payment.method.line', string='Payment Method',
        readonly=False, store=True,
        compute='_compute_payment_method_line_id',
        domain="[('id', 'in', available_payment_method_line_ids)]",)
    available_payment_method_line_ids = fields.Many2many('account.payment.method.line', compute='_compute_payment_method_line_fields')
    
    is_advanced_payment = fields.Boolean(
        'Pagos avanzados',
        default = False,
    )
    @api.model
    def create(self, vals):
        record = super(CustomAccountPaymentRegister, self).create(vals)
        if not record.l10n_latam_check_number:
            if record.journal_id.l10n_check_next_number:
                record.l10n_latam_check_number = record.journal_id.l10n_check_next_number
        return record
        
    @api.depends('can_edit_wizard', 'amount')
    def _compute_payment_difference(self):
        wizard.payment_difference = 0.0
        
    @api.depends('payment_type', 'journal_id', 'currency_id')
    def _compute_payment_method_line_fields(self):
        for wizard in self:
            if wizard.journal_id:
                wizard.available_payment_method_line_ids = wizard.journal_id._get_available_payment_method_lines(wizard.payment_type)
            else:
                wizard.available_payment_method_line_ids = False
                
    @api.depends('journal_id')
    def _compute_currency_id(self):
        for wizard in self:
            wizard.currency_id = wizard.journal_id.currency_id  or wizard.company_id.currency_id
            
    @api.depends('payment_type', 'company_id', 'can_edit_wizard')
    def _compute_available_journal_ids(self):
        for wizard in self:
            available_journals = self.env['account.journal']
            
    @api.onchange('journal_id','payment_method_line_id')
    def _compute_l10n_latam_check_number(self):
        for wizard in self:
            if not wizard.l10n_latam_check_number:
                if wizard.journal_id.l10n_check_next_number:
                    wizard.l10n_latam_check_number = wizard.journal_id.l10n_check_next_number
    
    @api.depends('amount_received', 'company_id', 'currency_id', 'payment_date','l10n_latam_check_id')
    def _compute_amount(self):
        for wizard in self:
            if wizard.l10n_latam_check_id:
                wizard.amount = wizard.l10n_latam_check_id.amount
            else:
                if wizard.amount_received:
                    wizard.amount = wizard.amount_received
                else:
                    wizard.amount = None
                

        
    def _init_payments(self, to_process):
        """

        Create the payments.

        :param to_process:  A list of python dictionary, one for each payment to create, containing:
                            * create_vals:  The values used for the 'create' method.
                            * to_reconcile: The journal items to perform the reconciliation.
                            * batch:        A python dict containing everything you want about the source journal items
                                            to which a payment will be created (see '_get_batches').
        :param edit_mode:   Is the wizard in edition mode.
        """
        payments = self.env['account.payment']\
            .with_context(skip_invoice_sync=True)\
            .create([x['create_vals'] for x in to_process])

        for payment, vals in zip(payments, to_process):
            vals['payment'] = payment

            # If payments are made using a currency different than the source one, ensure the balance match exactly in
            # order to fully paid the source journal items.
            # For example, suppose a new currency B having a rate 100:1 regarding the company currency A.
            # If you try to pay 12.15A using 0.12B, the computed balance will be 12.00A for the payment instead of 12.15A.
            lines = vals['to_reconcile']

            # Batches are made using the same currency so making 'lines.currency_id' is ok.
            if payment.currency_id != lines.currency_id:
                liquidity_lines, counterpart_lines, writeoff_lines = payment._seek_for_lines()
                source_balance = abs(sum(lines.mapped('amount_residual')))
                if liquidity_lines[0].balance:
                    payment_rate = liquidity_lines[0].amount_currency / liquidity_lines[0].balance
                else:
                    payment_rate = 0.0
                source_balance_converted = abs(source_balance) * payment_rate

                # Translate the balance into the payment currency is order to be able to compare them.
                # In case in both have the same value (12.15 * 0.01 ~= 0.12 in our example), it means the user
                # attempt to fully paid the source lines and then, we need to manually fix them to get a perfect
                # match.
                payment_balance = abs(sum(counterpart_lines.mapped('balance')))
                payment_amount_currency = abs(sum(counterpart_lines.mapped('amount_currency')))
                if not payment.currency_id.is_zero(source_balance_converted - payment_amount_currency):
                    continue

                delta_balance = source_balance - payment_balance

                # Balance are already the same.
                if self.company_currency_id.is_zero(delta_balance):
                    continue

                # Fix the balance but make sure to peek the liquidity and counterpart lines first.
                debit_lines = (liquidity_lines + counterpart_lines).filtered('debit')
                credit_lines = (liquidity_lines + counterpart_lines).filtered('credit')

                if debit_lines and credit_lines:
                    payment.move_id.write({'line_ids': [
                        (1, debit_lines[0].id, {'debit': debit_lines[0].debit + delta_balance}),
                        (1, credit_lines[0].id, {'credit': credit_lines[0].credit + delta_balance}),
                    ]})
        return payments

   
    
    def _create_payment_vals_from_wizard(self):
        payment_vals = {
            'date': self.payment_date,
            'amount': self.amount,
            'payment_type': self.payment_type,
            'partner_type': self.partner_type,
            'journal_id': self.journal_id.id,
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'partner_id': self.partner_id.id,
            'partner_bank_id': self.partner_bank_id.id,
            'payment_method_line_id': self.payment_method_line_id.id,
            'destination_account_id': self.line_ids[0].account_id.id,
            'write_off_line_vals': [],
            'l10n_latam_check_number':self.l10n_latam_check_number,
            'l10n_latam_check_payment_date':self.l10n_latam_check_payment_date,
            'l10n_latam_check_id':self.l10n_latam_check_id.id,
        }
        return payment_vals
    
    def _create_payments(self):
        self.ensure_one()
        edit_mode = True 
        to_process = [] 
        if edit_mode:
            payment_vals = self._create_payment_vals_from_wizard()
            to_process_values = {
                'create_vals': payment_vals,
                'to_reconcile': first_batch_result['lines'],
            }
            
            to_process.append(to_process_values)
        payments = self._init_payments(to_process)
        if self.multiple_payment_id and payments:
            self.multiple_payment_id.to_pay_payment_ids = [(4, payment.id) for payment in payments]
        return payments
        
    def action_create_payments(self):
        payments = self._create_payments()
        self.journal_id.increment_sequence()
        return True
        
    @api.model
    def default_get(self, fields_list):
        # Devuelve un diccionario vacío o un conjunto personalizado de valores predeterminados
        return {}
        

