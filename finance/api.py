"""
HTTP API consumed by the Telegram bot running on a separate server.

All endpoints are read-only and authenticated with a shared token sent
in the `X-Bot-Token` header (matching `settings.BOT_API_TOKEN`).
"""
from functools import wraps
from hmac import compare_digest

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from finance.models import (
    Customer,
    Order,
    PaymentHistory,
    Purchase,
    Supplier,
    SupplierPayment,
)


def _last9_digits(phone):
    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())
    return digits[-9:]


def bot_api_token_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        expected = getattr(settings, 'BOT_API_TOKEN', '') or ''
        provided = request.headers.get('X-Bot-Token', '') or ''
        if not expected or not compare_digest(expected, provided):
            return JsonResponse({'detail': 'Unauthorized'}, status=401)
        return view_func(request, *args, **kwargs)
    return wrapper


def _customer_dict(customer):
    return {
        'id': customer.id,
        'name': customer.name,
        'phone': customer.phone,
        'address': customer.address,
        'default_debt': customer.default_debt,
        'total_debt': customer.total_debt,
    }


def _supplier_dict(supplier):
    return {
        'id': supplier.id,
        'name': supplier.name,
        'phone': supplier.phone or '',
        'address': supplier.address or '',
        'initial_debt': supplier.initial_debt,
    }


@require_GET
@bot_api_token_required
def customers_list(request):
    customers = Customer.objects.all().order_by('name')
    return JsonResponse({'results': [_customer_dict(c) for c in customers]})


@require_GET
@bot_api_token_required
def customer_by_phone(request):
    phone = request.GET.get('phone', '')
    target = _last9_digits(phone)
    if len(target) < 9:
        return JsonResponse({'detail': 'Not found'}, status=404)

    customer = next(
        (
            c for c in Customer.objects
            .exclude(phone__isnull=True)
            .exclude(phone__exact='')
            if _last9_digits(c.phone) == target
        ),
        None,
    )
    if not customer:
        return JsonResponse({'detail': 'Not found'}, status=404)
    return JsonResponse(_customer_dict(customer))


@require_GET
@bot_api_token_required
def customer_summary(request, customer_id):
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return JsonResponse({'detail': 'Not found'}, status=404)

    orders = Order.objects.filter(customer_id=customer_id)
    total_ordered = sum(order.total_price for order in orders)

    return JsonResponse({
        'total_ordered': total_ordered,
        'total_debt': customer.total_debt,
        'customer_default_debt': customer.default_debt,
        'orders_count': orders.count(),
    })


@require_GET
@bot_api_token_required
def customer_combined(request, customer_id):
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return JsonResponse({'detail': 'Not found'}, status=404)

    orders = Order.objects.filter(customer_id=customer_id).order_by('order_date')
    payments = PaymentHistory.objects.filter(customer_id=customer_id).order_by('paid_at')

    payment_type_dict = dict(PaymentHistory.PaymentTypeChoices.choices)
    combined_data = []

    for order in orders:
        combined_data.append({
            'type': 'order',
            'id': order.id,
            'product': order.product.name if order.product else 'N/A',
            'quantity': order.quantity,
            'price_per_kg': order.price_per_kg,
            'date': order.order_date.strftime('%Y-%m-%d'),
            'total_price': order.total_price,
            'remaining_debt': order.remaining_debt,
        })

    for payment in payments:
        combined_data.append({
            'type': 'payment',
            'id': payment.id,
            'product': '',
            'quantity': 0,
            'price_per_kg': 0,
            'paid_amount': float(payment.amount),
            'date': payment.paid_at.strftime('%Y-%m-%d'),
            'total_price': 0,
            'remaining_debt': -float(payment.amount),
            'payment_type': payment_type_dict.get(payment.payment_type, payment.payment_type),
            'comment': payment.comment or '',
        })

    type_priority = {'order': 0, 'payment': 1}
    combined_data.sort(key=lambda x: (x['date'], type_priority.get(x['type'], 9), x['id']))

    total_filtered_debt = sum(
        item['remaining_debt'] for item in combined_data if item['type'] == 'order'
    ) - sum(
        item['paid_amount'] for item in combined_data if item['type'] == 'payment'
    )
    cumulative_debt = customer.total_debt - total_filtered_debt

    for item in combined_data:
        if item['type'] == 'order':
            cumulative_debt += item['remaining_debt']
        else:
            cumulative_debt -= item['paid_amount']
        item['cumulative_debt'] = cumulative_debt

    return JsonResponse({
        'customer': _customer_dict(customer),
        'combined_data': combined_data,
    })


@require_GET
@bot_api_token_required
def supplier_by_phone(request):
    phone = request.GET.get('phone', '')
    target = _last9_digits(phone)
    if len(target) < 9:
        return JsonResponse({'detail': 'Not found'}, status=404)

    supplier = next(
        (
            s for s in Supplier.objects
            .exclude(phone__isnull=True)
            .exclude(phone__exact='')
            if _last9_digits(s.phone) == target
        ),
        None,
    )
    if not supplier:
        return JsonResponse({'detail': 'Not found'}, status=404)
    return JsonResponse(_supplier_dict(supplier))


@require_GET
@bot_api_token_required
def supplier_report(request, supplier_id):
    try:
        supplier = Supplier.objects.get(id=supplier_id)
    except Supplier.DoesNotExist:
        return JsonResponse({'detail': 'Not found'}, status=404)

    purchases = (
        Purchase.objects.filter(supplier=supplier)
        .select_related('product', 'barter_product')
        .order_by('purchase_date')
    )
    payments = (
        SupplierPayment.objects.filter(supplier=supplier)
        .select_related('barter_product')
        .order_by('paid_at')
    )

    purchase_type_dict = dict(Purchase.PurchaseTypeChoices.choices)
    payment_type_dict = dict(SupplierPayment.PaymentTypeChoices.choices)

    rows = []
    for p in purchases:
        rows.append({
            'type': 'purchase',
            'date': p.purchase_date.strftime('%Y-%m-%d'),
            'description': (p.product.name if p.product else '—'),
            'kind': purchase_type_dict.get(p.purchase_type, p.purchase_type),
            'quantity': p.quantity,
            'price_per_unit': p.price_per_unit or 0,
            'amount': p.total_cost,
            'note': p.note or '',
        })
    for pay in payments:
        extra = ''
        if pay.payment_type == SupplierPayment.PaymentTypeChoices.BARTER and pay.barter_product:
            extra = f"{pay.barter_product.name} x {pay.barter_quantity}"
        rows.append({
            'type': 'payment',
            'date': pay.paid_at.strftime('%Y-%m-%d'),
            'description': extra or (pay.comment or '—'),
            'kind': payment_type_dict.get(pay.payment_type, pay.payment_type or '—'),
            'quantity': 0,
            'price_per_unit': 0,
            'amount': pay.amount,
            'note': pay.comment or '',
        })

    rows.sort(key=lambda r: r['date'])

    total_purchased = sum(r['amount'] for r in rows if r['type'] == 'purchase')
    total_paid = sum(r['amount'] for r in rows if r['type'] == 'payment')
    debt = supplier.initial_debt + total_purchased - total_paid

    running = supplier.initial_debt
    for r in rows:
        if r['type'] == 'purchase':
            running += r['amount']
        else:
            running -= r['amount']
        r['cumulative_debt'] = running

    return JsonResponse({
        'supplier': _supplier_dict(supplier),
        'rows': rows,
        'total_purchased': total_purchased,
        'total_paid': total_paid,
        'debt': debt,
    })
