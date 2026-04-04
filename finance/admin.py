from django.contrib import admin
from finance.models import Customer, Product, Order, PaymentHistory, Supplier


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'address', 'total_debt')
    search_fields = ('name', 'phone')
    ordering = ('-total_debt',)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'address')
    search_fields = ('name',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'supplier')
    search_fields = ('name',)
    ordering = ('name',)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('customer', 'product', 'order_date', 'quantity', 'total_price')
    search_fields = ('customer__name', 'product__name')
    list_filter = ('order_date', 'product')
    ordering = ('-order_date',)
    readonly_fields = ('total_price', 'remaining_debt')


@admin.register(PaymentHistory)
class PaymentHistoryAdmin(admin.ModelAdmin):
    list_display = ('customer', 'amount', 'paid_at')
    search_fields = ('customer__name',)
    list_filter = ('paid_at',)
    ordering = ('-paid_at',)
    readonly_fields = ('customer',)
    
    def get_readonly_fields(self, request, obj=None):
        if obj:
            return self.readonly_fields + ('customer',)
        return self.readonly_fields
