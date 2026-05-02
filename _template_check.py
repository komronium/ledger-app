"""Quick template render smoke test."""
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.template.loader import get_template
from django.template import Context, RequestContext
from django.test import RequestFactory
from django.contrib.auth.models import AnonymousUser

from finance.models import (
    Customer, Product, Supplier, Purchase, SupplierPayment, Order, PaymentHistory, Expense,
)

# Pick first records or empty querysets — just verify templates parse and render.
factory = RequestFactory()
req = factory.get('/')
req.user = AnonymousUser()

base_ctx = {
    'request': req,
    'csrf_token': 'test',
    'page': 'dashboard',
    'today': '2026-05-02',
    'errors': None,
    'orders': [],
    'customers': Customer.objects.all(),
    'products': Product.objects.all(),
    'products_json': '[]',
    'all_products': Product.objects.all(),
    'customer': None,
    'total_quantity': 0,
    'total_price': 0,
    'total_paid_amount': 0,
    'total_debt': 0,
}

for tpl in ['order.html', 'order_edit.html', 'supplier_detail.html']:
    t = get_template(tpl)
    if tpl == 'order_edit.html':
        order = Order.objects.first()
        ctx = dict(base_ctx, form=None, order=order)
        if not order:
            print(f"SKIP {tpl} - no Order instance")
            continue
    elif tpl == 'supplier_detail.html':
        sup = Supplier.objects.first()
        if not sup:
            print(f"SKIP {tpl} - no Supplier instance")
            continue
        ctx = dict(base_ctx,
            supplier=sup,
            purchases=Purchase.objects.filter(supplier=sup),
            payments=SupplierPayment.objects.filter(supplier=sup),
            total_purchased=0, total_paid=0, total_owed=0, debt=0,
            revenue=0, profit=0, products=Product.objects.filter(supplier=sup),
            all_products=Product.objects.all(),
        )
    else:
        ctx = base_ctx
    try:
        out = t.render(ctx, req)
        print(f"OK   {tpl}  ({len(out)} chars)")
    except Exception as e:
        print(f"FAIL {tpl}: {e!r}")
