import sqlite3
c = sqlite3.connect("db.sqlite3")
for table in ("supplier_payments", "payment_histories", "purchases"):
    cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})")]
    print(f"{table}: {cols}")
