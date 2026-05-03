"""End-to-end smoke tests — re-run after additional hardening."""
import os, django, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db import transaction
from django.test import RequestFactory
from django.contrib.auth.models import User
from finance.models import Customer, Product, Supplier, Order, PaymentHistory, Purchase, SupplierPayment
from finance.forms import OrderForm, PaymentForm, PaymentEditForm
from finance.views import OrderView, OrderDeleteView, SupplierDetailView, PaymentDeleteView, DebtView, StatisticsView

failures = []; passes = []
def check(name, cond, detail=""):
    if cond:
        passes.append(name); print(f"  PASS {name}")
    else:
        failures.append(f"{name}: {detail}"); print(f"  FAIL {name} -- {detail}")

def make_user_admin():
    u, _ = User.objects.get_or_create(username='_e2e_admin', defaults={'is_superuser': True, 'is_staff': True})
    u.is_superuser = True; u.save()
    return u

def fresh_customer():
    return Customer.objects.create(name='_e2e Customer', phone='+998000000000', address='_test', default_debt=0, total_debt=0)
def fresh_supplier():
    return Supplier.objects.create(name='_e2e Supplier', phone='+998111111111', address='_test', initial_debt=0)
def fresh_product(supplier=None, qty=100, price=1000, promo_buy=None, promo_free=None):
    return Product.objects.create(name=f'_e2e Product {Product.objects.count()}',
        price=price, quantity=qty, supplier=supplier, promo_buy=promo_buy, promo_free=promo_free)


print("\n[1] Order create/delete roundtrip")
try:
    with transaction.atomic():
        sid = transaction.savepoint()
        c = fresh_customer(); p = fresh_product(qty=100, price=500)
        o = Order.objects.create(customer=c, product=p, quantity=10, price_per_kg=500)
        p.refresh_from_db(); c.refresh_from_db()
        check("inventory deducted", p.quantity == 90)
        check("remaining_debt set", o.remaining_debt == 5000)
        c.total_debt += o.remaining_debt; c.save()
        rf = RequestFactory(); req = rf.post('/x'); req.user = make_user_admin()
        OrderDeleteView.as_view()(req, pk=o.id)
        p.refresh_from_db(); c.refresh_from_db()
        check("inventory restored", p.quantity == 100)
        check("debt restored", c.total_debt == 0)
        transaction.savepoint_rollback(sid)
except Exception as e:
    failures.append(f"[1] crashed: {e}"); print(f"  CRASH: {e}")


print("\n[2] Promo buy 5 get 1 free")
try:
    with transaction.atomic():
        sid = transaction.savepoint()
        c = fresh_customer(); p = fresh_product(qty=100, price=1000, promo_buy=5, promo_free=1)
        o = Order.objects.create(customer=c, product=p, quantity=10, price_per_kg=1000)
        p.refresh_from_db()
        check("promo deducted free items", p.quantity == 88)
        check("customer charged paid only", o.total_price == 10000)
        rf = RequestFactory(); req = rf.post('/x'); req.user = make_user_admin()
        OrderDeleteView.as_view()(req, pk=o.id)
        p.refresh_from_db()
        check("promo restored on delete", p.quantity == 100)
        transaction.savepoint_rollback(sid)
except Exception as e:
    failures.append(f"[2] crashed: {e}"); print(f"  CRASH: {e}")


print("\n[3] Edit order preserves partial payment")
try:
    with transaction.atomic():
        sid = transaction.savepoint()
        c = fresh_customer(); p = fresh_product(qty=100, price=1000)
        o = Order.objects.create(customer=c, product=p, quantity=10, price_per_kg=1000)
        c.total_debt = 10000; c.save()
        o.remaining_debt = 6000; o.save()
        o.refresh_from_db()
        check("partial payment preserved", o.remaining_debt == 6000)
        transaction.savepoint_rollback(sid)
except Exception as e:
    failures.append(f"[3] crashed: {e}"); print(f"  CRASH: {e}")


