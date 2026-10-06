"""端到端手工验证脚本：真实启动服务后跑核心流程 + 数据库核对。"""
import os
import sys

import requests

BASE = os.getenv("BASE_URL", "http://127.0.0.1:8000")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from order_system import db  # noqa: E402


def show(title, resp):
    print(f"--- {title}: HTTP {resp.status_code} {resp.text}")


def stock_in_db(pid):
    return db.query_one("SELECT stock FROM inventory WHERE product_id=%s", (pid,))["stock"]


def main():
    print("=== 1. 初始化主库 ===")
    from order_system.init_db import init_schema, seed_products
    init_schema()
    seed_products()
    db.DB_NAME = "order_system"

    print("=== 2. 创建用户 ===")
    r = requests.post(f"{BASE}/api/users", json={"username": "e2e_user", "password": "pwd"})
    show("create user", r)
    uid = r.json()["data"]["id"] or r.json()["data"]["id"]

    print("=== 3. 准备商品和库存 ===")
    r = requests.post(f"{BASE}/api/products/setup",
                      json={"name": "E2E商品", "price": "59.90", "stock": 20, "status": "ON_SALE"})
    show("setup product", r)
    pid = r.json()["data"]["id"]

    r = requests.post(f"{BASE}/api/products/setup",
                      json={"name": "E2E下架品", "price": "10.00", "stock": 5, "status": "OFF_SHELF"})
    off_pid = r.json()["data"]["id"]

    r = requests.get(f"{BASE}/api/inventory/{pid}")
    show("inventory before order", r)

    print("=== 4. 创建订单（买 3 件）===")
    r = requests.post(f"{BASE}/api/orders",
                      json={"user_id": uid, "items": [{"product_id": pid, "quantity": 3}]})
    show("create order", r)
    order = r.json()["data"]
    print("   total_amount =", order["total_amount"], "(期望 179.70)")
    print("   DB 库存 =", stock_in_db(pid), "(期望 17)")

    print("=== 5. 查询订单 ===")
    r = requests.get(f"{BASE}/api/orders/{order['id']}")
    show("get order", r)

    print("=== 6. 异常场景 ===")
    cases = [
        ("库存不足", {"user_id": uid, "items": [{"product_id": pid, "quantity": 999}]}),
        ("数量为0", {"user_id": uid, "items": [{"product_id": pid, "quantity": 0}]}),
        ("数量为负", {"user_id": uid, "items": [{"product_id": pid, "quantity": -5}]}),
        ("商品不存在", {"user_id": uid, "items": [{"product_id": 99999999, "quantity": 1}]}),
        ("商品下架", {"user_id": uid, "items": [{"product_id": off_pid, "quantity": 1}]}),
        ("用户不存在", {"user_id": 99999999, "items": [{"product_id": pid, "quantity": 1}]}),
    ]
    for name, payload in cases:
        r = requests.post(f"{BASE}/api/orders", json=payload)
        print(f"--- {name}: {r.json()}")
    print("   异常后 DB 库存 =", stock_in_db(pid), "(期望仍为 17)")

    print("=== 7. 取消订单 ===")
    r = requests.post(f"{BASE}/api/orders/{order['id']}/cancel")
    show("cancel order", r)
    print("   恢复后 DB 库存 =", stock_in_db(pid), "(期望 20)")

    print("=== 8. 重复取消 ===")
    r = requests.post(f"{BASE}/api/orders/{order['id']}/cancel")
    print("--- 重复取消:", r.json())
    print("   DB 库存 =", stock_in_db(pid), "(期望仍为 20，不能被二次恢复)")

    print("=== 9. 商品列表/详情 ===")
    r = requests.get(f"{BASE}/api/products")
    print("--- 商品数量:", len(r.json()["data"]))
    r = requests.get(f"{BASE}/api/products/{pid}")
    print("--- 商品详情:", r.json()["data"])

    print("\n=== E2E 验证结束 ===")


if __name__ == "__main__":
    main()
