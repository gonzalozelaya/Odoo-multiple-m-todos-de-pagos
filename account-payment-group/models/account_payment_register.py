from odoo import models, fields, api, Command, _
from odoo.exceptions import ValidationError, UserError
from collections import defaultdict
from odoo.tools import frozendict
import pprint


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
    
    is_advanced_payment = fields.Boolean(
        'Pagos avanzados',
        default = False,
    )
    payment_type = fields.Selection([
        ('outbound', 'Send Money'),
        ('inbound', 'Receive Money'),
    ], string='Payment Type', store=True, copy=False)
    partner_type = fields.Selection([
        ('customer', 'Customer'),
        ('supplier', 'Vendor'),
    ], store=True, copy=False,)
    @api.model
    def create(self, vals):
        record = super(CustomAccountPaymentRegister, self).create(vals)
        if not record.l10n_latam_check_number:
            if record.journal_id.l10n_check_next_number:
                record.l10n_latam_check_number = record.journal_id.l10n_check_next_number
        return record
        
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
                    if wizard.amount_received > 0:
                        wizard.amount = wizard.amount_received
                    else:
                        wizard.amount_received = 0
                else:
                    wizard.amount = None
                    
    def _init_payments(self, to_process):
        """ Create the payments.

        :param to_process:  A list of python dictionary, one for each payment to create, containing:
                            * create_vals:  The values used for the 'create' method.
                            * to_reconcile: The journal items to perform the reconciliation.
                            * batch:        A python dict containing everything you want about the source journal items
                                            to which a payment will be created (see '_get_batches').
        :param edit_mode:   Is the wizard in edition mode.
        """
        #raise UserError(pprint.pformat(to_process))
        payments = self.env['account.payment']\
            .with_context(skip_invoice_sync=True)\
            .create([x['create_vals'] for x in to_process])
 
        return payments

   
    
    def _create_payment_vals_from_wizard(self):
        payment_vals = {
            'date': self.payment_date,
            'amount': self.amount,
            'payment_type': self.payment_type,
            'partner_type': self.partner_type,
            'journal_id': self.journal_id.id,
            'company_id': self.company_id.id,
            'currency_id': 19,
            'partner_id': self.partner_id.id,
            'partner_bank_id': self.partner_bank_id.id,
            'payment_method_line_id': self.payment_method_line_id.id,
            #'destination_account_id': self.line_ids[0].account_id.id,
            'write_off_line_vals': [],
            'l10n_latam_check_number':self.l10n_latam_check_number,
            'l10n_latam_check_payment_date':self.l10n_latam_check_payment_date,
            'l10n_latam_check_id':self.l10n_latam_check_id.id,
            'multiple_payment_id':self.multiple_payment_id.id,
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
                'to_reconcile': self.env['account.move.line'],
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

    def _get_batches(self):
        ''' Group the account.move.line linked to the wizard together.
        Lines are grouped if they share 'partner_id','account_id','currency_id' & 'partner_type' and if
        0 or 1 partner_bank_id can be determined for the group.
        :return: A list of batches, each one containing:
            * payment_values:   A dictionary of payment values.
            * moves:        An account.move recordset.
        '''
        self.ensure_one()

        lines = self.line_ids._origin
        if not lines:
            return []
        if len(lines.company_id.root_id) > 1:
            raise UserError(_("You can't create payments for entries belonging to different companies."))

        batches = defaultdict(lambda: {'lines': self.env['account.move.line']})
        banks_per_partner = defaultdict(lambda: {'inbound': set(), 'outbound': set()})
        for line in lines:
            batch_key = self._get_line_batch_key(line)
            vals = batches[frozendict(batch_key)]
            vals['payment_values'] = batch_key
            vals['lines'] += line
            banks_per_partner[batch_key['partner_id']]['inbound' if line.balance > 0.0 else 'outbound'].add(
                batch_key['partner_bank_id']
            )

        partner_unique_inbound = {p for p, b in banks_per_partner.items() if len(b['inbound']) == 1}
        partner_unique_outbound = {p for p, b in banks_per_partner.items() if len(b['outbound']) == 1}

        # Compute 'payment_type'.
        batch_vals = []
        seen_keys = set()
        for i, key in enumerate(list(batches)):
            if key in seen_keys:
                continue
            vals = batches[key]
            lines = vals['lines']
            merge = (
                batch_key['partner_id'] in partner_unique_inbound
                and batch_key['partner_id'] in partner_unique_outbound
            )
            if merge:
                for other_key in list(batches)[i+1:]:
                    if other_key in seen_keys:
                        continue
                    other_vals = batches[other_key]
                    if all(
                        other_vals['payment_values'][k] == v
                        for k, v in vals['payment_values'].items()
                        if k not in ('partner_bank_id', 'payment_type')
                    ):
                        # add the lines in this batch and mark as seen
                        lines += other_vals['lines']
                        seen_keys.add(other_key)
            balance = sum(lines.mapped('balance'))
            vals['payment_values']['payment_type'] = 'inbound' if balance > 0.0 else 'outbound'
            if merge:
                partner_banks = banks_per_partner[batch_key['partner_id']]
                vals['partner_bank_id'] = partner_banks[vals['payment_values']['payment_type']]
                vals['lines'] = lines
            batch_vals.append(vals)
        return batch_vals

    @api.depends('line_ids')
    def _compute_from_lines(self):
        ''' Load initial values from the account.moves passed through the context. '''
        for wizard in self:
            batches = wizard._get_batches()
            if not batches:
                wizard.source_currency_id = self.env.context.get('default_currency_id', wizard.company_id.currency_id.id)
                wizard.source_amount = 0.0
                wizard.source_amount_currency = 0.0
                wizard.can_edit_wizard = True
                wizard.can_group_payments = False
            else:
                batch_result = batches[0]
                wizard_values_from_batch = wizard._get_wizard_values_from_batch(batch_result)
    
                if len(batches) == 1:
                    # == Single batch to be mounted on the view ==
                    wizard.update(wizard_values_from_batch)
    
                    wizard.can_edit_wizard = True
                    wizard.can_group_payments = len(batch_result['lines']) != 1
                else:
                    # == Multiple batches: The wizard is not editable  ==
                    wizard.update({
                        'company_id': batches[0]['lines'][0].company_id._accessible_branches()[:1].id,
                        'partner_id': False,
                        'partner_type': False,
                        'payment_type': wizard_values_from_batch['payment_type'],
                        'source_currency_id': False,
                        'source_amount': False,
                        'source_amount_currency': False,
                    })
    
                    wizard.can_edit_wizard = False
                    wizard.can_group_payments = any(len(batch_result['lines']) != 1 for batch_result in batches)
                
    @api.depends('can_edit_wizard')
    def _compute_communication(self):
        # The communication can't be computed in '_compute_from_lines' because
        # it's a compute editable field and then, should be computed in a separated method.
        for wizard in self:
                wizard.communication = False

    @api.depends('can_edit_wizard')
    def _compute_group_payment(self):
        for wizard in self:
            if wizard.can_edit_wizard:
                    batches = wizard._get_batches()
                    if batches:
                        wizard.group_payment = len(batches[0]['lines'].move_id) == 1
                    else:
                        wizard.group_payment = False
            else:
                wizard.group_payment = False

    @api.depends('can_edit_wizard', 'journal_id')
    def _compute_available_partner_bank_ids(self):
        for wizard in self:
            if wizard.can_edit_wizard:
                batches = wizard._get_batches()
                if batches:
                    batch = batches[0]
                    wizard.available_partner_bank_ids = wizard._get_batch_available_partner_banks(batch, wizard.journal_id)
                else:
                    wizard.available_partner_bank_ids = None
            else:
                wizard.available_partner_bank_ids = None
                
    @api.depends('journal_id', 'available_partner_bank_ids')
    def _compute_partner_bank_id(self):
        for wizard in self:
            if wizard.can_edit_wizard:
                batches = wizard._get_batches()
                if batches:
                    batch = batches[0]
                    partner_bank_id = batch['payment_values']['partner_bank_id']
                    available_partner_banks = wizard.available_partner_bank_ids._origin
                    if partner_bank_id and partner_bank_id in available_partner_banks.ids:
                        wizard.partner_bank_id = self.env['res.partner.bank'].browse(partner_bank_id)
                    else:
                        wizard.partner_bank_id = available_partner_banks[:1]
                else:
                    wizard.partner_bank_id = None
            else:
                wizard.partner_bank_id = None
    @api.depends('can_edit_wizard', 'amount')
    def _compute_payment_difference(self):
        for wizard in self:
            if wizard.can_edit_wizard and wizard.payment_date:
                batches = wizard._get_batches()
                if batches:
                    batch_result = batches[0]
                    total_amount_residual_in_wizard_currency = wizard\
                        ._get_total_amount_in_wizard_currency_to_full_reconcile(batch_result, early_payment_discount=False)[0]
                    wizard.payment_difference = total_amount_residual_in_wizard_currency - wizard.amount
                else:
                    wizard.payment_difference = 0.0
            else:
                wizard.payment_difference = 0.0
                
    @api.depends('payment_type', 'company_id', 'can_edit_wizard')
    def _compute_available_journal_ids(self):
        for wizard in self:
            available_journals = self.env['account.journal']
            batches = wizard._get_batches()
            if batches:
                for batch in batches:
                    available_journals |= wizard._get_batch_available_journals(batch)
                wizard.available_journal_ids = [Command.set(available_journals.ids)]
            else:
                available_journals = self.env['account.journal'].search([
                    ('company_id', '=', wizard.company_id.id), # Filtra por la empresa seleccionada
                    ('type', 'in', ['bank', 'cash']) # Puedes ajustar esto según el tipo de diario requerido
                ])
                wizard.available_journal_ids = [Command.set(available_journals.ids)]



    @api.depends('can_edit_wizard', 'payment_date', 'currency_id', 'amount')
    def _compute_early_payment_discount_mode(self):
        for wizard in self:
            if not wizard.journal_id or not wizard.currency_id or not wizard.payment_date:
                wizard.early_payment_discount_mode = wizard.early_payment_discount_mode
            elif wizard.can_edit_wizard:
                batches = wizard._get_batches()
                if batches:
                    batch_result = wizard._get_batches()[0]
                    total_amount_residual_in_wizard_currency, mode = wizard._get_total_amount_in_wizard_currency_to_full_reconcile(batch_result)
                    wizard.early_payment_discount_mode = \
                        wizard.currency_id.compare_amounts(wizard.amount, total_amount_residual_in_wizard_currency) == 0 \
                        and mode == 'early_payment'
                else:
                    wizard.early_payment_discount_mode = False
            else:
                wizard.early_payment_discount_mode = False