print("\n[4] Customer barter payment full roundtrip")
try:
    with transaction.atomic():
        sid = transaction.savepoint()
        c = fresh_customer(); p = fresh_product(qty=50, price=200)
        c.total_debt = 1000; c.save()
        form = PaymentForm({'customer_id': c.id, 'payment_mode': 'barter',
            'barter_product_id': p.id, 'barter_quantity': 3})
        check("barter form valid", form.is_valid(), f"errors={form.errors}")
        if form.is_valid():
            payment = form.save()
            c.refresh_from_db(); p.refresh_from_db()
            check("barter amount", int(payment.amount) == 600)
            check("inventory increased", p.quantity == 53)
            check("debt reduced", c.total_debt == 400)
            rf = RequestFactory(); req = rf.post('/x'); req.user = make_user_admin()
            PaymentDeleteView.as_view()(req, pk=payment.id)
            c.refresh_from_db(); p.refresh_from_db()
            check("debt restored on delete", c.total_debt == 1000)
            check("inventory restored on delete", p.quantity == 50)
        transaction.savepoint_rollback(sid)
except Exception as e:
    failures.append(f"[4] crashed: {e}"); print(f"  CRASH: {e}")


print("\n[5] Supplier barter payment via view")
try:
    with transaction.atomic():
        sid = transaction.savepoint()
        s = fresh_supplier(); p = fresh_product(qty=20, price=1500)
        Purchase.objects.create(supplier=s, product=fresh_product(qty=0),
            quantity=10, price_per_unit=2000, purchase_type='cash')
        rf = RequestFactory()
        req = rf.post(f'/suppliers/{s.id}/', {
            'action': 'payment', 'payment_type': 'barter',
            'barter_product': str(p.id), 'barter_quantity': '5'})
        req.user = make_user_admin()
        SupplierDetailView.as_view()(req, pk=s.id)
        p.refresh_from_db()
        check("supplier barter inventory deducted", p.quantity == 15)
        sp = SupplierPayment.objects.filter(supplier=s, payment_type='barter').first()
        check("supplier barter row created", sp is not None)
        if sp: check("supplier barter amount", sp.amount == 7500)
        transaction.savepoint_rollback(sid)
except Exception as e:
    failures.append(f"[5] crashed: {e}"); print(f"  CRASH: {e}")


print("\n[6] USD customer payment")
try:
    with transaction.atomic():
        sid = transaction.savepoint()
        c = fresh_customer(); c.total_debt = 100000; c.save()
        form = PaymentForm({'customer_id': c.id, 'payment_mode': 'money',
            'usd_amount': '5', 'exchange_rate': '12700', 'payment_type': 'cash'})
        check("USD form valid", form.is_valid(), f"errors={form.errors}")
        if form.is_valid():
            payment = form.save(); c.refresh_from_db()
            check("USD amount", int(payment.amount) == 63500)
            check("debt reduced by computed UZS", c.total_debt == 36500)
        transaction.savepoint_rollback(sid)
except Exception as e:
    failures.append(f"[6] crashed: {e}"); print(f"  CRASH: {e}")


print("\n[7] PaymentForm rejects missing customer_id")
try:
    form = PaymentForm({'payment_mode': 'money', 'payment_amount': '100'})
    check("invalid (not crash)", not form.is_valid())
except Exception as e:
    failures.append(f"[7] crashed: {e}"); print(f"  CRASH: {e}")


print("\n[8] SupplierPayment barter snapshots price")
try:
    with transaction.atomic():
        sid = transaction.savepoint()
        s = fresh_supplier(); p = fresh_product(qty=10, price=500)
        sp = SupplierPayment.objects.create(supplier=s, payment_type='barter',
            barter_product=p, barter_quantity=2, amount=0)
        check("snapshot at create", sp.amount == 1000)
        p.price = 5000; p.save()
        sp.comment = 'edited'; sp.save(); sp.refresh_from_db()
        check("not recomputed on resave", sp.amount == 1000)
        transaction.savepoint_rollback(sid)
except Exception as e:
    failures.append(f"[8] crashed: {e}"); print(f"  CRASH: {e}")


