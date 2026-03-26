from django.db import models


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

    COLOR_CHOICES = [
        ('#FF0000', "Qizil"),
        ('#FFA500', "To'q sariq"),
        ('#FFFF00', "Sariq"),
        ('#00B050', "Yashil"),
        ('#0070C0', "To'q ko'k"),
        ('#00B0F0', "Moviy"),
        ('#002060', "Ko'k"),
        ('#7030A0', "Binafsha"),
        ('#808080', "Kulrang"),
        ('#000000', "Qora"),
    ]

    name = models.CharField(max_length=50)
    color = models.CharField(max_length=10, choices=COLOR_CHOICES)

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

