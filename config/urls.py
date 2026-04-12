from django.contrib import admin
from django.urls import path
from finance.views import (
    LoginView, LogoutView,
    OrderView, CustomerView, DebtView, ProductView, StatisticsView, ProductDeleteView,
    OrderEditView, OrderDeleteView, CustomerDeleteView, PaymentDeleteView, PaymentEditView,
    SupplierView, SupplierDeleteView, ProductEditView,
    ExpenseView, ExpenseDeleteView,
    SupplierDetailView, PurchaseDeleteView, SupplierPaymentDeleteView,
)


urlpatterns = [
    path('admin/', admin.site.urls),

    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    
    path('', OrderView.as_view(), name='dashboard'),
    path('order/edit/<int:pk>/', OrderEditView.as_view(), name='order_edit'),
    path('order/delete/<int:pk>/', OrderDeleteView.as_view(), name='order_delete'),
    path('customer/', CustomerView.as_view(), name='customer'),
    path('customer/delete/<int:pk>/', CustomerDeleteView.as_view(), name='customer_delete'),
    path('debt/', DebtView.as_view(), name='debts'),
    path('product/', ProductView.as_view(), name='product'),
    path('product/delete/<int:pk>/', ProductDeleteView.as_view(), name='product_delete'),
    path('product/edit/<int:pk>/', ProductEditView.as_view(), name='product_edit'),
    path('statistics/', StatisticsView.as_view(), name='stats'),
    path('payments/edit/<int:pk>/', PaymentEditView.as_view(), name='payment_edit'),
    path('payments/delete/<int:pk>/', PaymentDeleteView.as_view(), name='payment_delete'),
    path('supplier/', SupplierView.as_view(), name='supplier'),
    path('supplier/delete/<int:pk>/', SupplierDeleteView.as_view(), name='supplier_delete'),
    path('supplier/<int:pk>/', SupplierDetailView.as_view(), name='supplier_detail'),
    path('supplier/purchase/delete/<int:pk>/', PurchaseDeleteView.as_view(), name='purchase_delete'),
    path('supplier/payment/delete/<int:pk>/', SupplierPaymentDeleteView.as_view(), name='supplier_payment_delete'),
    path('expense/', ExpenseView.as_view(), name='expense'),
    path('expense/delete/<int:pk>/', ExpenseDeleteView.as_view(), name='expense_delete'),
]
