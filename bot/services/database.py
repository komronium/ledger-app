"""
Database service layer for accessing customer data
Uses Django ORM directly with async support
"""
import os
import sys
import django
from pathlib import Path
from typing import Optional, List, Dict
from asgiref.sync import sync_to_async


def setup_django():
    """Set up Django environment"""
    project_path = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_path))
    
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()


# Setup Django on import
setup_django()

from finance.models import Customer, Order, PaymentHistory, Supplier, Purchase, SupplierPayment


class CustomerService:
    """Service for accessing customer data"""
    
    @staticmethod
    @sync_to_async
    def get_all_customers() -> List[Dict]:
        """
        Get all customers
        
        Returns:
            List of all customers
        """
        customers = Customer.objects.all().order_by('name')
        
        result = []
        for customer in customers:
            result.append({
                'id': customer.id,
                'name': customer.name,
                'phone': customer.phone,
                'address': customer.address,
                'default_debt': customer.default_debt,
                'total_debt': customer.total_debt,
            })
        
        return result
    
    @staticmethod
    @sync_to_async
    def get_customer_by_phone(phone: str) -> Optional[Dict]:
        """
        Get customer by phone number
        
        Args:
            phone: Customer phone number
            
        Returns:
            Customer data or None
        """
        try:
            customer = Customer.objects.get(phone=phone)
            return {
                'id': customer.id,
                'name': customer.name,
                'phone': customer.phone,
                'address': customer.address,
                'default_debt': customer.default_debt,
                'total_debt': customer.total_debt,
            }
        except Customer.DoesNotExist:
            return None
    
    @staticmethod
    @sync_to_async
    def get_customer_orders(customer_id: int) -> List[Dict]:
        """
        Get all orders for a customer
        
        Args:
            customer_id: Customer ID
            
        Returns:
            List of order data
        """
        orders = Order.objects.filter(customer_id=customer_id).select_related(
            'product', 'customer'
        ).order_by('-order_date')
        
        result = []
        for order in orders:
            result.append({
                'id': order.id,
                'product': order.product.name if order.product else 'N/A',
                'quantity': order.quantity,
                'price_per_kg': order.price_per_kg,
                'order_date': order.order_date.strftime('%Y-%m-%d'),
                'total_price': order.total_price,
                'remaining_debt': order.remaining_debt,
            })
        
        return result
    
    @staticmethod
    @sync_to_async
    def get_customer_summary(customer_id: int) -> Dict:
        """
        Get customer summary (total amount, total debt)
        
        Args:
            customer_id: Customer ID
            
        Returns:
            Customer summary data
        """
        customer = Customer.objects.get(id=customer_id)
        orders = Order.objects.filter(customer_id=customer_id)
        
        total_ordered = sum(order.total_price for order in orders)
        total_debt = customer.total_debt
        
        return {
            'total_ordered': total_ordered,
            'total_debt': total_debt,
            'customer_default_debt': customer.default_debt,
            'orders_count': orders.count(),
        }
    
    @staticmethod
    @sync_to_async
    def get_customer_combined_data(customer_id: int) -> tuple:
        """
        Get combined orders and payments with cumulative debt
        Similar to web app's _calculate_cumulative_debt
        
        Args:
            customer_id: Customer ID
            
        Returns:
            Tuple of (combined_data, customer) with cumulative debt calculated
        """
        customer = Customer.objects.get(id=customer_id)
        orders = Order.objects.filter(customer_id=customer_id).order_by('order_date')
        payments = PaymentHistory.objects.filter(customer_id=customer_id).order_by('paid_at')
        
        combined_data = []
        
        # Add orders
        for order in orders:
            combined_data.append({
                'type': 'order',
                'id': order.id,
                'product': order.product.name if order.product else 'N/A',
                'quantity': order.quantity,
                'price_per_kg': order.price_per_kg,
                'date': order.order_date.strftime('%Y-%m-%d'),
                'total_price': order.total_price,
                'remaining_debt': order.remaining_debt,
            })
        
        # Add payments
        for payment in payments:
            payment_type_dict = dict(PaymentHistory.PaymentTypeChoices.choices)
            combined_data.append({
                'type': 'payment',
                'id': payment.id,
                'product': '',
                'quantity': 0,
                'price_per_kg': 0,
                'paid_amount': float(payment.amount),
                'date': payment.paid_at.strftime('%Y-%m-%d'),
                'total_price': 0,
                'remaining_debt': -float(payment.amount),
                'payment_type': payment_type_dict.get(payment.payment_type, payment.payment_type),
                'comment': payment.comment or '',
            })
        
        # Sort by date
        combined_data.sort(key=lambda x: x['date'])
        
        # Calculate cumulative debt
        cumulative_debt = customer.total_debt
        
        # Calculate total from filtered transactions
        total_filtered_debt = sum(
            item['remaining_debt'] for item in combined_data if item['type'] == 'order'
        ) - sum(
            item['paid_amount'] for item in combined_data if item['type'] == 'payment'
        )
        
        # Adjust starting point
        cumulative_debt = cumulative_debt - total_filtered_debt
        
        # Add cumulative debt to each item
        for item in combined_data:
            if item['type'] == 'order':
                cumulative_debt += item['remaining_debt']
            elif item['type'] == 'payment':
                cumulative_debt -= item['paid_amount']

            item['cumulative_debt'] = cumulative_debt

        return combined_data, customer


