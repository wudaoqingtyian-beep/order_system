"""业务逻辑层：商品、库存、订单。

约定：
1. 所有写操作使用 db.transaction()，任一步失败整体回滚。
2. 金额一律使用 Decimal 计算，避免浮点误差。
3. 抛出的都是 errors.BizError，错误码稳定。
"""
import os
from decimal import Decimal

from . import db, errors
from .errors import BizError

STATUS_ON_SALE = "ON_SALE"
STATUS_OFF_SHELF = "OFF_SHELF"
ORDER_PENDING = "PENDING"
ORDER_CANCELLED = "CANCELLED"


def _fail(err):
    code, msg = err
    raise BizError(code, msg)


# ---------------------------------------------------------------- 用户
def create_user(username: str, password: str) -> dict:
    with db.get_conn() as conn:
        exists = db.query_one(
            "SELECT id FROM `user` WHERE username = %s", (username,), conn
        )
        if exists:
            raise BizError(1002, "用户名已存在")
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO `user` (username, password) VALUES (%s, %s)",
                (username, password),
            )
            uid = cur.lastrowid
    return get_user(uid)


def get_user(user_id: int) -> dict:
    row = db.query_one(
        "SELECT id, username, created_at FROM `user` WHERE id = %s", (user_id,)
    )
    if not row:
        _fail(errors.E_USER_NOT_FOUND)
    return {
        "id": row["id"],
        "username": row["username"],
        "created_at": row["created_at"].strftime("%Y-%m-%d %H:%M:%S"),
    }


# ---------------------------------------------------------------- 商品
def list_products() -> list:
    rows = db.query_all("SELECT id, name, price, status, created_at FROM product ORDER BY id")
    return [_product_out(r) for r in rows]


def get_product(product_id: int) -> dict:
    row = db.query_one(
        "SELECT id, name, price, status, created_at FROM product WHERE id = %s",
        (product_id,),
    )
    if not row:
        _fail(errors.E_PRODUCT_NOT_FOUND)
    return _product_out(row)


def _product_out(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "price": float(row["price"]),
        "status": row["status"],
        "created_at": row["created_at"].strftime("%Y-%m-%d %H:%M:%S"),
    }


# ---------------------------------------------------------------- 库存
def setup_product(name, price, stock, status=STATUS_ON_SALE) -> dict:
    """测试用：一次性创建商品 + 库存。"""
    if status not in (STATUS_ON_SALE, STATUS_OFF_SHELF) or stock < 0:
        _fail(errors.E_PARAM_INVALID)
    with db.transaction() as cur:
        cur.execute(
            "INSERT INTO product (name, price, status) VALUES (%s, %s, %s)",
            (name or f"测试商品-{os.urandom(3).hex()}", Decimal(str(price)), status),
        )
        product_id = cur.lastrowid
        cur.execute(
            "INSERT INTO inventory (product_id, stock) VALUES (%s, %s)",
            (product_id, stock),
        )
    data = get_product(product_id)
    data["stock"] = stock
    return data


def get_inventory(product_id: int) -> dict:
    row = db.query_one(
        "SELECT product_id, stock, updated_at FROM inventory WHERE product_id = %s",
        (product_id,),
    )
    if not row:
        # 商品存在但没有库存记录时，按 0 库存返回，便于断言
        product = db.query_one("SELECT id FROM product WHERE id = %s", (product_id,))
        if not product:
            _fail(errors.E_PRODUCT_NOT_FOUND)
        return {"product_id": product_id, "stock": 0}
    return {
        "product_id": row["product_id"],
        "stock": row["stock"],
        "updated_at": row["updated_at"].strftime("%Y-%m-%d %H:%M:%S"),
    }


def set_inventory(product_id: int, stock: int) -> dict:
    """开发/测试环境准备库存数据用。"""
    if stock < 0:
        _fail(errors.E_PARAM_INVALID)
    with db.transaction() as cur:
        _lock_product(cur, product_id)
        cur.execute(
            "INSERT INTO inventory (product_id, stock) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE stock = VALUES(stock)",
            (product_id, stock),
        )
    return get_inventory(product_id)


def set_product_status(product_id: int, status: str) -> dict:
    """测试用：上架 / 下架商品。"""
    if status not in (STATUS_ON_SALE, STATUS_OFF_SHELF):
        _fail(errors.E_PARAM_INVALID)
    with db.transaction() as cur:
        _lock_product(cur, product_id)
        cur.execute("UPDATE product SET status = %s WHERE id = %s", (status, product_id))
    return get_product(product_id)


