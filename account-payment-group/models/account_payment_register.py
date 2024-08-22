from odoo import models, fields, api, Command, _
from odoo.exceptions import ValidationError, UserError

class CustomAccountPaymentRegister(models.TransientModel):
    _name = 'custom.account.payment.register'
    _inherit = 'account.payment.register'

    amount_received = fields.Monetary(currency_field='currency_id', store=True, readonly=True)
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
    payment_method_code = fields.Char(
        related='payment_method_line_id.code')

    @api.depends('amount_received', 'company_id', 'currency_id', 'payment_date')
    def _compute_amount(self):
        for wizard in self:
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
            'l10n_latam_check_id':self.l10n_latam_check_id,
        }
        return payment_vals
    
    def _create_payments(self):
        self.ensure_one()
        # Skip batches that are not valid (bank account not trusted but required)
        all_batches = self._get_batches()
        batches = []
        # Skip batches that are not valid (bank account not trusted but required)
        for batch in all_batches:
            batch_account = self._get_batch_account(batch)
            if self.require_partner_bank_account and not batch_account.allow_out_payment:
                continue
            batches.append(batch)

        if not batches:
            raise UserError(_('To record payments with %s, the recipient bank account must be manually validated. You should go on the partner bank account in order to validate it.', self.payment_method_line_id.name))
        first_batch_result = batches[0]
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
        return True

