from django import forms
from finance.models import Customer, Product, Order, PaymentHistory, Supplier


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
        order.customer = Customer.objects.get(id=self.cleaned_data['customer_id'])
        order.product = Product.objects.get(id=self.cleaned_data['product_id'])
        
        if commit:
            if self.instance.pk:  # This is an update
                old_order = Order.objects.get(pk=self.instance.pk)
                old_remaining_debt = old_order.remaining_debt
                old_customer = old_order.customer
                
                order.save()
                new_remaining_debt = order.remaining_debt
                
                if old_customer != order.customer:
                    old_customer.total_debt -= old_remaining_debt
                    old_customer.save()
                    
                    order.customer.total_debt += new_remaining_debt
                    order.customer.save()
                else:
                    debt_difference = new_remaining_debt - old_remaining_debt
                    order.customer.total_debt += debt_difference
                    order.customer.save()
            else:  # This is a new order
                order.save()
                customer = order.customer
                customer.total_debt += order.remaining_debt
                customer.save()
        
        return order


class CustomerForm(forms.ModelForm):
    debt = forms.CharField(required=False, initial='0')

    class Meta:
        model = Customer
        fields = ['name', 'phone', 'address', 'debt']

    def save(self, commit=True, update=False):
        customer = super().save(commit=False)
        debt = self.cleaned_data.get('debt').replace(',', '').replace(' ', '').replace('.', '') or 0

        if commit:
            if update:
                old_debt = customer.default_debt
                old_total_debt = customer.total_debt
                debt_difference = int(debt) - old_total_debt
                customer.total_debt = int(debt)
                customer.default_debt = old_debt + debt_difference
                customer.save()
            else:
                customer.total_debt = int(debt)
                customer.default_debt = int(debt)
            customer.save()
        return customer


class PaymentForm(forms.ModelForm):
    customer_id = forms.IntegerField()
    payment_amount = forms.CharField()
    comment = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Izoh qoldiring...'}))

    class Meta:
        model = PaymentHistory
        fields = ['customer_id', 'payment_amount', 'payment_type', 'comment']

    def save(self, commit=True):
        payment_history = super().save(commit=False)
        payment_history.customer = Customer.objects.get(id=self.cleaned_data['customer_id'])
        if commit:
            payment_history.amount = float(self.cleaned_data['payment_amount'].replace(',', '').replace(' ', '').replace('.', ''))
            payment_history.save()
            customer = payment_history.customer
            customer.total_debt -= payment_history.amount
            customer.save()
        return payment_history


class PaymentEditForm(forms.ModelForm):
    payment_amount = forms.CharField()
    comment = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Izoh qoldiring...'}))

    class Meta:
        model = PaymentHistory
        fields = ['payment_amount', 'payment_type', 'comment']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set initial value for payment_amount if instance exists
        if self.instance and self.instance.pk:
            self.fields['payment_amount'].initial = str(self.instance.amount)

    def save(self, commit=True):
        payment_history = super().save(commit=False)
        if commit:
            # Calculate the difference in amount to update customer debt
            old_amount = float(self.instance.amount)
            new_amount = float(self.cleaned_data['payment_amount'].replace(',', '').replace(' ', '').replace('.', ''))
            payment_history.amount = new_amount
            
            # Update customer debt based on the difference
            amount_difference = new_amount - old_amount
            customer = payment_history.customer
            customer.total_debt -= amount_difference
            customer.save()
            
            payment_history.save()
        return payment_history


class ProductForm(forms.ModelForm):

    class Meta:
        model = Product
        fields = ['name', 'price', 'supplier']

    def save(self, commit=True):
        product = super().save(commit=False)
        if commit:
            product.save()
        return product


class SupplierForm(forms.ModelForm):

    class Meta:
        model = Supplier
        fields = ['name', 'phone', 'address']
