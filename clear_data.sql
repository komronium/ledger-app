-- Clear all application data (preserves Django system tables and migrations)
PRAGMA foreign_keys = OFF;

DELETE FROM orders;
DELETE FROM payment_histories;
DELETE FROM purchases;
DELETE FROM supplier_payments;
DELETE FROM expenses;
DELETE FROM products;
DELETE FROM customers;
DELETE FROM suppliers;
DELETE FROM user_profiles;
DELETE FROM auth_user;

-- Reset auto-increment counters
DELETE FROM sqlite_sequence WHERE name IN (
    'orders',
    'payment_histories',
    'purchases',
    'supplier_payments',
    'expenses',
    'products',
    'customers',
    'suppliers',
    'user_profiles',
    'auth_user'
);

PRAGMA foreign_keys = ON;
