import json
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView as LView
from django.db import models
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.timezone import make_naive
from django.views import View

from finance.filters import CustomerFilter, OrderFilter, PaymentFilter
from finance.forms import (
    CustomerForm,
    ExpenseForm,
    OrderForm,
    PaymentEditForm,
    PaymentForm,
    ProductForm,
    PurchaseForm,
    SupplierForm,
    SupplierPaymentForm,
)
from finance.models import (
    Customer,
    Expense,
    Order,
    PaymentHistory,
    Product,
    Purchase,
    Supplier,
    SupplierPayment,
    UserProfile,
)


def _is_admin(user):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    try:
        return user.profile.role == UserProfile.ROLE_ADMIN
    except Exception:
        return False


def _to_decimal(value):
    if value in (None, ""):
        return None
    cleaned = str(value).replace(",", ".").replace(" ", "").strip()
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


class AdminOnlyMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not _is_admin(request.user):
            return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)


class LoginView(LView):
    template_name = "login.html"
    redirect_authenticated_user = True


class LogoutView(View):
    def get(self, request):
        from django.contrib.auth import logout

        logout(request)
        return redirect("login")


class OrderView(LoginRequiredMixin, View):
    template_name = "order.html"

    def _get_payment_data(self, customer_id, date_from=None, date_to=None):
        payments = PaymentHistory.objects.filter(customer_id=customer_id)
        if date_from:
            payments = payments.filter(paid_at__date__gte=date_from)
        if date_to:
            payments = payments.filter(paid_at__date__lte=date_to)
        return payments.order_by("-paid_at")

    def _prepare_combined_data(self, orders, payments, customer):
        combined_data = []
        # Group orders by (customer_id, batch_id, order_date). Orders without
        # batch_id stay as their own single-item group.
        groups = {}
        ordered_keys = []
        for order in orders:
            cust_id = order.customer_id
            if order.batch_id:
                key = ("g", cust_id, order.batch_id)
            else:
                key = ("o", order.id)
            if key not in groups:
                groups[key] = {
                    "type": "order",
                    "id": order.batch_id or f"single-{order.id}",
                    "primary_id": order.id,
                    "batch_id": order.batch_id,
                    "customer": order.customer if order.customer else "",
                    "order_date": order.order_date,
                    "items": [],
                    "quantity": 0,
                    "total_price": 0,
                    "remaining_debt": 0,
                }
                ordered_keys.append(key)
            g = groups[key]
            g["items"].append({
                "id": order.id,
                "product": order.product,
                "product_name": order.product.name if order.product else "—",
                "quantity": order.quantity,
                "price_per_kg": order.price_per_kg,
                "total_price": order.total_price,
            })
            g["quantity"] += order.quantity
            g["total_price"] += order.total_price
            g["remaining_debt"] += order.remaining_debt
            # Use earliest order_date in group (they should all match anyway)
            if order.order_date < g["order_date"]:
                g["order_date"] = order.order_date

        for key in ordered_keys:
            combined_data.append(groups[key])

        for payment in payments:
            combined_data.append(
                {
                    "type": "payment",
                    "id": payment.id,
                    "customer": payment.customer,
                    "product": payment.barter_product
                    if payment.payment_type == "barter"
                    else "",
                    "quantity": payment.barter_quantity
                    if payment.payment_type == "barter"
                    else 0,
                    "price_per_kg": (
                        payment.barter_product.price if payment.barter_product else 0
                    )
                    if payment.payment_type == "barter"
                    else 0,
                    "paid_amount": payment.amount,
                    "usd_amount": payment.usd_amount,
                    "exchange_rate": payment.exchange_rate,
                    "order_date": payment.paid_at.date(),
                    "total_price": 0,
                    "remaining_debt": -payment.amount,
                    "payment_type": payment.payment_type,
                    "comment": payment.comment,
                }
            )

        # Stable order: by date, then orders before payments (same day),
        # then by primary id (insertion order). Keeps the cumulative-debt walk
        # deterministic across requests.
        type_priority = {"order": 0, "payment": 1}
        combined_data.sort(
            key=lambda x: (
                x["order_date"],
                type_priority.get(x["type"], 9),
                x.get("primary_id") or x.get("id"),
            )
        )
        return combined_data

    def _calculate_cumulative_debt(self, combined_data, customer):
        cumulative_debt = customer.total_debt

        total_filtered_debt = sum(
            item["remaining_debt"] for item in combined_data if item["type"] == "order"
        ) - sum(
            item["paid_amount"] for item in combined_data if item["type"] == "payment"
        )

        cumulative_debt = cumulative_debt - total_filtered_debt

        for item in combined_data:
            if item["type"] == "order":
                cumulative_debt += item["remaining_debt"]
            elif item["type"] == "payment":
                cumulative_debt -= item["paid_amount"]
            item["remaining_debt"] = cumulative_debt

        return combined_data

    def get(self, request):
        query_params = request.GET.copy()
        if not query_params.get("customer_id"):
            query_params["date_from"] = query_params.get("date_from") or date.today()
            query_params["date_to"] = query_params.get("date_to") or date.today()

        filtered_orders = OrderFilter(
            query_params,
            queryset=Order.objects.order_by("order_date").select_related(
                "customer", "product"
            ),
        ).qs

        customer = None
        if request.GET.get("customer_id"):
            try:
                customer = Customer.objects.get(id=request.GET.get("customer_id"))
            except Customer.DoesNotExist:
                pass

        if customer:
            date_from = query_params.get("date_from")
            date_to = query_params.get("date_to")
            payments = self._get_payment_data(customer.id, date_from, date_to)

            combined_data = self._prepare_combined_data(
                filtered_orders, payments, customer
            )
            combined_data = self._calculate_cumulative_debt(combined_data, customer)

            total_quantity = sum(
                item["quantity"] for item in combined_data if item["type"] == "order"
            )
            total_price = sum(
                item["total_price"] for item in combined_data if item["type"] == "order"
            )
            total_paid_amount = sum(
                item["paid_amount"]
                for item in combined_data
                if item["type"] == "payment"
            )
            total_debt = customer.total_debt
            order_data = combined_data
        else:
            order_aggs = filtered_orders.aggregate(
                total_quantity=models.Sum("quantity"),
                total_price=models.Sum("total_price"),
                total_debt=models.Sum("remaining_debt"),
            )

            totals = {
                "total_quantity": order_aggs["total_quantity"] or 0,
                "total_price": order_aggs["total_price"] or 0,
                "total_debt": order_aggs["total_debt"] or 0,
            }

            # Group orders into batches (same as customer view).
            groups = {}
            ordered_keys = []
            for order in filtered_orders:
                if order.batch_id:
                    key = ("g", order.customer_id, order.batch_id)
                else:
                    key = ("o", order.id)
                if key not in groups:
                    groups[key] = {
                        "type": "order",
                        "id": order.batch_id or f"single-{order.id}",
                        "primary_id": order.id,
                        "batch_id": order.batch_id,
                        "customer": order.customer,
                        "order_date": order.order_date,
                        "items": [],
                        "quantity": 0,
                        "total_price": 0,
                        "remaining_debt": 0,
                    }
                    ordered_keys.append(key)
                g = groups[key]
                g["items"].append({
                    "id": order.id,
                    "product": order.product,
                    "product_name": order.product.name if order.product else "—",
                    "quantity": order.quantity,
                    "price_per_kg": order.price_per_kg,
                    "total_price": order.total_price,
                })
                g["quantity"] += order.quantity
                g["total_price"] += order.total_price
                g["remaining_debt"] += order.remaining_debt

            order_data = [groups[k] for k in ordered_keys]

            total_quantity = totals["total_quantity"]
            total_price = totals["total_price"]
            total_paid_amount = 0
            total_debt = totals["total_debt"]

        products_list = list(
            Product.objects.values(
                "id", "name", "price", "quantity", "promo_buy", "promo_free"
            )
        )
        import json as _json

        products_json = _json.dumps(products_list)

        # Slim, JSON-serializable view of order rows for the receipt modal.
        orders_for_js = []
        for row in order_data:
            if row.get("type") != "order":
                orders_for_js.append({"type": "payment"})
                continue
            orders_for_js.append({
                "type": "order",
                "batch_id": row.get("batch_id"),
                "primary_id": row.get("primary_id"),
                "customer_name": row["customer"].name if row.get("customer") else "",
                "order_date": row["order_date"].strftime("%d.%m.%Y") if row.get("order_date") else "",
                "items": [
                    {
                        "id": it["id"],
                        "name": it["product_name"],
                        "quantity": int(it["quantity"]),
                        "price_per_kg": int(it["price_per_kg"]),
                        "total_price": int(it["total_price"]),
                    }
                    for it in row.get("items", [])
                ],
                # remaining_debt may be Decimal because PaymentHistory.amount is
                # a DecimalField — coerce to int for JSON.
                "total_price": int(row.get("total_price", 0)),
                "remaining_debt": int(row.get("remaining_debt", 0)),
            })
        orders_view_json = _json.dumps(orders_for_js)

        errors = request.session.pop("order_errors", None)

        context = {
            "orders": order_data,
            "orders_view_json": orders_view_json,
            "customers": Customer.objects.all(),
            "products": Product.objects.all(),
            "products_json": products_json,
            "today": date.today().strftime("%Y-%m-%d"),
            "total_quantity": total_quantity,
            "total_price": total_price,
            "total_paid_amount": total_paid_amount,
            "total_debt": total_debt,
            "page": "dashboard",
            "customer": customer,
            "errors": errors,
        }

        return render(request, self.template_name, context=context)

    def post(self, request):
        import uuid

        from django.db import transaction

        orders_json = request.POST.get("orders_json", "[]")
        try:
            orders_data = json.loads(orders_json)
        except json.JSONDecodeError:
            orders_data = []

        batch_id = uuid.uuid4().hex if len(orders_data) > 0 else None

        errors = []
        for item in orders_data:
            try:
                customer = Customer.objects.get(id=item.get("customer_id"))
                product = Product.objects.get(id=item.get("product_id"))
                requested_quantity = int(item.get("quantity", 0))
                price_per_kg = int(item.get("price_per_kg", 0))
            except (Customer.DoesNotExist, Product.DoesNotExist, ValueError, TypeError):
                errors.append("Buyurtma ma'lumotlari noto'g'ri (mijoz, mahsulot yoki miqdor).")
                continue

            if requested_quantity <= 0:
                errors.append(f"{product.name}: miqdor 0 dan katta bo'lishi kerak.")
                continue
            if price_per_kg < 0:
                errors.append(f"{product.name}: narx manfiy bo'lishi mumkin emas.")
                continue

            try:
                with transaction.atomic():
                    # Re-fetch with row lock so concurrent orders don't race
                    product = Product.objects.select_for_update().get(pk=product.pk)
                    free_count = 0
                    if product.promo_buy and product.promo_free and product.promo_buy > 0:
                        free_count = (requested_quantity // product.promo_buy) * product.promo_free
                    total_to_deduct = requested_quantity + free_count
                    if product.quantity < total_to_deduct:
                        if free_count:
                            errors.append(
                                f"{product.name}: {requested_quantity} so'raldi + {free_count} aksiya = {total_to_deduct} kerak, lekin {product.quantity} mavjud."
                            )
                        else:
                            errors.append(
                                f"{product.name}: {requested_quantity} kg so'raldi, lekin {product.quantity} kg mavjud."
                            )
                        continue

                    order = Order(
                        customer=customer,
                        product=product,
                        quantity=requested_quantity,
                        price_per_kg=price_per_kg,
                        batch_id=batch_id,
                    )
                    order.save()
                    Customer.objects.filter(pk=customer.pk).update(
                        total_debt=models.F('total_debt') + order.remaining_debt
                    )
            except Exception as e:
                errors.append(f"Buyurtmani saqlashda xatolik: {e}")
                continue

        if errors:
            request.session["order_errors"] = errors

        return redirect("dashboard")


class OrderEditView(LoginRequiredMixin, View):
    template_name = "order_edit.html"

    def get_context(self, form, order):
        return {
            "form": form,
            "order": order,
            "customers": Customer.objects.all(),
            "products": Product.objects.all(),
            "page": "dashboard",
        }

    def get(self, request, pk):
        order = get_object_or_404(Order, id=pk)
        form = OrderForm(instance=order)
        return render(request, self.template_name, self.get_context(form, order))

    def post(self, request, pk):
        order = get_object_or_404(Order, id=pk)
        form = OrderForm(request.POST, instance=order)

        if form.is_valid():
            form.save()
            return redirect("dashboard")

        return render(request, self.template_name, self.get_context(form, order))


class OrderDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        from django.db import transaction
        order = get_object_or_404(Order, id=pk)
        with transaction.atomic():
            customer = order.customer
            if customer:
                customer.total_debt -= order.remaining_debt
                customer.save()
            if order.product:
                free_count = order._compute_promo_free(order.product, order.quantity)
                order.product.quantity += order.quantity + free_count
                order.product.save()
            order.delete()
        return redirect("dashboard")

    # GET kept for backwards-compat with the existing edit-page link
    get = post


class CustomerView(AdminOnlyMixin, View):
    template_name = "customer.html"

    def get(self, request):
        customers = CustomerFilter(
            request.GET, Customer.objects.order_by("-total_debt")
        ).qs
        all_customers = Customer.objects.order_by("-total_debt").values(
            "id", "name", "phone", "total_debt"
        )
        total_debt = customers.aggregate(total=models.Sum("total_debt"))["total"] or 0

        context = {
            "customers": customers,
            "all_customers": all_customers,
            "today": date.today().strftime("%Y-%m-%d"),
            "total_debt": total_debt,
            "page": "customer",
        }
        return render(request, self.template_name, context=context)

    def post(self, request):
        if request.POST.get("_method") == "PUT":
            return self.put(request)

        form = CustomerForm(request.POST)
        if form.is_valid():
            form.save()
        return redirect("customer")

    def put(self, request):
        customer_id = request.POST.get("id")
        customer = get_object_or_404(Customer, id=customer_id)
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save(update=True)
        return redirect("customer")


class CustomerDeleteView(AdminOnlyMixin, View):
    def delete(self, request, pk):
        Customer.objects.filter(id=pk).delete()
        return HttpResponse(status=204)


class DebtView(AdminOnlyMixin, View):
    template_name = "debt.html"

    def _available_years(self):
        years = {d.year for d in PaymentHistory.objects.dates("paid_at", "year")}
        years.add(date.today().year)
        return sorted(years)

    def get(self, request):
        selected_year = request.GET.get("year", str(date.today().year))

        try:
            selected_year = int(selected_year)
        except (ValueError, TypeError):
            selected_year = date.today().year

        customers = Customer.objects.order_by("-total_debt")

        date_from = request.GET.get("date_from", date.today().strftime("%Y-%m-%d"))
        date_to = request.GET.get("date_to", date.today().strftime("%Y-%m-%d"))

        query_params = request.GET.copy()
        query_params["date_from"] = date_from
        query_params["date_to"] = date_to

        payments = PaymentFilter(
            query_params,
            PaymentHistory.objects.filter(paid_at__year=selected_year)
            .select_related("customer", "barter_product")
            .order_by("-paid_at"),
        ).qs

        context = {
            "customers": customers,
            "products": Product.objects.all(),
            "payments": payments,
            "total_amount": sum(payment.amount for payment in payments),
            "today": date.today().strftime("%Y-%m-%d"),
            "date_from": date_from,
            "date_to": date_to,
            "payment_type_choices": PaymentHistory.PaymentTypeChoices.choices,
            "selected_year": selected_year,
            "available_years": self._available_years(),
            "page": "debt",
        }
        return render(request, self.template_name, context=context)

    def post(self, request):
        form = PaymentForm(request.POST)
        if form.is_valid():
            form.save()
        return redirect("debts")


class PaymentEditView(AdminOnlyMixin, View):
    template_name = "payment_edit.html"

    def get_context(self, form, payment):
        return {
            "form": form,
            "payment": payment,
            "products": Product.objects.all(),
            "payment_type_choices": PaymentHistory.PaymentTypeChoices.choices,
            "page": "debt",
        }

    def get(self, request, pk):
        payment = get_object_or_404(PaymentHistory, id=pk)
        form = PaymentEditForm(instance=payment)
        return render(request, self.template_name, self.get_context(form, payment))

    def post(self, request, pk):
        payment = get_object_or_404(PaymentHistory, id=pk)
        form = PaymentEditForm(request.POST, instance=payment)

        if form.is_valid():
            form.save()
            return redirect("debts")

        return render(request, self.template_name, self.get_context(form, payment))


class PaymentDeleteView(AdminOnlyMixin, View):
    def post(self, request, pk):
        from django.db import transaction
        payment = get_object_or_404(PaymentHistory, id=pk)
        with transaction.atomic():
            customer = payment.customer
            customer.total_debt += int(payment.amount)
            customer.save()
            if (
                payment.payment_type == PaymentHistory.PaymentTypeChoices.BARTER
                and payment.barter_product
            ):
                payment.barter_product.refresh_from_db()
                payment.barter_product.quantity -= payment.barter_quantity
                payment.barter_product.save()
            payment.delete()
        return redirect("debts")

    # GET kept for backwards-compat with existing links in templates
    get = post


class ProductView(AdminOnlyMixin, View):
    template_name = "product.html"

    def parse_month(self, month_str):
        try:
            year, month_num = month_str.split("-")
            return int(year), int(month_num)
        except ValueError:
            today = date.today()
            return today.year, today.month

    def get_month_annotation(self, year, month):
        return models.Sum(
            models.Case(
                models.When(
                    orders__order_date__year=year,
                    orders__order_date__month=month,
                    then="orders__quantity",
                ),
                default=0,
            )
        )

    def get(self, request):
        current_month = date.today().strftime("%Y-%m")
        selected_month = request.GET.get("month") or current_month

        year, month = self.parse_month(selected_month)

        products = list(
            Product.objects.annotate(
                total_quantity=self.get_month_annotation(year, month)
            )
        )

        month_orders = Order.objects.filter(
            order_date__year=year, order_date__month=month
        ).select_related("product")

        deducted_map = {}
        free_map = {}
        for o in month_orders:
            if not o.product_id:
                continue
            p = o.product
            free = 0
            if p.promo_buy and p.promo_free and p.promo_buy > 0:
                free = (o.quantity // p.promo_buy) * p.promo_free
            pid = o.product_id
            deducted_map[pid] = deducted_map.get(pid, 0) + o.quantity + free
            if free > 0:
                free_map[pid] = free_map.get(pid, 0) + free

        total_deducted = 0
        for product in products:
            product.total_deducted = deducted_map.get(product.id, 0)
            product.total_free = free_map.get(product.id, 0)
            total_deducted += product.total_deducted

        context = {
            "products": products,
            "suppliers": Supplier.objects.all(),
            "total_quantity": total_deducted,
            "page": "product",
            "selected_month": selected_month,
        }
        return render(request, self.template_name, context=context)

    def post(self, request):
        form = ProductForm(request.POST)
        if form.is_valid():
            form.save()
        return redirect("product")


class ProductDeleteView(AdminOnlyMixin, View):
    def post(self, request, pk):
        Product.objects.filter(pk=pk).delete()
        return redirect("product")


class ProductEditView(AdminOnlyMixin, View):
    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            form.save()
        return redirect("product")


class StatisticsView(AdminOnlyMixin, View):
    template_name = "stats.html"

    MONTH_NAMES = [
        "Yanvar",
        "Fevral",
        "Mart",
        "Aprel",
        "May",
        "Iyun",
        "Iyul",
        "Avgust",
        "Sentabr",
        "Oktabr",
        "Noyabr",
        "Dekabr",
    ]

    def _available_years(self):
        years = {d.year for d in Order.objects.dates("order_date", "year")}
        years |= {d.year for d in Purchase.objects.dates("purchase_date", "year")}
        years |= {d.year for d in PaymentHistory.objects.dates("paid_at", "year")}
        years |= {d.year for d in SupplierPayment.objects.dates("paid_at", "year")}
        years.add(date.today().year)
        return sorted(years)

    def _avg_cost_map(self):
        """Average buy-cost per product unit, across all purchases.

        Used as a per-unit COGS estimate so we can compute profit for any
        period (today, week, month, year) without trying to match each sale
        to a specific purchase batch.
        """
        cost_map = {}
        agg = (
            Purchase.objects.filter(product__isnull=False)
            .values("product_id")
            .annotate(
                total_cost=models.Sum("total_cost"),
                total_qty=models.Sum("quantity"),
            )
        )
        for row in agg:
            qty = row["total_qty"] or 0
            cost = row["total_cost"] or 0
            if qty > 0 and cost > 0:
                cost_map[row["product_id"]] = cost / qty
        return cost_map

    def _period_stats(self, date_from, date_to, cost_map):
        """Aggregate revenue / COGS / expenses / profit / orders for a window.

        date_from and date_to are inclusive.
        """
        orders = Order.objects.filter(
            order_date__gte=date_from, order_date__lte=date_to
        ).select_related("product")
        revenue = 0
        cogs = 0
        qty = 0
        count = 0
        for o in orders:
            revenue += o.total_price
            qty += o.quantity
            count += 1
            unit_cost = cost_map.get(o.product_id, 0)
            cogs += int(unit_cost * o.quantity)

        expenses = (
            Expense.objects.filter(
                date__gte=date_from, date__lte=date_to
            ).aggregate(s=models.Sum("amount"))["s"]
            or 0
        )

        return {
            "revenue": revenue,
            "cogs": cogs,
            "expenses": expenses,
            "profit": revenue - cogs - expenses,
            "orders_count": count,
            "quantity": qty,
        }

    def get(self, request):
        import datetime as _dt

        today = date.today()

        selected_year = request.GET.get("year", str(today.year))
        try:
            selected_year = int(selected_year)
        except (ValueError, TypeError):
            selected_year = today.year

        cost_map = self._avg_cost_map()

        # Today, week (Mon..Sun), month, year — all anchored to "today".
        week_start = today - _dt.timedelta(days=today.weekday())
        week_end = week_start + _dt.timedelta(days=6)
        month_start = today.replace(day=1)
        if month_start.month == 12:
            next_month = month_start.replace(year=month_start.year + 1, month=1)
        else:
            next_month = month_start.replace(month=month_start.month + 1)
        month_end = next_month - _dt.timedelta(days=1)
        year_start = today.replace(month=1, day=1)
        year_end = today.replace(month=12, day=31)

        today_stats = self._period_stats(today, today, cost_map)
        week_stats = self._period_stats(week_start, week_end, cost_map)
        month_stats = self._period_stats(month_start, month_end, cost_map)
        year_stats = self._period_stats(year_start, year_end, cost_map)

        # Yesterday (for delta vs today)
        yesterday = today - _dt.timedelta(days=1)
        yesterday_stats = self._period_stats(yesterday, yesterday, cost_map)

        def _pct_delta(curr, prev):
            if not prev:
                return None
            return round((curr - prev) / abs(prev) * 100)

        today_revenue_delta = _pct_delta(
            today_stats["revenue"], yesterday_stats["revenue"]
        )
        today_profit_delta = _pct_delta(
            today_stats["profit"], yesterday_stats["profit"]
        )

        # Last 7 days mini-chart (oldest -> today)
        last_7_days = []
        max_day_profit = 1
        for i in range(6, -1, -1):
            d = today - _dt.timedelta(days=i)
            ds = self._period_stats(d, d, cost_map)
            last_7_days.append(
                {
                    "label": d.strftime("%d.%m"),
                    "weekday": ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"][d.weekday()],
                    "revenue": ds["revenue"],
                    "profit": ds["profit"],
                    "is_today": d == today,
                }
            )
            if ds["profit"] > max_day_profit:
                max_day_profit = ds["profit"]
        for d in last_7_days:
            d["bar_pct"] = (
                round((d["profit"] / max_day_profit) * 100)
                if max_day_profit and d["profit"] > 0
                else 0
            )

        # Selected-year monthly breakdown
        orders_year = Order.objects.filter(
            order_date__year=selected_year
        ).select_related("product")

        monthly_data = []
        max_monthly_profit = 1
        for month_num in range(1, 13):
            m_first = _dt.date(selected_year, month_num, 1)
            if month_num == 12:
                m_next = _dt.date(selected_year + 1, 1, 1)
            else:
                m_next = _dt.date(selected_year, month_num + 1, 1)
            m_last = m_next - _dt.timedelta(days=1)
            ms = self._period_stats(m_first, m_last, cost_map)
            monthly_data.append(
                {
                    "month": self.MONTH_NAMES[month_num - 1],
                    "month_num": month_num,
                    "revenue": ms["revenue"],
                    "profit": ms["profit"],
                    "expenses": ms["expenses"],
                    "count": ms["orders_count"],
                }
            )
            if ms["profit"] > max_monthly_profit:
                max_monthly_profit = ms["profit"]
        for m in monthly_data:
            m["bar_pct"] = (
                round((m["profit"] / max_monthly_profit) * 100)
                if max_monthly_profit and m["profit"] > 0
                else 0
            )

        # Top products this month (more useful than yearly for daily decisions)
        top_products = (
            Product.objects.annotate(
                sold_quantity=models.Sum(
                    "orders__quantity",
                    filter=models.Q(
                        orders__order_date__gte=month_start,
                        orders__order_date__lte=month_end,
                    ),
                ),
                sold_revenue=models.Sum(
                    "orders__total_price",
                    filter=models.Q(
                        orders__order_date__gte=month_start,
                        orders__order_date__lte=month_end,
                    ),
                ),
            )
            .filter(sold_quantity__gt=0)
            .order_by("-sold_revenue")[:5]
        )

        top_debtors = Customer.objects.filter(total_debt__gt=0).order_by(
            "-total_debt"
        )[:5]

        # Customer debt (snapshot, time-independent)
        total_customer_debt = (
            Customer.objects.aggregate(s=models.Sum("total_debt"))["s"] or 0
        )

        # Supplier breakdown for selected year
        supplier_stats = []
        total_supplier_debt = 0

        for supplier in Supplier.objects.all():
            purchases = Purchase.objects.filter(
                supplier=supplier, purchase_date__year=selected_year
            )
            payments = SupplierPayment.objects.filter(
                supplier=supplier, paid_at__year=selected_year
            )

            purchased = sum(p.total_cost for p in purchases)
            paid = sum(p.amount for p in payments)
            all_purchases = sum(p.total_cost for p in supplier.purchases.all())
            all_payments = sum(p.amount for p in supplier.payments.all())
            debt = supplier.initial_debt + all_purchases - all_payments

            supplier_orders = orders_year.filter(product__supplier=supplier)
            sales_revenue = 0
            sales_cogs = 0
            sales_quantity = 0
            for o in supplier_orders:
                sales_revenue += o.total_price
                sales_quantity += o.quantity
                sales_cogs += int(cost_map.get(o.product_id, 0) * o.quantity)
            profit = sales_revenue - sales_cogs

            total_supplier_debt += max(debt, 0)

            monthly = []
            for month_num in range(1, 13):
                mo_orders = supplier_orders.filter(order_date__month=month_num)
                mo_purchases = purchases.filter(purchase_date__month=month_num)
                mo_payments = payments.filter(paid_at__month=month_num)
                m_sales = sum(o.total_price for o in mo_orders)
                m_cogs = sum(
                    int(cost_map.get(o.product_id, 0) * o.quantity)
                    for o in mo_orders
                )
                m_purchased = sum(p.total_cost for p in mo_purchases)
                m_paid = sum(p.amount for p in mo_payments)
                monthly.append(
                    {
                        "month": self.MONTH_NAMES[month_num - 1],
                        "sales": m_sales,
                        "purchased": m_purchased,
                        "paid": m_paid,
                        "profit": m_sales - m_cogs,
                    }
                )

            supplier_stats.append(
                {
                    "supplier": supplier,
                    "purchased": purchased,
                    "paid": paid,
                    "debt": debt,
                    "sales": sales_revenue,
                    "quantity": sales_quantity,
                    "profit": profit,
                    "monthly": monthly,
                }
            )

        # Sort suppliers by profit (most valuable first)
        supplier_stats.sort(key=lambda s: s["profit"], reverse=True)

        context = {
            "today_label": today.strftime("%d.%m.%Y"),
            "today_stats": today_stats,
            "week_stats": week_stats,
            "month_stats": month_stats,
            "year_stats": year_stats,
            "today_revenue_delta": today_revenue_delta,
            "today_profit_delta": today_profit_delta,
            "last_7_days": last_7_days,
            "monthly_data": monthly_data,
            "top_products": top_products,
            "top_debtors": top_debtors,
            "total_customer_debt": total_customer_debt,
            "total_supplier_debt": total_supplier_debt,
            "supplier_stats": supplier_stats,
            "selected_year": selected_year,
            "available_years": self._available_years(),
            "current_month_label": self.MONTH_NAMES[today.month - 1],
            "page": "stats",
        }

        return render(request, self.template_name, context=context)


class SupplierView(AdminOnlyMixin, View):
    template_name = "supplier.html"

    def get(self, request):
        suppliers = Supplier.objects.annotate(product_count=models.Count("products"))
        supplier_debts = {}
        for s in suppliers:
            purchased = sum(p.total_cost for p in s.purchases.all())
            paid = sum(p.amount for p in s.payments.all())
            supplier_debts[s.pk] = s.initial_debt + purchased - paid

        total_products = sum(s.product_count for s in suppliers)
        total_supplier_debt = sum(d for d in supplier_debts.values() if d > 0)
        debtors_count = sum(1 for d in supplier_debts.values() if d > 0)

        return render(
            request,
            self.template_name,
            {
                "suppliers": suppliers,
                "supplier_debts": supplier_debts,
                "total_products": total_products,
                "total_supplier_debt": total_supplier_debt,
                "debtors_count": debtors_count,
                "page": "supplier",
            },
        )

    def post(self, request):
        method = request.POST.get("_method")
        if method == "PUT":
            supplier_id = request.POST.get("id")
            supplier = get_object_or_404(Supplier, pk=supplier_id)
            form = SupplierForm(request.POST, instance=supplier)
        else:
            form = SupplierForm(request.POST)
        if form.is_valid():
            form.save()
        return redirect("supplier")


class SupplierDeleteView(AdminOnlyMixin, View):
    def post(self, request, pk):
        Supplier.objects.filter(pk=pk).delete()
        return redirect("supplier")


class SupplierDetailView(AdminOnlyMixin, View):
    template_name = "supplier_detail.html"

    def get(self, request, pk):
        supplier = get_object_or_404(Supplier, pk=pk)
        purchases = Purchase.objects.filter(supplier=supplier).select_related(
            "product", "barter_product"
        )
        payments = SupplierPayment.objects.filter(supplier=supplier)

        total_purchased = sum(p.total_cost for p in purchases)
        total_paid = sum(p.amount for p in payments)
        debt = supplier.initial_debt + total_purchased - total_paid

        orders = Order.objects.filter(product__supplier=supplier)
        revenue = sum(o.total_price for o in orders)
        cost = sum(o.quantity * (o.product.price if o.product else 0) for o in orders)
        profit = revenue - cost

        products = Product.objects.filter(supplier=supplier)
        all_products = Product.objects.all()

        total_owed = supplier.initial_debt + total_purchased

        return render(
            request,
            self.template_name,
            {
                "supplier": supplier,
                "purchases": purchases,
                "payments": payments,
                "total_purchased": total_purchased,
                "total_paid": total_paid,
                "total_owed": total_owed,
                "debt": debt,
                "revenue": revenue,
                "profit": profit,
                "products": products,
                "all_products": all_products,
                "page": "supplier",
            },
        )

    def post(self, request, pk):
        from django.db import transaction

        supplier = get_object_or_404(Supplier, pk=pk)
        action = request.POST.get("action")

        if action == "purchase":
            purchase_type = request.POST.get("purchase_type", "cash")
            barter_product_id = request.POST.get("barter_product")
            barter_quantity = request.POST.get("barter_quantity", 0)

            usd_amount = _to_decimal(request.POST.get("usd_price_per_unit"))
            exchange_rate = _to_decimal(request.POST.get("exchange_rate"))
            sum_price = request.POST.get("price_per_unit")

            if purchase_type == "barter":
                if not barter_product_id or not barter_quantity:
                    return redirect("supplier_detail", pk=pk)
            else:
                has_usd = usd_amount and exchange_rate
                if not sum_price and not has_usd:
                    return redirect("supplier_detail", pk=pk)

            try:
                product_id = request.POST.get("product") or None
                quantity = int(request.POST.get("quantity", 0))
            except (ValueError, TypeError):
                return redirect("supplier_detail", pk=pk)
            if quantity <= 0:
                return redirect("supplier_detail", pk=pk)

            purchase = Purchase(
                supplier=supplier,
                product_id=product_id,
                quantity=quantity,
                purchase_type=purchase_type,
                note=request.POST.get("note", ""),
            )

            if purchase_type == "barter":
                purchase.price_per_unit = None
                purchase.barter_product_id = barter_product_id
                try:
                    purchase.barter_quantity = int(barter_quantity)
                except (ValueError, TypeError):
                    purchase.barter_quantity = 0
                if purchase.barter_quantity <= 0:
                    return redirect("supplier_detail", pk=pk)
                # Verify we actually have enough of the bartered product to give away
                bp = Product.objects.filter(pk=purchase.barter_product_id).first()
                if not bp or bp.quantity < purchase.barter_quantity:
                    return redirect("supplier_detail", pk=pk)
            else:
                if usd_amount and exchange_rate:
                    purchase.usd_price_per_unit = usd_amount
                    purchase.exchange_rate = exchange_rate
                    purchase.price_per_unit = int(usd_amount * exchange_rate)
                else:
                    try:
                        purchase.price_per_unit = int(sum_price)
                    except (ValueError, TypeError):
                        purchase.price_per_unit = 0

            with transaction.atomic():
                purchase.save()

        elif action == "payment":
            payment_type = request.POST.get("payment_type") or None

            if payment_type == SupplierPayment.PaymentTypeChoices.BARTER:
                # Barter: we give supplier product P; debt reduced by P.price * qty
                barter_product_id = request.POST.get("barter_product")
                try:
                    barter_quantity = int(request.POST.get("barter_quantity", 0))
                except (ValueError, TypeError):
                    return redirect("supplier_detail", pk=pk)
                if not barter_product_id or barter_quantity <= 0:
                    return redirect("supplier_detail", pk=pk)
                with transaction.atomic():
                    try:
                        barter_product = Product.objects.select_for_update().get(pk=barter_product_id)
                    except Product.DoesNotExist:
                        return redirect("supplier_detail", pk=pk)
                    if barter_product.quantity < barter_quantity:
                        return redirect("supplier_detail", pk=pk)
                    payment = SupplierPayment(
                        supplier=supplier,
                        amount=(barter_product.price or 0) * barter_quantity,
                        payment_type=payment_type,
                        barter_product=barter_product,
                        barter_quantity=barter_quantity,
                        comment=request.POST.get("comment", ""),
                    )
                    payment.save()
            else:
                usd_amount = _to_decimal(request.POST.get("usd_amount"))
                exchange_rate = _to_decimal(request.POST.get("exchange_rate"))
                sum_amount = request.POST.get("amount")
                if usd_amount and exchange_rate:
                    final_amount = int(usd_amount * exchange_rate)
                else:
                    try:
                        final_amount = int(sum_amount)
                    except (ValueError, TypeError):
                        return redirect("supplier_detail", pk=pk)
                if final_amount <= 0:
                    return redirect("supplier_detail", pk=pk)
                payment = SupplierPayment(
                    supplier=supplier,
                    amount=final_amount,
                    payment_type=payment_type,
                    comment=request.POST.get("comment", ""),
                )
                if usd_amount and exchange_rate:
                    payment.usd_amount = usd_amount
                    payment.exchange_rate = exchange_rate
                payment.save()

        return redirect("supplier_detail", pk=pk)


class PurchaseDeleteView(AdminOnlyMixin, View):
    def post(self, request, pk):
        from django.contrib import messages
        from django.db import transaction

        purchase = get_object_or_404(Purchase, pk=pk)
        supplier_pk = purchase.supplier.pk

        # Don't delete if removing the received stock would go negative
        # (the goods have already been sold to customers).
        if purchase.product:
            current = Product.objects.filter(pk=purchase.product.pk).values_list("quantity", flat=True).first() or 0
            if current < purchase.quantity:
                messages.error(
                    request,
                    f"Xaridni o'chirib bo'lmaydi: '{purchase.product.name}' "
                    f"hozir omborda {current} ta, lekin xarid {purchase.quantity} ta edi "
                    f"(qisman sotilgan). Avval mahsulotni qo'lda to'g'rilang."
                )
                return redirect("supplier_detail", pk=supplier_pk)

        with transaction.atomic():
            if purchase.product:
                Product.objects.filter(pk=purchase.product.pk).update(
                    quantity=models.F("quantity") - purchase.quantity
                )
            if (
                purchase.purchase_type == Purchase.PurchaseTypeChoices.BARTER
                and purchase.barter_product
            ):
                Product.objects.filter(pk=purchase.barter_product.pk).update(
                    quantity=models.F("quantity") + purchase.barter_quantity
                )
            purchase.delete()
        return redirect("supplier_detail", pk=supplier_pk)


class SupplierPaymentDeleteView(AdminOnlyMixin, View):
    def post(self, request, pk):
        payment = get_object_or_404(SupplierPayment, pk=pk)
        supplier_pk = payment.supplier.pk
        if (
            payment.payment_type == SupplierPayment.PaymentTypeChoices.BARTER
            and payment.barter_product
        ):
            payment.barter_product.quantity += payment.barter_quantity
            payment.barter_product.save()
        payment.delete()
        return redirect("supplier_detail", pk=supplier_pk)


class ProfileView(AdminOnlyMixin, View):
    def get(self, request):
        return redirect("operator")

    def post(self, request):
        return redirect("operator")


class OperatorView(AdminOnlyMixin, View):
    template_name = "operator.html"

    def _all_users(self):
        return User.objects.select_related("profile").order_by(
            "-is_superuser", "username"
        )

    def get(self, request):
        return render(
            request,
            self.template_name,
            {"users": self._all_users(), "page": "operator"},
        )

    def post(self, request):
        action = request.POST.get("action")
        error = None
        success = None

        if action == "add_user":
            username = request.POST.get("username", "").strip()
            password = request.POST.get("password", "").strip()
            role = request.POST.get("role", UserProfile.ROLE_OPERATOR)
            if not username or not password:
                error = "Username va parol to'ldirilishi shart."
            elif User.objects.filter(username=username).exists():
                error = f"'{username}' allaqachon band."
            else:
                new_user = User.objects.create_user(
                    username=username, password=password
                )
                UserProfile.objects.filter(user=new_user).update(role=role)
                success = "added"

        elif action == "edit_user":
            user_id = request.POST.get("user_id")
            target = get_object_or_404(User, pk=user_id)
            new_username = request.POST.get("new_username", "").strip()
            new_password = request.POST.get("new_password", "").strip()
            new_role = request.POST.get("new_role", "")

            if new_username and new_username != target.username:
                if (
                    User.objects.filter(username=new_username)
                    .exclude(pk=target.pk)
                    .exists()
                ):
                    error = f"'{new_username}' allaqachon band."
                else:
                    target.username = new_username
                    target.save()

            if not error and new_password:
                if len(new_password) < 4:
                    error = "Parol kamida 4 ta belgidan iborat bo'lishi kerak."
                else:
                    target.set_password(new_password)
                    target.save()
                    if target == request.user:
                        from django.contrib.auth import update_session_auth_hash

                        update_session_auth_hash(request, target)

            if not error and new_role in (
                UserProfile.ROLE_ADMIN,
                UserProfile.ROLE_OPERATOR,
            ):
                UserProfile.objects.filter(user=target).update(role=new_role)

            if not error:
                success = "updated"

        return render(
            request,
            self.template_name,
            {
                "users": self._all_users(),
                "page": "operator",
                "error": error,
                "success": success,
            },
        )


class OperatorDeleteView(AdminOnlyMixin, View):
    def post(self, request, pk):
        User.objects.filter(pk=pk, profile__role=UserProfile.ROLE_OPERATOR).delete()
        return redirect("operator")


class ExpenseView(AdminOnlyMixin, View):
    template_name = "expense.html"

    def get(self, request):
        expenses = Expense.objects.all()
        total = sum(e.amount for e in expenses)
        return render(
            request,
            self.template_name,
            {
                "expenses": expenses,
                "total": total,
                "page": "expense",
            },
        )

    def post(self, request):
        form = ExpenseForm(request.POST)
        if form.is_valid():
            form.save()
        return redirect("expense")


class ExpenseDeleteView(AdminOnlyMixin, View):
    def post(self, request, pk):
        Expense.objects.filter(pk=pk).delete()
        return redirect("expense")
