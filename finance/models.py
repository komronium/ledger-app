from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class UserProfile(models.Model):
    ROLE_ADMIN = 'admin'
    ROLE_OPERATOR = 'operator'
    ROLE_CHOICES = [
        (ROLE_ADMIN, 'Admin'),
        (ROLE_OPERATOR, 'Operator'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_OPERATOR)

    class Meta:
        db_table = 'user_profiles'

    def __str__(self):
        return f"{self.user.username} ({self.role})"

    def is_admin(self):
        return self.role == self.ROLE_ADMIN or self.user.is_superuser


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        role = UserProfile.ROLE_ADMIN if instance.is_superuser else UserProfile.ROLE_OPERATOR
        UserProfile.objects.get_or_create(user=instance, defaults={'role': role})


class Supplier(models.Model):
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.CharField(max_length=255, blank=True, null=True)
    initial_debt = models.IntegerField(default=0, verbose_name="Boshlang'ich qarz")

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
    quantity = models.IntegerField(default=0, verbose_name="Mavjud miqdor (kg)")
    supplier = models.ForeignKey(
        Supplier, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='products', verbose_name="Firma"
    )
    promo_buy = models.IntegerField(null=True, blank=True, verbose_name="Aksiya: nechta sotib olsa")
    promo_free = models.IntegerField(null=True, blank=True, verbose_name="Aksiya: nechta bepul")

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

    def _compute_promo_free(self, product, quantity):
        if not product:
            return 0
        if product.promo_buy and product.promo_free and product.promo_buy > 0:
            return (quantity // product.promo_buy) * product.promo_free
        return 0

    def save(self, *args, **kwargs):
        self.total_price = self.quantity * self.price_per_kg
        self.remaining_debt = self.total_price

        is_new = self.pk is None
        if is_new and self.product:
            free_count = self._compute_promo_free(self.product, self.quantity)
            self.product.quantity -= (self.quantity + free_count)
            self.product.save()
        super().save(*args, **kwargs)


    def __str__(self):
        product_name = self.product.name if self.product else '—'
        customer_name = self.customer.name if self.customer else '—'
        return f"{customer_name} - {product_name} - {self.order_date}"


class PaymentHistory(models.Model):

    class PaymentTypeChoices(models.TextChoices):
        BANK = 'bank', "Pul ko'chirish"
        CASH = 'cash', 'Naqd'
        CLICK = 'click', 'Click'
        BARTER = 'barter', 'Barter (Mahsulot bilan)'

    customer = models.ForeignKey('Customer', on_delete=models.CASCADE, related_name='payment_histories')
    payment_type = models.CharField(
        max_length=20,
        choices=PaymentTypeChoices.choices,
        null=True,
        blank=True,
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    usd_amount = models.DecimalField(
        max_digits=15, decimal_places=2,
        null=True, blank=True,
        verbose_name="Dollar miqdori",
    )
    exchange_rate = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        verbose_name="Kurs (so'm)",
    )
    barter_product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='customer_barters',
        verbose_name="Barter mahsuloti",
    )
    barter_quantity = models.IntegerField(default=0, verbose_name="Barter miqdori")
    comment = models.TextField(null=True, blank=True, verbose_name="Izoh")
    paid_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payment_histories'
        verbose_name = 'Payment History'
        verbose_name_plural = 'Payment Histories'

    def __str__(self):
        return f"{self.customer.name} - {self.amount} so'm - {self.paid_at.strftime('%Y-%m-%d %H:%M')}"


class Purchase(models.Model):

    class PurchaseTypeChoices(models.TextChoices):
        CASH = 'cash', 'Naqd'
        CREDIT = 'credit', 'Qarz'
        BARTER = 'barter', 'Barter (Ayirboshlash)'

    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='purchases', verbose_name="Firma")
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name='purchases', verbose_name="Mahsulot")
    quantity = models.IntegerField(verbose_name="Miqdori")
    price_per_unit = models.IntegerField(null=True, blank=True, verbose_name="Birlik narxi")
    total_cost = models.IntegerField(default=0, verbose_name="Jami narx")
    usd_price_per_unit = models.DecimalField(
        max_digits=12, decimal_places=2,
        null=True, blank=True,
        verbose_name="Dollar birlik narxi",
    )
    exchange_rate = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        verbose_name="Kurs (so'm)",
    )
    purchase_date = models.DateField(auto_now_add=True)
    note = models.TextField(blank=True, null=True, verbose_name="Izoh")
    purchase_type = models.CharField(
        max_length=20,
        choices=PurchaseTypeChoices.choices,
        default=PurchaseTypeChoices.CASH,
        verbose_name="Xarid turi"
    )
    barter_product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='barter_purchases',
        verbose_name="Barter mahsuloti"
    )
    barter_quantity = models.IntegerField(default=0, verbose_name="Barter miqdori")

    class Meta:
        db_table = 'purchases'
        verbose_name = 'Purchase'
        verbose_name_plural = 'Purchases'
        ordering = ['-purchase_date']

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if self.price_per_unit is not None:
            self.total_cost = self.quantity * self.price_per_unit
        else:
            self.total_cost = 0
        super().save(*args, **kwargs)
        if is_new and self.product:
            self.product.quantity += self.quantity
            self.product.save()
        if is_new and self.purchase_type == self.PurchaseTypeChoices.BARTER and self.barter_product:
            self.barter_product.quantity -= self.barter_quantity
            self.barter_product.save()

    def __str__(self):
        return f"{self.supplier.name} - {self.product} - {self.purchase_date}"


class SupplierPayment(models.Model):

    class PaymentTypeChoices(models.TextChoices):
        BANK = 'bank', "Pul ko'chirish"
        CASH = 'cash', 'Naqd'
        CLICK = 'click', 'Click'

    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='payments', verbose_name="Firma")
    amount = models.IntegerField(verbose_name="Summa")
    usd_amount = models.DecimalField(
        max_digits=15, decimal_places=2,
        null=True, blank=True,
        verbose_name="Dollar miqdori",
    )
    exchange_rate = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        verbose_name="Kurs (so'm)",
    )
    payment_type = models.CharField(max_length=20, choices=PaymentTypeChoices.choices, null=True, blank=True)
    paid_at = models.DateField(auto_now_add=True)
    comment = models.TextField(blank=True, null=True, verbose_name="Izoh")

    class Meta:
        db_table = 'supplier_payments'
        verbose_name = 'Supplier Payment'
        verbose_name_plural = 'Supplier Payments'
        ordering = ['-paid_at']

    def __str__(self):
        return f"{self.supplier.name} - {self.amount} so'm - {self.paid_at}"


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
