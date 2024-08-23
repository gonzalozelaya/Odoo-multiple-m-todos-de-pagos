import re
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class AccountJournal(models.Model):
    _inherit = 'account.journal'
    
    l10n_check_next_number = fields.Char(
        string='Next Check Number',
        compute='l10n_compute_check_next_number',
        inverse='l10n_inverse_check_next_number',
        help="Sequence number of the next printed check.",
    )

    @api.depends('check_manual_sequencing')
    def l10n_compute_check_next_number(self):
        for journal in self:
            sequence = journal.check_sequence_id
            if sequence:
                journal.l10n_check_next_number = sequence.get_next_char(sequence.number_next_actual)
            else:
                journal.l10n_check_next_number = 1

    def l10n_inverse_check_next_number(self):
        for journal in self:
            if journal.l10n_check_next_number and not re.match(r'^[0-9]+$', journal.l10n_check_next_number):
                raise ValidationError(_('Next Check Number should only contains numbers.'))
            if int(journal.l10n_check_next_number) < journal.check_sequence_id.number_next_actual:
                raise ValidationError(_(
                    "The last check number was %s. In order to avoid a check being rejected "
                    "by the bank, you can only use a greater number.",
                    journal.l10n_check_sequence_id.number_next_actual
                ))
            if journal.check_sequence_id:
                journal.check_sequence_id.sudo().number_next_actual = int(journal.l10n_check_next_number)
                journal.check_sequence_id.sudo().padding = len(journal.l10n_check_next_number)
    
    def increment_sequence(self):
        for journal in self:
            sequence = journal.check_sequence_id
            if sequence:
                sequence.next_by_id()
                journal.l10n_check_next_number = sequence.get_next_char(sequence.number_next_actual)
        