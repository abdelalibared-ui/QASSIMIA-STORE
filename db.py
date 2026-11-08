
import os
import sqlite3
from pathlib import Path

DB_PATH = os.getenv("DATABASE_PATH", "./qassimia.db")

def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True) if "/" in DB_PATH else None
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT DEFAULT '',
            price_dzd INTEGER NOT NULL CHECK(price_dzd >= 0),
            image_url TEXT DEFAULT '',
            colors TEXT DEFAULT '[]',
            sizes TEXT DEFAULT '[]',
            stock INTEGER NOT NULL DEFAULT 0 CHECK(stock >= 0),
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            wilaya TEXT NOT NULL,
            municipality TEXT NOT NULL,
            address TEXT NOT NULL,
            notes TEXT DEFAULT '',
            payment_method TEXT NOT NULL,
            subtotal_dzd INTEGER NOT NULL,
            delivery_fee_dzd INTEGER NOT NULL DEFAULT 0,
            total_dzd INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'جديد',
            telegram_user_id TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            color TEXT NOT NULL,
            size TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price_dzd INTEGER NOT NULL
        );
        """)
        count = con.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if count == 0:
            # Optional starter examples; change prices and stock from the dashboard.
            con.execute("""INSERT INTO products
                (name, category, description, price_dzd, image_url, colors, sizes, stock)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ("قشابية القاسمية", "قشابية", "أضف وصف المنتج والصور والأسعار الحقيقية من لوحة التحكم.", 0, "",
                 '["بيج","رمادي","أخضر"]', '["S","M","L","XL"]', 0))
            con.execute("""INSERT INTO products
                (name, category, description, price_dzd, image_url, colors, sizes, stock)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ("جيلية القاسمية", "جيلية", "أضف وصف المنتج والصور والأسعار الحقيقية من لوحة التحكم.", 0, "",
                 '["أسود","رمادي","أخضر"]', '["S","M","L","XL"]', 0))