class SupplierService:
    """Service for accessing supplier data"""

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        return (phone or '').strip().replace('+', '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '')

    @staticmethod
    @sync_to_async
    def get_supplier_by_phone(phone: str) -> Optional[Dict]:
        """Find a supplier by phone number, tolerant of formatting."""
        normalized = SupplierService._normalize_phone(phone)
        candidates = [phone, normalized]
        if normalized.startswith('998') and len(normalized) == 12:
            candidates.append(normalized[3:])
        elif len(normalized) == 9:
            candidates.append('998' + normalized)

        supplier = None
        for candidate in candidates:
            if not candidate:
                continue
            supplier = Supplier.objects.filter(phone=candidate).first()
            if supplier:
                break
        if not supplier:
            # Last resort: substring match (handles stored values with spaces / dashes)
            for s in Supplier.objects.exclude(phone__isnull=True).exclude(phone__exact=''):
                if SupplierService._normalize_phone(s.phone) == normalized:
                    supplier = s
                    break
        if not supplier:
            return None
        return {
            'id': supplier.id,
            'name': supplier.name,
            'phone': supplier.phone or '',
            'address': supplier.address or '',
            'initial_debt': supplier.initial_debt,
        }

    @staticmethod
    @sync_to_async
    def get_supplier_report(supplier_id: int) -> Dict:
        """Build a combined supplier report with purchases, payments, debt."""
        supplier = Supplier.objects.get(id=supplier_id)
        purchases = Purchase.objects.filter(supplier=supplier).select_related('product', 'barter_product').order_by('purchase_date')
        payments = SupplierPayment.objects.filter(supplier=supplier).select_related('barter_product').order_by('paid_at')

        purchase_type_dict = dict(Purchase.PurchaseTypeChoices.choices)
        payment_type_dict = dict(SupplierPayment.PaymentTypeChoices.choices)

        rows = []
        for p in purchases:
            rows.append({
                'type': 'purchase',
                'date': p.purchase_date.strftime('%Y-%m-%d'),
                'description': (p.product.name if p.product else '—'),
                'kind': purchase_type_dict.get(p.purchase_type, p.purchase_type),
                'quantity': p.quantity,
                'price_per_unit': p.price_per_unit or 0,
                'amount': p.total_cost,
                'note': p.note or '',
            })
        for pay in payments:
            extra = ''
            if pay.payment_type == SupplierPayment.PaymentTypeChoices.BARTER and pay.barter_product:
                extra = f"{pay.barter_product.name} x {pay.barter_quantity}"
            rows.append({
                'type': 'payment',
                'date': pay.paid_at.strftime('%Y-%m-%d'),
                'description': extra or (pay.comment or '—'),
                'kind': payment_type_dict.get(pay.payment_type, pay.payment_type or '—'),
                'quantity': 0,
                'price_per_unit': 0,
                'amount': pay.amount,
                'note': pay.comment or '',
            })

        rows.sort(key=lambda r: r['date'])

        total_purchased = sum(r['amount'] for r in rows if r['type'] == 'purchase')
        total_paid = sum(r['amount'] for r in rows if r['type'] == 'payment')
        debt = supplier.initial_debt + total_purchased - total_paid

        # Cumulative debt walk
        running = supplier.initial_debt
        for r in rows:
            if r['type'] == 'purchase':
                running += r['amount']
            else:
                running -= r['amount']
            r['cumulative_debt'] = running

        return {
            'supplier': {
                'id': supplier.id,
                'name': supplier.name,
                'phone': supplier.phone or '',
                'address': supplier.address or '',
                'initial_debt': supplier.initial_debt,
            },
            'rows': rows,
            'total_purchased': total_purchased,
            'total_paid': total_paid,
            'debt': debt,
        }
