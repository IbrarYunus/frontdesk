"""The shop's database: schema, demo data, and a connection helper."""

import sqlite3
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE customers (id TEXT PRIMARY KEY, name TEXT, email TEXT);
CREATE TABLE orders (
    id TEXT PRIMARY KEY, customer_id TEXT REFERENCES customers(id), status TEXT,
    placed_on TEXT, shipped_on TEXT, delivered_on TEXT, shipping_address TEXT, tracking TEXT
);
CREATE TABLE order_items (
    order_id TEXT REFERENCES orders(id), sku TEXT, name TEXT, price REAL, final_sale INTEGER DEFAULT 0,
    PRIMARY KEY (order_id, sku)
);
CREATE TABLE refunds (
    id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, sku TEXT, amount REAL, reason TEXT,
    approved_by TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE escalations (
    id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id TEXT, priority TEXT, summary TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, customer_id TEXT, tool TEXT, input TEXT,
    outcome TEXT, detail TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE sessions (id TEXT PRIMARY KEY, customer_id TEXT, state TEXT);
"""

CUSTOMERS = [
    ("C1", "Maya Okafor", "maya@example.com"),
    ("C2", "Daniel Reyes", "daniel@example.com"),
    ("C3", "Priya Nair", "priya@example.com"),
    ("C4", "Tom Lindqvist", "tom@example.com"),
]

# id, customer, status, placed, shipped, delivered, address, tracking
ORDERS = [
    ("HO-1001", "C1", "delivered", "2026-08-31", "2026-09-01", "2026-09-05", "14 Alder Row, Leeds LS6 2QT", "RM482910GB"),
    ("HO-1002", "C1", "processing", "2026-09-14", None, None, "14 Alder Row, Leeds LS6 2QT", None),
    ("HO-1003", "C1", "shipped", "2026-09-10", "2026-09-12", None, "14 Alder Row, Leeds LS6 2QT", "RM483377GB"),
    ("HO-1004", "C2", "delivered", "2026-08-27", "2026-08-28", "2026-09-01", "3 Quay Street, Bristol BS1 4DJ", "RM481102GB"),
    ("HO-1005", "C2", "delivered", "2026-07-15", "2026-07-16", "2026-07-20", "3 Quay Street, Bristol BS1 4DJ", "RM470045GB"),
    ("HO-1006", "C2", "delivered", "2026-07-23", "2026-07-24", "2026-07-28", "3 Quay Street, Bristol BS1 4DJ", "RM471630GB"),
    ("HO-1007", "C3", "delivered", "2026-09-03", "2026-09-04", "2026-09-08", "22 Mill Lane, York YO1 7HP", "RM482001GB"),
    ("HO-1008", "C3", "delivered", "2026-08-28", "2026-08-29", "2026-09-02", "22 Mill Lane, York YO1 7HP", "RM481544GB"),
    ("HO-1009", "C4", "delivered", "2026-09-05", "2026-09-06", "2026-09-10", "8 Fell View, Kendal LA9 4BD", "RM482733GB"),
]

# order, sku, name, price, final_sale
ITEMS = [
    ("HO-1001", "MUG-01", "Trail Mug", 24.0, 0),
    ("HO-1001", "BEANIE-02", "Merino Beanie", 38.0, 0),
    ("HO-1002", "TENT-2P", "Two-Person Tent", 289.0, 0),
    ("HO-1003", "LAMP-05", "Headlamp", 45.0, 0),
    ("HO-1004", "JACKET-DN", "Down Jacket", 240.0, 0),
    ("HO-1005", "BOOT-HK", "Hiking Boots", 165.0, 0),
    ("HO-1006", "STOVE-01", "Camp Stove", 79.0, 0),
    ("HO-1007", "SHELL-CL", "Clearance Rain Shell", 60.0, 1),
    ("HO-1007", "SOCK-WL", "Wool Socks", 18.0, 0),
    ("HO-1008", "FILTER-01", "Water Filter", 55.0, 0),
    ("HO-1009", "HARNESS-01", "Climbing Harness", 95.0, 0),
]

REFUNDS = [("HO-1008", "FILTER-01", 55.0, "changed_mind", "auto")]


@contextmanager
def connect(path=None):
    # The server streams from a generator that FastAPI may resume on another worker thread.
    db = sqlite3.connect(path or config.DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    finally:
        db.close()


def reset(path=None) -> None:
    path = path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    with connect(path) as db:
        db.executescript(SCHEMA)
        db.executemany("INSERT INTO customers VALUES (?,?,?)", CUSTOMERS)
        db.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)", ORDERS)
        db.executemany("INSERT INTO order_items VALUES (?,?,?,?,?)", ITEMS)
        db.executemany(
            "INSERT INTO refunds (order_id, sku, amount, reason, approved_by) VALUES (?,?,?,?,?)", REFUNDS
        )


def ensure(path=None) -> None:
    if not (path or config.DB_PATH).exists():
        reset(path)