def _lock_product(cur, product_id: int) -> dict:
    """SELECT ... FOR UPDATE：并发安全，同时返回商品行做存在性与状态校验。"""
    cur.execute(
        "SELECT id, name, price, status FROM product WHERE id = %s FOR UPDATE",
        (product_id,),
    )
    product = cur.fetchone()
    if not product:
        _fail(errors.E_PRODUCT_NOT_FOUND)
    return product


# ---------------------------------------------------------------- 订单
def create_order(user_id: int, items: list) -> dict:
    """创建订单：校验 -> 扣库存 -> 建订单 -> 建明细，全部在同一事务内。"""
    if not items:
        _fail(errors.E_ITEMS_EMPTY)

    with db.transaction() as cur:
        cur.execute("SELECT id FROM `user` WHERE id = %s FOR UPDATE", (user_id,))
        if not cur.fetchone():
            _fail(errors.E_USER_NOT_FOUND)

        # 同一商品可能多次出现，先合并数量
        merged = {}
        for item in items:
            qty = int(item["quantity"])
            if qty <= 0:
                _fail(errors.E_QUANTITY_INVALID)
            merged[item["product_id"]] = merged.get(item["product_id"], 0) + qty

        total = Decimal("0.00")
        details = []
        for product_id, qty in merged.items():
            product = _lock_product(cur, product_id)
            if product["status"] != STATUS_ON_SALE:
                _fail(errors.E_PRODUCT_OFF_SHELF)

            cur.execute(
                "SELECT stock FROM inventory WHERE product_id = %s FOR UPDATE",
                (product_id,),
            )
            row = cur.fetchone()
            if not row:
                _fail(errors.E_STOCK_NOT_FOUND)
            if row["stock"] < qty:
                _fail(errors.E_STOCK_NOT_ENOUGH)

            cur.execute(
                "UPDATE inventory SET stock = stock - %s WHERE product_id = %s",
                (qty, product_id),
            )
            price = Decimal(product["price"])
            subtotal = price * qty
            total += subtotal
            details.append(
                {
                    "product_id": product_id,
                    "quantity": qty,
                    "price": price,
                    "subtotal": subtotal,
                }
            )

        cur.execute(
            "INSERT INTO orders (user_id, total_amount, status) VALUES (%s, %s, %s)",
            (user_id, total, ORDER_PENDING),
        )
        order_id = cur.lastrowid
        for d in details:
            cur.execute(
                "INSERT INTO order_items (order_id, product_id, quantity, price, subtotal) "
                "VALUES (%s, %s, %s, %s, %s)",
                (order_id, d["product_id"], d["quantity"], d["price"], d["subtotal"]),
            )

    return get_order(order_id)


def get_order(order_id: int) -> dict:
    order = db.query_one(
        "SELECT id, user_id, total_amount, status, created_at FROM orders WHERE id = %s",
        (order_id,),
    )
    if not order:
        _fail(errors.E_ORDER_NOT_FOUND)
    items = db.query_all(
        "SELECT oi.product_id, p.name AS product_name, oi.quantity, oi.price, oi.subtotal "
        "FROM order_items oi LEFT JOIN product p ON p.id = oi.product_id "
        "WHERE oi.order_id = %s ORDER BY oi.id",
        (order_id,),
    )
    return {
        "id": order["id"],
        "user_id": order["user_id"],
        "status": order["status"],
        "total_amount": float(order["total_amount"]),
        "created_at": order["created_at"].strftime("%Y-%m-%d %H:%M:%S"),
        "items": [
            {
                "product_id": i["product_id"],
                "product_name": i["product_name"],
                "quantity": i["quantity"],
                "price": float(i["price"]),
                "subtotal": float(i["subtotal"]),
            }
            for i in items
        ],
    }


def cancel_order(order_id: int) -> dict:
    """取消订单并恢复库存。仅 PENDING 可取消；重复取消直接报错，不动库存。"""
    with db.transaction() as cur:
        cur.execute(
            "SELECT id, status FROM orders WHERE id = %s FOR UPDATE", (order_id,)
        )
        order = cur.fetchone()
        if not order:
            _fail(errors.E_ORDER_NOT_FOUND)
        if order["status"] == ORDER_CANCELLED:
            _fail(errors.E_ORDER_ALREADY_CANCELLED)
        if order["status"] != ORDER_PENDING:
            _fail(errors.E_ORDER_STATUS_NOT_CANCELABLE)

        cur.execute(
            "SELECT product_id, quantity FROM order_items WHERE order_id = %s", (order_id,)
        )
        for row in cur.fetchall():
            cur.execute(
                "UPDATE inventory SET stock = stock + %s WHERE product_id = %s",
                (row["quantity"], row["product_id"]),
            )

        cur.execute(
            "UPDATE orders SET status = %s WHERE id = %s", (ORDER_CANCELLED, order_id)
        )

    return get_order(order_id)