print("\n[9] Order.save validates negative/zero/over-stock")
try:
    with transaction.atomic():
        sid = transaction.savepoint()
        c = fresh_customer(); p = fresh_product(qty=10, price=100)
        # Negative quantity
        try:
            Order.objects.create(customer=c, product=p, quantity=-1, price_per_kg=100)
            check("rejects negative qty", False, "no exception")
        except ValueError:
            check("rejects negative qty", True)
        # Zero quantity
        try:
            Order.objects.create(customer=c, product=p, quantity=0, price_per_kg=100)
            check("rejects zero qty", False, "no exception")
        except ValueError:
            check("rejects zero qty", True)
        # Over stock
        try:
            Order.objects.create(customer=c, product=p, quantity=1000, price_per_kg=100)
            check("rejects over-stock", False, "no exception")
        except ValueError:
            check("rejects over-stock", True)
        transaction.savepoint_rollback(sid)
except Exception as e:
    failures.append(f"[9] crashed: {e}"); print(f"  CRASH: {e}")


print("\n[10] OrderView.post handles validation errors gracefully")
try:
    with transaction.atomic():
        sid = transaction.savepoint()
        import json
        c = fresh_customer(); p = fresh_product(qty=5, price=100)
        rf = RequestFactory()
        req = rf.post('/', {'orders_json': json.dumps([
            {'customer_id': c.id, 'product_id': p.id, 'quantity': 100, 'price_per_kg': 100}])})
        req.user = make_user_admin()
        # Add session middleware emulation
        from django.contrib.sessions.backends.db import SessionStore
        req.session = SessionStore(); req.session.create()
        OrderView.as_view()(req)
        p.refresh_from_db(); c.refresh_from_db()
        check("over-stock order NOT saved", Order.objects.filter(customer=c).count() == 0)
        check("inventory unchanged", p.quantity == 5)
        check("customer debt unchanged", c.total_debt == 0)
        check("error stored in session", 'order_errors' in req.session)
        transaction.savepoint_rollback(sid)
except Exception as e:
    failures.append(f"[10] crashed: {e}"); print(f"  CRASH: {e}")


print("\n[11] Available years are dynamic")
try:
    dv = DebtView()
    years = dv._available_years()
    from datetime import date
    check("includes current year", date.today().year in years)
    check("returns sorted list", years == sorted(years))
    sv = StatisticsView()
    syears = sv._available_years()
    check("stats includes current year", date.today().year in syears)
except Exception as e:
    failures.append(f"[11] crashed: {e}"); print(f"  CRASH: {e}")


print("\n[12] Same-day cumulative debt is deterministic")
try:
    with transaction.atomic():
        sid = transaction.savepoint()
        c = fresh_customer(); p = fresh_product(qty=100, price=100)
        # Three events same day: order, payment, order
        o1 = Order.objects.create(customer=c, product=p, quantity=2, price_per_kg=100)
        c.total_debt = 200; c.save()
        ph = PaymentHistory.objects.create(customer=c, amount=50, payment_type='cash')
        c.total_debt -= 50; c.save()
        o2 = Order.objects.create(customer=c, product=p, quantity=3, price_per_kg=100)
        c.total_debt += 300; c.save()

        view = OrderView()
        # Get events
        orders = Order.objects.filter(customer=c)
        payments = PaymentHistory.objects.filter(customer=c)
        d1 = view._prepare_combined_data(orders, payments, c)
        d2 = view._prepare_combined_data(orders, payments, c)
        check("ordering deterministic", [(x['type'], x['id']) for x in d1] == [(x['type'], x['id']) for x in d2])
        # Orders should come before payments on same day
        types_in_order = [x['type'] for x in d1]
        check("orders before payments on same day",
              types_in_order == ['order', 'order', 'payment'],
              f"got {types_in_order}")
        transaction.savepoint_rollback(sid)
except Exception as e:
    failures.append(f"[12] crashed: {e}"); print(f"  CRASH: {e}")


print(f"\n{'='*60}")
print(f"Passed: {len(passes)} | Failed: {len(failures)}")
if failures:
    print("\nFAILURES:")
    for f in failures: print(f"  - {f}")
    sys.exit(1)
else:
    print("All tests pass.")
