from decimal import Decimal, InvalidOperation

from django import forms
from finance.models import Customer, Product, Order, PaymentHistory, Supplier, Expense, Purchase, SupplierPayment


def _to_int(value, default=0):
    """Parse a user-entered numeric string (with spaces, commas, dots)."""
    if value is None:
        return default
    if isinstance(value, (int, float, Decimal)):
        try:
            return int(value)
        except (ValueError, TypeError):
            return default
    cleaned = str(value).replace(',', '').replace(' ', '').replace('.', '').strip()
    if not cleaned:
        return default
    try:
        return int(cleaned)
    except ValueError:
        return default


def _to_decimal(value):
    """Parse a user-entered USD string into a Decimal, or None."""
    if value in (None, ''):
        return None
    cleaned = str(value).replace(',', '.').replace(' ', '').strip()
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


class OrderForm(forms.ModelForm):
    customer_id = forms.IntegerField()
    product_id = forms.IntegerField()

    class Meta:
        model = Order
        fields = ['customer_id', 'product_id', 'quantity', 'price_per_kg']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['customer_id'].initial = self.instance.customer.id if self.instance.customer else None
            self.fields['product_id'].initial = self.instance.product.id if self.instance.product else None

    def clean(self):
        cleaned_data = super().clean()
        customer_id = cleaned_data.get('customer_id')
        product_id = cleaned_data.get('product_id')

        if customer_id:
            try:
                Customer.objects.get(id=customer_id)
            except Customer.DoesNotExist:
                raise forms.ValidationError("Tanlangan mijoz mavjud emas.")

        if product_id:
            try:
                Product.objects.get(id=product_id)
            except Product.DoesNotExist:
                raise forms.ValidationError("Tanlangan mahsulot mavjud emas.")

        return cleaned_data

    def save(self, commit=True):
        order = super().save(commit=False)
        new_customer = Customer.objects.get(id=self.cleaned_data['customer_id'])
        new_product = Product.objects.get(id=self.cleaned_data['product_id'])
        order.customer = new_customer
        order.product = new_product

        if not commit:
            return order

        if self.instance.pk:
            old_order = Order.objects.select_related('customer', 'product').get(pk=self.instance.pk)
            old_customer = old_order.customer
            old_product = old_order.product
            old_quantity = old_order.quantity
            old_remaining_debt = old_order.remaining_debt

            if old_product:
                old_free = order._compute_promo_free(old_product, old_quantity)
                old_product.quantity += (old_quantity + old_free)
                old_product.save()

            new_free = order._compute_promo_free(new_product, order.quantity)
            new_product.refresh_from_db()
            new_product.quantity -= (order.quantity + new_free)
            new_product.save()

            order.total_price = order.quantity * order.price_per_kg
            order.remaining_debt = order.total_price
            super(Order, order).save()

            new_remaining_debt = order.remaining_debt
            if old_customer and old_customer.pk != new_customer.pk:
                old_customer.total_debt -= old_remaining_debt
                old_customer.save()
                new_customer.total_debt += new_remaining_debt
                new_customer.save()
            else:
                debt_difference = new_remaining_debt - old_remaining_debt
                new_customer.total_debt += debt_difference
                new_customer.save()
        else:
            order.save()
            new_customer.total_debt += order.remaining_debt
            new_customer.save()

        return order


class CustomerForm(forms.ModelForm):
    debt = forms.CharField(required=False, initial='0')

    class Meta:
        model = Customer
        fields = ['name', 'phone', 'address', 'debt']

    def save(self, commit=True, update=False):
        customer = super().save(commit=False)
        new_default_debt = _to_int(self.cleaned_data.get('debt'), 0)

        if commit:
            if update:
                old_default_debt = customer.default_debt or 0
                diff = new_default_debt - old_default_debt
                customer.default_debt = new_default_debt
                customer.total_debt = (customer.total_debt or 0) + diff
            else:
                customer.default_debt = new_default_debt
                customer.total_debt = new_default_debt
            customer.save()
        return customer


class PaymentForm(forms.ModelForm):
    customer_id = forms.IntegerField()
    payment_amount = forms.CharField(required=False)
    usd_amount = forms.CharField(required=False)
    exchange_rate = forms.CharField(required=False)
    barter_product_id = forms.IntegerField(required=False)
    barter_quantity = forms.IntegerField(required=False)
    comment = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Izoh qoldiring...'}))

    class Meta:
        model = PaymentHistory
        fields = ['customer_id', 'payment_amount', 'payment_type', 'comment']

    def save(self, commit=True):
        payment = super().save(commit=False)
        customer = Customer.objects.get(id=self.cleaned_data['customer_id'])
        payment.customer = customer

        payment_type = self.cleaned_data.get('payment_type')

        if payment_type == PaymentHistory.PaymentTypeChoices.BARTER:
            barter_product_id = self.cleaned_data.get('barter_product_id')
            barter_quantity = self.cleaned_data.get('barter_quantity') or 0
            barter_product = Product.objects.get(id=barter_product_id)
            unit_price = barter_product.price or 0
            payment.barter_product = barter_product
            payment.barter_quantity = barter_quantity
            payment.amount = unit_price * barter_quantity
            payment.usd_amount = None
            payment.exchange_rate = None
        else:
            usd_amount = _to_decimal(self.cleaned_data.get('usd_amount'))
            exchange_rate = _to_decimal(self.cleaned_data.get('exchange_rate'))
            if usd_amount and exchange_rate:
                payment.usd_amount = usd_amount
                payment.exchange_rate = exchange_rate
                payment.amount = int(usd_amount * exchange_rate)
            else:
                payment.amount = _to_int(self.cleaned_data.get('payment_amount'))
                payment.usd_amount = None
                payment.exchange_rate = None

        if commit:
            payment.save()
            if payment_type == PaymentHistory.PaymentTypeChoices.BARTER and payment.barter_product:
                payment.barter_product.quantity += payment.barter_quantity
                payment.barter_product.save()
            customer.total_debt -= int(payment.amount)
            customer.save()

        return payment


