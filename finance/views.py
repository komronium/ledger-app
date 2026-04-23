import json
from datetime import date

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
    ProductForm,
    SupplierForm,
    ExpenseForm,
    PurchaseForm,
    SupplierPaymentForm,
    CustomerForm,
    OrderForm,
    PaymentEditForm,
    PaymentForm,
)
from finance.models import Product, Customer, Order, PaymentHistory, Supplier, Expense, Purchase, SupplierPayment, UserProfile


def _is_admin(user):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    try:
        return user.profile.role == UserProfile.ROLE_ADMIN
    except Exception:
        return True


class AdminOnlyMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not _is_admin(request.user):
            return redirect('dashboard')
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
        """Get payment data for a specific customer with optional date filtering"""
        payments = PaymentHistory.objects.filter(customer_id=customer_id)

        # Apply date filtering if provided
        if date_from:
            payments = payments.filter(paid_at__date__gte=date_from)
        if date_to:
            payments = payments.filter(paid_at__date__lte=date_to)

        return payments.order_by("-paid_at")

    def _prepare_combined_data(self, orders, payments, customer):
        """Combine order and payment data into a single list"""
        combined_data = []

        # Add orders
        for order in orders:
            combined_data.append(
                {
                    "type": "order",
                    "id": order.id,
                    "customer": order.customer if order.customer else "",
                    "product": order.product if order.product else "",
                    "quantity": order.quantity,
                    "price_per_kg": order.price_per_kg,
                    "order_date": order.order_date,
                    "total_price": order.total_price,
                    "remaining_debt": order.remaining_debt,
                }
            )

        # Add payments
        for payment in payments:
            combined_data.append(
                {
                    "type": "payment",
                    "id": payment.id,
                    "customer": payment.customer,
                    "product": "",
                    "quantity": 0,
                    "price_per_kg": 0,
                    "paid_amount": payment.amount,
                    "order_date": payment.paid_at.date(),
                    "total_price": 0,
                    "remaining_debt": -payment.amount,
                    "payment_type": payment.payment_type,
                    "comment": payment.comment,
                }
            )

        combined_data.sort(key=lambda x: x["order_date"])
        return combined_data

    def _calculate_cumulative_debt(self, combined_data, customer):
        """Calculate cumulative debt for each transaction"""
        # Start with the customer's existing total debt
        cumulative_debt = customer.total_debt

        # Calculate total debt from current filtered transactions first
        total_filtered_debt = sum(
            item["remaining_debt"] for item in combined_data if item["type"] == "order"
        ) - sum(
            item["paid_amount"] for item in combined_data if item["type"] == "payment"
        )

        # Adjust cumulative debt to start from before these transactions
        cumulative_debt = cumulative_debt - total_filtered_debt

        for item in combined_data:
            if item["type"] == "order":
                cumulative_debt += item["remaining_debt"]
            elif item["type"] == "payment":
                cumulative_debt -= item["paid_amount"]

            # Update remaining_debt to show cumulative value
            item["remaining_debt"] = cumulative_debt

        return combined_data

    def get(self, request):
        query_params = request.GET.copy()
        if not query_params.get("customer_id"):
            query_params["date_from"] = query_params.get("date_from") or date.today()
            query_params["date_to"] = query_params.get("date_to") or date.today()

        # Get filtered orders
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

            # Combine orders and payments
            combined_data = self._prepare_combined_data(
                filtered_orders, payments, customer
            )

            # Calculate cumulative debt for each transaction
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
            # Calculate order totals only
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

            # Prepare order data
            order_data = [
                {
                    "type": "order",
                    "id": order.id,
                    "customer": order.customer,
                    "product": order.product,
                    "quantity": order.quantity,
                    "price_per_kg": order.price_per_kg,
                    "order_date": order.order_date,
                    "total_price": order.total_price,
                    "remaining_debt": order.remaining_debt,
                }
                for order in filtered_orders
            ]

            total_quantity = totals["total_quantity"]
            total_price = totals["total_price"]
            total_paid_amount = 0
            total_debt = totals["total_debt"]

        products_list = list(Product.objects.values('id', 'name', 'price', 'quantity'))
        import json as _json
        products_json = _json.dumps(products_list)

        # Get any error messages from session
        errors = request.session.pop('order_errors', None)

        context = {
            "orders": order_data,
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
        orders_json = request.POST.get('orders_json', '[]')
        try:
            orders_data = json.loads(orders_json)
        except json.JSONDecodeError:
            orders_data = []

        errors = []
        for item in orders_data:
            try:
                customer = Customer.objects.get(id=item.get('customer_id'))
                product = Product.objects.get(id=item.get('product_id'))
                requested_quantity = int(item.get('quantity', 0))

                # Check if enough quantity is available
                if product.quantity < requested_quantity:
                    errors.append(f"{product.name}: {requested_quantity} kg so'raldi, lekin {product.quantity} kg mavjud.")
                    continue

                order = Order(
                    customer=customer,
                    product=product,
                    quantity=requested_quantity,
                    price_per_kg=int(item.get('price_per_kg', 0)),
                )
                order.save()
                customer.total_debt += order.remaining_debt
                customer.save()
            except (Customer.DoesNotExist, Product.DoesNotExist, ValueError, TypeError):
                continue

        if errors:
            # Store error messages in session to display after redirect
            request.session['order_errors'] = errors

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
    def get(self, request, pk):
        order = get_object_or_404(Order, id=pk)
        customer = order.customer
        customer.total_debt -= order.remaining_debt
        customer.save()
        order.delete()
        return redirect("dashboard")


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

    def get(self, request):
        # Get year from query parameter, default to current year
        selected_year = request.GET.get("year", str(date.today().year))

        try:
            selected_year = int(selected_year)
        except (ValueError, TypeError):
            selected_year = date.today().year

        customers = Customer.objects.order_by("-total_debt")

        # Get date filters, default to today
        date_from = request.GET.get("date_from", date.today().strftime("%Y-%m-%d"))
        date_to = request.GET.get("date_to", date.today().strftime("%Y-%m-%d"))

        query_params = request.GET.copy()
        query_params["date_from"] = date_from
        query_params["date_to"] = date_to

        # Filter payments by year
        payments = PaymentFilter(
            query_params,
            PaymentHistory.objects.filter(paid_at__year=selected_year).order_by(
                "-paid_at"
            ),
        ).qs

        context = {
            "customers": customers,
            "payments": payments,
            "total_amount": sum(payment.amount for payment in payments),
            "today": date.today().strftime("%Y-%m-%d"),
            "date_from": date_from,
            "date_to": date_to,
            "payment_type_choices": PaymentHistory.PaymentTypeChoices.choices,
            "selected_year": selected_year,
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
    def get(self, request, pk):
        payment = get_object_or_404(PaymentHistory, id=pk)
        customer = payment.customer
        customer.total_debt += payment.amount
        customer.save()
        payment.delete()
        return redirect("debts")


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

        products = Product.objects.annotate(
            total_quantity=self.get_month_annotation(year, month)
        )

        context = {
            "products": products,
            "suppliers": Supplier.objects.all(),
            "total_quantity": sum(
                product.total_quantity or 0 for product in products
            ),
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
        "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
        "Iyul", "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr",
    ]

    def get(self, request):
        selected_year = request.GET.get("year", "2026")

        try:
            selected_year = int(selected_year)
        except (ValueError, TypeError):
            selected_year = 2026

        orders = Order.objects.filter(order_date__year=selected_year)
        customers = Customer.objects.all()

        total_revenue = sum(order.total_price for order in orders)
        total_debt = sum(customer.total_debt for customer in customers)
        total_quantity = sum(order.quantity for order in orders)
        total_orders = orders.count()

        # Monthly breakdown
        monthly_data = []
        max_monthly_revenue = 1  # avoid division by zero
        for month_num in range(1, 13):
            month_orders = orders.filter(order_date__month=month_num)
            revenue = sum(o.total_price for o in month_orders)
            qty = sum(o.quantity for o in month_orders)
            count = month_orders.count()
            if revenue > max_monthly_revenue:
                max_monthly_revenue = revenue
            monthly_data.append({
                "month": self.MONTH_NAMES[month_num - 1],
                "month_num": month_num,
                "revenue": revenue,
                "quantity": qty,
                "count": count,
            })

        # Calculate percentage for bar chart
        for m in monthly_data:
            m["bar_pct"] = round((m["revenue"] / max_monthly_revenue) * 100) if max_monthly_revenue else 0

        # Top products
        top_products = Product.objects.annotate(
            sold_quantity=models.Sum(
                "orders__quantity",
                filter=models.Q(orders__order_date__year=selected_year),
            ),
            sold_revenue=models.Sum(
                "orders__total_price",
                filter=models.Q(orders__order_date__year=selected_year),
            ),
        ).order_by("-sold_quantity")

        # Top customers by debt
        top_debtors = Customer.objects.filter(total_debt__gt=0).order_by("-total_debt")[:5]

        # Per-supplier stats: purchases, payments, debt, sales, profit
        supplier_stats = []
        total_supplier_debt = 0
        total_purchased_all = 0

        for supplier in Supplier.objects.all():
            purchases = Purchase.objects.filter(supplier=supplier, purchase_date__year=selected_year)
            payments = SupplierPayment.objects.filter(supplier=supplier, paid_at__year=selected_year)

            purchased = sum(p.total_cost for p in purchases)
            paid = sum(p.amount for p in payments)
            # All-time debt (not year-filtered)
            all_purchases = sum(p.total_cost for p in supplier.purchases.all())
            all_payments = sum(p.amount for p in supplier.payments.all())
            debt = all_purchases - all_payments

            supplier_orders = orders.filter(product__supplier=supplier)
            sales_revenue = sum(o.total_price for o in supplier_orders)
            sales_quantity = sum(o.quantity for o in supplier_orders)
            profit = sales_revenue - purchased

            total_supplier_debt += max(debt, 0)
            total_purchased_all += purchased

            monthly = []
            for month_num in range(1, 13):
                mo_orders = supplier_orders.filter(order_date__month=month_num)
                mo_purchases = purchases.filter(purchase_date__month=month_num)
                mo_payments = payments.filter(paid_at__month=month_num)
                m_sales = sum(o.total_price for o in mo_orders)
                m_purchased = sum(p.total_cost for p in mo_purchases)
                m_paid = sum(p.amount for p in mo_payments)
                monthly.append({
                    "month": self.MONTH_NAMES[month_num - 1],
                    "sales": m_sales,
                    "purchased": m_purchased,
                    "paid": m_paid,
                    "profit": m_sales - m_purchased,
                })

            supplier_stats.append({
                "supplier": supplier,
                "purchased": purchased,
                "paid": paid,
                "debt": debt,
                "sales": sales_revenue,
                "quantity": sales_quantity,
                "profit": profit,
                "monthly": monthly,
            })

        total_expenses = sum(
            e.amount for e in Expense.objects.filter(date__year=selected_year)
        )

        context = {
            "total_orders": total_orders,
            "total_revenue": total_revenue,
            "total_debt": total_debt,
            "total_quantity": total_quantity,
            "total_purchased": total_purchased_all,
            "total_supplier_debt": total_supplier_debt,
            "supplier_stats": supplier_stats,
            "total_expenses": total_expenses,
            "net_profit": total_revenue - total_purchased_all - total_expenses,
            "selected_year": selected_year,
            "page": "stats",
        }

        return render(request, self.template_name, context=context)


class SupplierView(AdminOnlyMixin, View):
    template_name = "supplier.html"

    def get(self, request):
        suppliers = Supplier.objects.annotate(
            product_count=models.Count('products')
        )
        supplier_debts = {}
        for s in suppliers:
            purchased = sum(p.total_cost for p in s.purchases.all())
            paid = sum(p.amount for p in s.payments.all())
            supplier_debts[s.pk] = purchased - paid
        return render(request, self.template_name, {
            "suppliers": suppliers,
            "supplier_debts": supplier_debts,
            "page": "supplier",
        })

    def post(self, request):
        method = request.POST.get('_method')
        if method == 'PUT':
            supplier_id = request.POST.get('id')
            supplier = get_object_or_404(Supplier, pk=supplier_id)
            form = SupplierForm(request.POST, instance=supplier)
        else:
            form = SupplierForm(request.POST)
        if form.is_valid():
            form.save()
        return redirect('supplier')


class SupplierDeleteView(AdminOnlyMixin, View):
    def post(self, request, pk):
        Supplier.objects.filter(pk=pk).delete()
        return redirect('supplier')


class SupplierDetailView(AdminOnlyMixin, View):
    template_name = 'supplier_detail.html'

    def get(self, request, pk):
        supplier = get_object_or_404(Supplier, pk=pk)
        purchases = Purchase.objects.filter(supplier=supplier)
        payments = SupplierPayment.objects.filter(supplier=supplier)

        total_purchased = sum(p.total_cost for p in purchases)
        total_paid = sum(p.amount for p in payments)
        debt = total_purchased - total_paid

        orders = Order.objects.filter(product__supplier=supplier)
        revenue = sum(o.total_price for o in orders)
        cost = sum(o.quantity * (o.product.price if o.product else 0) for o in orders)
        profit = revenue - cost

        products = Product.objects.filter(supplier=supplier)

        return render(request, self.template_name, {
            'supplier': supplier,
            'purchases': purchases,
            'payments': payments,
            'total_purchased': total_purchased,
            'total_paid': total_paid,
            'debt': debt,
            'revenue': revenue,
            'profit': profit,
            'products': products,
            'page': 'supplier',
        })

    def post(self, request, pk):
        supplier = get_object_or_404(Supplier, pk=pk)
        action = request.POST.get('action')
        if action == 'purchase':
            form = PurchaseForm(request.POST)
            if form.is_valid():
                purchase = form.save(commit=False)
                purchase.supplier = supplier
                purchase.save()
        elif action == 'payment':
            form = SupplierPaymentForm(request.POST)
            if form.is_valid():
                payment = form.save(commit=False)
                payment.supplier = supplier
                payment.save()
        return redirect('supplier_detail', pk=pk)


class PurchaseDeleteView(AdminOnlyMixin, View):
    def post(self, request, pk):
        purchase = get_object_or_404(Purchase, pk=pk)
        supplier_pk = purchase.supplier.pk
        purchase.delete()
        return redirect('supplier_detail', pk=supplier_pk)


class SupplierPaymentDeleteView(AdminOnlyMixin, View):
    def post(self, request, pk):
        payment = get_object_or_404(SupplierPayment, pk=pk)
        supplier_pk = payment.supplier.pk
        payment.delete()
        return redirect('supplier_detail', pk=supplier_pk)


class ProfileView(AdminOnlyMixin, View):
    def get(self, request):
        return redirect('operator')

    def post(self, request):
        return redirect('operator')


class OperatorView(AdminOnlyMixin, View):
    template_name = 'operator.html'

    def _all_users(self):
        return User.objects.select_related('profile').order_by('-is_superuser', 'username')

    def get(self, request):
        return render(request, self.template_name, {'users': self._all_users(), 'page': 'operator'})

    def post(self, request):
        action = request.POST.get('action')
        error = None
        success = None

        if action == 'add_user':
            username = request.POST.get('username', '').strip()
            password = request.POST.get('password', '').strip()
            role = request.POST.get('role', UserProfile.ROLE_OPERATOR)
            if not username or not password:
                error = "Username va parol to'ldirilishi shart."
            elif User.objects.filter(username=username).exists():
                error = f"'{username}' allaqachon band."
            else:
                new_user = User.objects.create_user(username=username, password=password)
                UserProfile.objects.filter(user=new_user).update(role=role)
                success = "added"

        elif action == 'edit_user':
            user_id = request.POST.get('user_id')
            target = get_object_or_404(User, pk=user_id)
            new_username = request.POST.get('new_username', '').strip()
            new_password = request.POST.get('new_password', '').strip()
            new_role = request.POST.get('new_role', '')

            if new_username and new_username != target.username:
                if User.objects.filter(username=new_username).exclude(pk=target.pk).exists():
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

            if not error and new_role in (UserProfile.ROLE_ADMIN, UserProfile.ROLE_OPERATOR):
                UserProfile.objects.filter(user=target).update(role=new_role)

            if not error:
                success = "updated"

        return render(request, self.template_name, {
            'users': self._all_users(),
            'page': 'operator',
            'error': error,
            'success': success,
        })


class OperatorDeleteView(AdminOnlyMixin, View):
    def post(self, request, pk):
        User.objects.filter(pk=pk, profile__role=UserProfile.ROLE_OPERATOR).delete()
        return redirect('operator')


class ExpenseView(AdminOnlyMixin, View):
    template_name = 'expense.html'

    def get(self, request):
        expenses = Expense.objects.all()
        total = sum(e.amount for e in expenses)
        return render(request, self.template_name, {
            'expenses': expenses,
            'total': total,
            'page': 'expense',
        })

    def post(self, request):
        form = ExpenseForm(request.POST)
        if form.is_valid():
            form.save()
        return redirect('expense')


class ExpenseDeleteView(AdminOnlyMixin, View):
    def post(self, request, pk):
        Expense.objects.filter(pk=pk).delete()
        return redirect('expense')
