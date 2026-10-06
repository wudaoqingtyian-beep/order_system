"""数据库初始化：建库建表 + 写入少量基础商品数据。

用法:
    python -m order_system.init_db
"""
import os

from . import db

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_FILE = os.path.join(HERE, "schema.sql")

SEED_PRODUCTS = [
    ("测试商品-手机", "1999.00", "ON_SALE"),
    ("测试商品-耳机", "299.00", "ON_SALE"),
    ("测试商品-下架品", "99.00", "OFF_SHELF"),
]


def split_sql(text: str):
    """按分号切分 SQL 语句，忽略注释行。"""
    for raw in text.split(";"):
        lines = [
            ln for ln in raw.splitlines() if not ln.strip().startswith("--")
        ]
        stmt = "\n".join(lines).strip()
        if stmt:
            yield stmt


def init_schema():
    with open(SCHEMA_FILE, encoding="utf-8") as f:
        sql_text = f.read()
    conn = db.connect(with_db=False, autocommit=True)
    try:
        with conn.cursor() as cur:
            for stmt in split_sql(sql_text):
                cur.execute(stmt)
    finally:
        conn.close()
    print("[init_db] 数据库与数据表创建完成")


def seed_products():
    conn = db.connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            for name, price, status in SEED_PRODUCTS:
                cur.execute(
                    "SELECT id FROM product WHERE name = %s", (name,)
                )
                if cur.fetchone():
                    continue
                cur.execute(
                    "INSERT INTO product (name, price, status) VALUES (%s, %s, %s)",
                    (name, price, status),
                )
                pid = cur.lastrowid
                cur.execute(
                    "INSERT INTO inventory (product_id, stock) VALUES (%s, %s)",
                    (pid, 100),
                )
    finally:
        conn.close()
    print("[init_db] 基础商品数据写入完成")


if __name__ == "__main__":
    init_schema()
    seed_products()
