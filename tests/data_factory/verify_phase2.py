"""Phase 2 端到端验证：真实服务 + 真实 MySQL 上跑「造数 → 下单 → 清理」。

前置：先启动服务
    python -m uvicorn order_system.main:app --host 127.0.0.1 --port 8000
运行：
    python order_system/tests/data_factory/verify_phase2.py
"""
import os
import sys

import requests

BASE = os.getenv("BASE_URL", "http://127.0.0.1:8000")
HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, WORKSPACE)

from order_system import db  # noqa: E402
from order_system.tests.data_factory.order_data_factory import OrderDataFactory  # noqa: E402


class Http:
    """把 requests 包装成适配层需要的 client（相对路径 + BASE_URL）。"""

    def post(self, url, **kw):
        return requests.post(BASE + url, **kw)

    def get(self, url, **kw):
        return requests.get(BASE + url, **kw)


def counts():
    """主库全局计数，用于证明清理后回到基线。"""
    return {
        t: db.query_one(f"SELECT COUNT(*) c FROM `{t}`")["c"]
        for t in ("user", "product", "inventory", "orders", "order_items")
    }


def stock_of(pid):
    return db.query_one("SELECT stock FROM inventory WHERE product_id=%s", (pid,))["stock"]


def main():
    baseline = counts()
    print(f"=== 0. 基线计数: {baseline} ===")

    factory = OrderDataFactory(Http())
    print(f"=== 1. 创建批次 batch_id = {factory.batch_id} ===")

    user = factory.create_user()
    print(f"    自动生成用户: id={user['id']} username={user['username']}")

    product = factory.create_product(price=99.90, stock=10, status="ON_SALE")
    print(f"    自动生成商品: id={product['id']} name={product['name']} "
          f"price={product['price']} stock={product['stock']}")
    print(f"    DB 库存 = {stock_of(product['id'])}")

    print("=== 2. 创建订单（买 3 件）===")
    body = factory.place_order(user["id"], [{"product_id": product["id"], "quantity": 3}])
    print(f"    {body}")
    order = body["data"]
    print(f"    金额 = {order['total_amount']} (期望 299.7)")
    print(f"    DB 库存 = {stock_of(product['id'])} (期望 7)")

    print("=== 3. 查询订单 ===")
    r = requests.get(f"{BASE}/api/orders/{order['id']}")
    print(f"    {r.json()['data']}")

    print("=== 4. 异常场景（自动生成库存=3，买 5）===")
    p2 = factory.create_product(stock=3, status="ON_SALE")
    bad = factory.place_order(user["id"], [{"product_id": p2["id"], "quantity": 5}])
    print(f"    {bad}")
    print(f"    DB 库存 = {stock_of(p2['id'])} (期望仍为 3)")

    print("=== 5. 取消订单 ===")
    r = requests.post(f"{BASE}/api/orders/{order['id']}/cancel")
    print(f"    {r.json()['data']['status']}")
    print(f"    DB 库存 = {stock_of(product['id'])} (期望 10)")

    print("=== 6. 清理本批次数据 ===")
    report = factory.cleanup()
    print(f"    删除统计: {report}")
    print(f"    库内残留: {factory.remaining()}")

    after = counts()
    print(f"=== 7. 清理后计数: {after} ===")
    print(f"    是否回到基线: {after == baseline}")

    archive = OrderDataFactory.load_batch(factory.batch_id)
    print(f"=== 8. 批次档案可查: cleaned={archive['cleaned']} "
          f"users={archive['user_ids']} products={archive['product_ids']} ===")

    print("\n=== Phase 2 验证结束 ===")


if __name__ == "__main__":
    main()