from django.contrib import admin
from finance.models import Customer, Product, Order, PaymentHistory, Supplier, Expense, Purchase, SupplierPayment


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


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ('supplier', 'product', 'quantity', 'price_per_unit', 'total_cost', 'purchase_date')
    list_filter = ('supplier', 'purchase_date')
    ordering = ('-purchase_date',)


@admin.register(SupplierPayment)
class SupplierPaymentAdmin(admin.ModelAdmin):
    list_display = ('supplier', 'amount', 'payment_type', 'paid_at')
    list_filter = ('supplier', 'paid_at')
    ordering = ('-paid_at',)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('title', 'amount', 'date')
    search_fields = ('title',)
    ordering = ('-date',)


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
