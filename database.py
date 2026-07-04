"""
database.py
SQLite persistence layer with thread-safe writes for concurrent consumers.
"""
import sqlite3
import threading
import os
from datetime import datetime

# Thread-local storage for connection pooling per thread
_thread_local = threading.local()

DB_PATH = os.getenv("DB_PATH", "/app/data/products.db")

# Ensure the directory exists (skip silently in read-only /app during imports)
try:
    os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else ".", exist_ok=True)
except PermissionError:
    pass

# Module-level lock for schema initialization (one-time only)
_schema_lock = threading.Lock()
_schema_initialized = False


def _get_connection():
    """Return a sqlite3 connection for the current thread with timeout for concurrent writes."""
    if not hasattr(_thread_local, "conn") or _thread_local.conn is None:
        # timeout=30 seconds lets SQLite wait for the write lock instead of failing immediately
        _thread_local.conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
        _thread_local.conn.execute("PRAGMA journal_mode=WAL;")
        _thread_local.conn.execute("PRAGMA busy_timeout=30000;")
    return _thread_local.conn


def init_schema():
    """Create the products table if it does not exist. Thread-safe / idempotent."""
    global _schema_initialized
    with _schema_lock:
        if _schema_initialized:
            return
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT UNIQUE NOT NULL,
                stock_code TEXT,
                kdv_haric_tavsiye_edilen_perakende_fiyat TEXT,
                kdv_haric_net_fiyat TEXT,
                kdv_haric_satis_fiyati TEXT,
                stok_durumu TEXT,
                stock_amount INTEGER,
                product_description TEXT,
                is_group_product INTEGER DEFAULT 0,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scrape_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.commit()
        conn.close()
        _schema_initialized = True


def reset_database():
    """Drop products + scrape_meta and recreate an empty schema.

    Called by the harvester at the start of every pipeline run so each
    `docker compose up` produces a clean SQLite file.
    """
    global _schema_initialized
    with _schema_lock:
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        conn.execute("PRAGMA busy_timeout=30000;")
        conn.execute("DROP TABLE IF EXISTS products")
        conn.execute("DROP TABLE IF EXISTS scrape_meta")
        conn.commit()
        conn.close()
        _schema_initialized = False
    init_schema()
    print(f"Database reset: dropped and recreated schema at {DB_PATH}")


def save_product(data: dict) -> bool:
    """
    Insert or replace a product row.
    data keys expected:
        sku, stockCode (optional),
        kdv_haric_tavsiye_edilen_perakende_fiyat,
        kdv_haric_net_fiyat,
        kdv_haric_satis_fiyati,
        stok_durumu,
        stock_amount,
        product_description,
        is_group_product (0/1)
    """
    init_schema()
    conn = _get_connection()
    try:
        conn.execute(
            """
            INSERT INTO products (
                sku, stock_code,
                kdv_haric_tavsiye_edilen_perakende_fiyat,
                kdv_haric_net_fiyat,
                kdv_haric_satis_fiyati,
                stok_durumu,
                stock_amount,
                product_description,
                is_group_product,
                scraped_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sku) DO UPDATE SET
                stock_code=excluded.stock_code,
                kdv_haric_tavsiye_edilen_perakende_fiyat=excluded.kdv_haric_tavsiye_edilen_perakende_fiyat,
                kdv_haric_net_fiyat=excluded.kdv_haric_net_fiyat,
                kdv_haric_satis_fiyati=excluded.kdv_haric_satis_fiyati,
                stok_durumu=excluded.stok_durumu,
                stock_amount=excluded.stock_amount,
                product_description=excluded.product_description,
                is_group_product=excluded.is_group_product,
                scraped_at=excluded.scraped_at
            """,
            (
                data.get("sku", ""),
                data.get("stockCode", data.get("sku", "")),
                data.get("kdv_haric_tavsiye_edilen_perakende_fiyat"),
                data.get("kdv_haric_net_fiyat"),
                data.get("kdv_haric_satis_fiyati"),
                data.get("stok_durumu"),
                data.get("stock_amount"),
                data.get("product_description"),
                1 if data.get("is_group_product") else 0,
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        print(f"💾 SQLite saved SKU={data.get('sku')} | stok_durumu={data.get('stok_durumu')} | stock_amount={data.get('stock_amount')}")
        return True
    except Exception as e:
        print(f"❌ SQLite save error for SKU={data.get('sku')}: {e}")
        return False


def get_all_products():
    """Return every row from the products table as a list of dicts."""
    init_schema()
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT * FROM products ORDER BY scraped_at DESC")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_scrape_meta(key: str) -> str | None:
    init_schema()
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    cursor = conn.execute("SELECT value FROM scrape_meta WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def set_scrape_meta(key: str, value: str):
    init_schema()
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute(
        "INSERT INTO scrape_meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def count_products() -> int:
    init_schema()
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    cursor = conn.execute("SELECT COUNT(*) FROM products")
    count = cursor.fetchone()[0]
    conn.close()
    return count
