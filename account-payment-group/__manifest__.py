# -*- coding: utf-8 -*-
{
    'name': "Account Payment with multiple methods",

    'summary': """
        Este modulo permite usar multiples metodos de pago en una sola orden""",

    'description': """
        Este modulo permite usar multiples metodos de pago en una sola orden
    """,

    'author': "AAAAAAAAA",
    'website': "http://www.yourcompany.com",
    "license": "AGPL-3",
    'installable': True,
    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/master/odoo/addons/base/module/module_data.xml
    # for the full list
    'category': 'Payment',
    'version': '17.0.0.1',

    # any module necessary for this one to work correctly
    "external_dependencies": {
        "python": [],
        "bin": [], 
    }, 
    "depends": [
        "account",
        "account_payment",
        "account_payment_pro",
        "l10n_ar_withholding_ux",
        "l10n_ar_account_withholding", 
    ],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'views/views.xml',
        'views/account_payment_register.xml',
        'views/report_withholdings_certificate_template.xml',
        'views/report_payment_with_withholdings.xml',
    ],
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],
}