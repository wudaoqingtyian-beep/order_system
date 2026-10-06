"""订单测试数据工厂适配层：数据生成 → 落库 → 批次档案 → 精确清理。

生命周期：
    OrderDataFactory(client)     创建批次（batch_id）
      .create_user()             自动生成用户数据并落库
      .create_product()          自动生成商品 + 库存并落库
      .place_order()             下单，并登记本批次产生的订单
      .cancel_order()            取消订单（用于构造「已取消」前置状态）
      .cleanup()                 按批次精确删除本批次数据
      .remaining()               查询本批次残留数量（清理后应为 0）

为什么不在表里加标记字段：
    order_system 表结构本阶段不允许改动，因此批次信息记录在档案文件里，
    清理时按主键精确删除（比按标记字段全表删除更精确，不会误删其他批次数据）。
"""
import json
import os
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(HERE)
PROJECT_ROOT = os.path.dirname(TESTS_DIR)
WORKSPACE = os.path.dirname(PROJECT_ROOT)
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

from order_system import db  # noqa: E402
from . import factory_bridge  # noqa: E402

BATCH_DIR = os.path.join(TESTS_DIR, ".batches")


class DataFactoryError(Exception):
    """造数/清理过程中的问题，直接抛出便于测试定位。"""


class OrderDataFactory:
    """面向 order_system 的测试数据工厂（每实例 = 一个批次）。"""

    def __init__(self, client, prefix="test_order"):
        self.client = client
        self.batch_id = f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"
        self.created_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self.user_ids = []
        self.product_ids = []
        self.order_ids = []
        self.cleaned = False
        self.cleanup_report = {}
        os.makedirs(BATCH_DIR, exist_ok=True)
        self._persist()

    # ------------------------------------------------------------ 档案
    @property
    def archive_path(self):
        return os.path.join(BATCH_DIR, f"{self.batch_id}.json")

    def snapshot(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "created_at": self.created_at,
            "user_ids": self.user_ids,
            "product_ids": self.product_ids,
            "order_ids": self.order_ids,
            "cleaned": self.cleaned,
            "cleanup_report": self.cleanup_report,
        }

    def _persist(self):
        with open(self.archive_path, "w", encoding="utf-8") as f:
            json.dump(self.snapshot(), f, ensure_ascii=False, indent=2)

    @staticmethod
    def load_batch(batch_id) -> dict:
        """按 batch_id 查询本次生成的数据（档案）。"""
        path = os.path.join(BATCH_DIR, f"{batch_id}.json")
        if not os.path.exists(path):
            raise DataFactoryError(f"批次档案不存在: {batch_id}")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    # ------------------------------------------------------------ 造数
    def _call(self, method, url, **kw):
        resp = getattr(self.client, method)(url, **kw)
        body = resp.json()
        if body.get("code") != 0:
            raise DataFactoryError(f"{method.upper()} {url} 失败: {body}")
        return body["data"]

    def create_user(self, username=None, password=None) -> dict:
        """生成并创建一个用户（username/password 不传则由数据工厂随机生成）。"""
        row = factory_bridge.generate_rows("order_system", model="user", count=1)["user"][0]
        data = self._call(
            "post", "/api/users",
            json={
                "username": username or row["username"],
                "password": password or row["password"],
            },
        )
        self.user_ids.append(data["id"])
        self._persist()
        data["password"] = password or row["password"]
        return data

    def create_product(self, price=None, stock=None, status=None, name=None) -> dict:
        """生成并创建一个商品 + 库存。

        随机值来自数据工厂；传参可精确覆盖，用于构造指定场景：
          stock=3            库存不足场景
          stock=0            零库存场景
          status="OFF_SHELF" 下架商品场景
        不传 status 时使用数据工厂随机生成的状态（用于验证"数据可自动生成"）。
        """
        row = factory_bridge.generate_rows("order_system", model="product", count=1)["product"][0]
        data = self._call(
            "post", "/api/products/setup",
            json={
                "name": name or row["name"],
                "price": str(price if price is not None else row["price"]),
                "stock": stock if stock is not None else row["stock"],
                "status": status or row["status"],
            },
        )
        self.product_ids.append(data["id"])
        self._persist()
        return data

    def place_order(self, user_id, items):
        """下单并登记订单号；下单失败时返回错误响应（不抛异常，由测试断言）。"""
        resp = self.client.post("/api/orders", json={"user_id": user_id, "items": items})
        body = resp.json()
        if body.get("code") == 0:
            self.order_ids.append(body["data"]["id"])
            self._persist()
        return body

    def cancel_order(self, order_id):
        """取消订单（造数用：构造「已取消订单」前置状态，供重复取消等场景使用）。"""
        return self._call("post", f"/api/orders/{order_id}/cancel")

    # ------------------------------------------------------------ 清理
    def cleanup(self) -> dict:
        """按批次精确清理：订单明细 → 订单 → 库存 → 商品 → 用户（逆外键顺序）。"""
        if self.cleaned:
            return self.cleanup_report

        report = {}
        user_ids = tuple(self.user_ids)
        product_ids = tuple(self.product_ids)

        with db.transaction() as cur:
            # 本批次用户产生的全部订单（含测试过程中创建但未登记的）
            order_ids = set(self.order_ids)
            if user_ids:
                cur.execute("SELECT id FROM orders WHERE user_id IN %s", (user_ids,))
                order_ids |= {r["id"] for r in cur.fetchall()}

            if order_ids:
                ids = tuple(order_ids)
                cur.execute("DELETE FROM order_items WHERE order_id IN %s", (ids,))
                report["order_items"] = cur.rowcount
                cur.execute("DELETE FROM orders WHERE id IN %s", (ids,))
                report["orders"] = cur.rowcount
            if product_ids:
                cur.execute("DELETE FROM inventory WHERE product_id IN %s", (product_ids,))
                report["inventory"] = cur.rowcount
                cur.execute("DELETE FROM product WHERE id IN %s", (product_ids,))
                report["product"] = cur.rowcount
            if user_ids:
                cur.execute("DELETE FROM `user` WHERE id IN %s", (user_ids,))
                report["user"] = cur.rowcount

        self.cleaned = True
        self.cleanup_report = report
        self._persist()
        return report

    # ------------------------------------------------------------ 核对
    def remaining(self) -> dict:
        """查询本批次数据在库里的残留条数（应全部为 0）。"""
        with db.get_conn() as conn:
            counts = {}
            for label, sql, args in (
                ("user", "SELECT COUNT(*) c FROM `user` WHERE id IN %s",
                 (tuple(self.user_ids) or (0,),)),
                ("product", "SELECT COUNT(*) c FROM product WHERE id IN %s",
                 (tuple(self.product_ids) or (0,),)),
                ("inventory", "SELECT COUNT(*) c FROM inventory WHERE product_id IN %s",
                 (tuple(self.product_ids) or (0,),)),
                ("orders", "SELECT COUNT(*) c FROM orders WHERE id IN %s",
                 (tuple(self.order_ids) or (0,),)),
            ):
                counts[label] = db.query_one(sql, args, conn)["c"]
        return counts