class PaymentEditForm(forms.ModelForm):
    payment_amount = forms.CharField(required=False)
    usd_amount = forms.CharField(required=False)
    exchange_rate = forms.CharField(required=False)
    barter_quantity = forms.IntegerField(required=False)
    barter_product_id = forms.IntegerField(required=False)
    comment = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Izoh qoldiring...'}))

    class Meta:
        model = PaymentHistory
        fields = ['payment_amount', 'payment_type', 'comment']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['payment_amount'].initial = str(self.instance.amount)
            if self.instance.usd_amount is not None:
                self.fields['usd_amount'].initial = str(self.instance.usd_amount)
            if self.instance.exchange_rate is not None:
                self.fields['exchange_rate'].initial = str(self.instance.exchange_rate)

    def save(self, commit=True):
        payment = super().save(commit=False)
        old_amount = int(self.instance.amount) if self.instance.amount else 0
        old_barter_product = self.instance.barter_product
        old_barter_quantity = self.instance.barter_quantity or 0

        payment_type = self.cleaned_data.get('payment_type') or self.instance.payment_type

        if payment_type == PaymentHistory.PaymentTypeChoices.BARTER:
            barter_product_id = self.cleaned_data.get('barter_product_id') or (old_barter_product.pk if old_barter_product else None)
            new_barter_quantity = self.cleaned_data.get('barter_quantity') or old_barter_quantity
            barter_product = Product.objects.get(id=barter_product_id) if barter_product_id else old_barter_product
            unit_price = barter_product.price if barter_product else 0
            payment.barter_product = barter_product
            payment.barter_quantity = new_barter_quantity
            payment.amount = unit_price * new_barter_quantity
            payment.usd_amount = None
            payment.exchange_rate = None
        else:
            usd_amount = _to_decimal(self.cleaned_data.get('usd_amount'))
            exchange_rate = _to_decimal(self.cleaned_data.get('exchange_rate'))
            if usd_amount and exchange_rate:
                payment.usd_amount = usd_amount
                payment.exchange_rate = exchange_rate
                payment.amount = int(usd_amount * exchange_rate)
            else:
                payment.amount = _to_int(self.cleaned_data.get('payment_amount'))
                payment.usd_amount = None
                payment.exchange_rate = None
            payment.barter_product = None
            payment.barter_quantity = 0

        if commit:
            new_amount = int(payment.amount)
            amount_difference = new_amount - old_amount
            customer = payment.customer
            customer.total_debt -= amount_difference
            customer.save()

            if old_barter_product and (
                payment.barter_product_id != old_barter_product.pk
                or payment.barter_quantity != old_barter_quantity
            ):
                old_barter_product.quantity -= old_barter_quantity
                old_barter_product.save()
                if payment.barter_product:
                    payment.barter_product.refresh_from_db()
                    payment.barter_product.quantity += payment.barter_quantity
                    payment.barter_product.save()
            elif not old_barter_product and payment.barter_product:
                payment.barter_product.quantity += payment.barter_quantity
                payment.barter_product.save()

            payment.save()

        return payment


class ProductForm(forms.ModelForm):

    class Meta:
        model = Product
        fields = ['name', 'price', 'quantity', 'supplier', 'promo_buy', 'promo_free']

    def clean(self):
        cleaned_data = super().clean()
        promo_buy = cleaned_data.get('promo_buy')
        promo_free = cleaned_data.get('promo_free')
        if (promo_buy is None) != (promo_free is None):
            raise forms.ValidationError("Aksiya: ikkala maydonni ham to'ldiring yoki ikkalasini ham bo'sh qoldiring.")
        if promo_buy is not None and promo_buy <= 0:
            raise forms.ValidationError("Aksiya: sotib olinadigan miqdor 0 dan katta bo'lishi kerak.")
        if promo_free is not None and promo_free <= 0:
            raise forms.ValidationError("Aksiya: bepul miqdor 0 dan katta bo'lishi kerak.")
        return cleaned_data

    def save(self, commit=True):
        product = super().save(commit=False)
        if commit:
            product.save()
        return product


class SupplierForm(forms.ModelForm):

    class Meta:
        model = Supplier
        fields = ['name', 'phone', 'address', 'initial_debt']


class ExpenseForm(forms.ModelForm):

    class Meta:
        model = Expense
        fields = ['title', 'amount', 'note']


class PurchaseForm(forms.ModelForm):

    class Meta:
        model = Purchase
        fields = ['product', 'quantity', 'price_per_unit', 'note']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['price_per_unit'].required = False


class SupplierPaymentForm(forms.ModelForm):

    class Meta:
        model = SupplierPayment
        fields = ['amount', 'payment_type', 'comment']
