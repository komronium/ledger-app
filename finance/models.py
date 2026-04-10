from django.db import models


class Supplier(models.Model):
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = 'suppliers'
        verbose_name = 'Supplier'
        verbose_name_plural = 'Suppliers'

    def __str__(self):
        return self.name


class Customer(models.Model):
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    address = models.CharField(max_length=255)
    default_debt = models.IntegerField(default=0)
    total_debt = models.IntegerField(default=0)

    class Meta:
        db_table = 'customers'
        verbose_name = 'Customer'
        verbose_name_plural = 'Customers'

    def __str__(self):
        return self.name


class Product(models.Model):

    name = models.CharField(max_length=50)
    price = models.IntegerField(default=0, verbose_name="Narxi")
    supplier = models.ForeignKey(
        Supplier, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='products', verbose_name="Firma"
    )

    class Meta:
        db_table = 'products'
        verbose_name = 'Product'
        verbose_name_plural = 'Products'

    def __str__(self):
        return self.name


class Order(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, related_name='orders', null=True)
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, related_name='orders', null=True)
    
    quantity = models.IntegerField(verbose_name="Miqdori")
    price_per_kg = models.IntegerField()
    order_date = models.DateField(auto_now_add=True)

    total_price = models.IntegerField()  
    remaining_debt = models.IntegerField()

    class Meta:
        db_table = 'orders'
        verbose_name = 'Order'
        verbose_name_plural = 'Orders'

    def save(self, *args, **kwargs):
        self.total_price = self.quantity * self.price_per_kg
        self.remaining_debt = self.total_price
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.customer.name} - {self.product.name} - {self.order_date}"
    

class PaymentHistory(models.Model):

    class PaymentTypeChoices(models.TextChoices):
        BANK = 'bank', "Pul ko'chirish"
        CASH = 'cash', 'Naqd'
        CLICK = 'click', 'Click'

    customer = models.ForeignKey('Customer', on_delete=models.CASCADE, related_name='payment_histories')
    payment_type = models.CharField(
        max_length=20,
        choices=PaymentTypeChoices.choices,
        null=True,
        blank=True,
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    comment = models.TextField(null=True, blank=True, verbose_name="Izoh")
    paid_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payment_histories'
        verbose_name = 'Payment History'
        verbose_name_plural = 'Payment Histories'

    def __str__(self):
        return f"{self.customer.name} - {self.amount} so'm - {self.paid_at.strftime('%Y-%m-%d %H:%M')}"


class Expense(models.Model):
    title = models.CharField(max_length=200, verbose_name="Sarlavha")
    amount = models.IntegerField(verbose_name="Summa")
    date = models.DateField(auto_now_add=True)
    note = models.TextField(blank=True, null=True, verbose_name="Izoh")

    class Meta:
        db_table = 'expenses'
        verbose_name = 'Expense'
        verbose_name_plural = 'Expenses'
        ordering = ['-date']

    def __str__(self):
        return f"{self.title} - {self.amount}"

