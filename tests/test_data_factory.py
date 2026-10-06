"""Phase 2：测试数据工厂接入验证。

验证点：
  1. 用户 / 商品 / 库存数据可自动生成并正确落库关联
  2. 生成的数据可直接用于订单业务流程（下单 / 查单 / 取消）
  3. 每批数据有唯一 batch_id，可按批次查询与精确清理
  4. 清理后数据库无残留，且不误删其他批次数据
"""
import os

from order_system import db
from order_system.tests.data_factory.order_data_factory import OrderDataFactory


def stock_of(product_id):
    return db.query_one(
        "SELECT stock FROM inventory WHERE product_id = %s", (product_id,)
    )["stock"]


# ------------------------------------------------------------ 生成 + 关联
def test_auto_generated_user_and_product(client, data_factory):
    """用户 / 商品 / 库存自动生成，且与业务表正确关联。"""
    user = data_factory.create_user()
    product = data_factory.create_product()

    # 生成的用户名带前缀，密码非空
    assert user["username"].startswith("test_")
    assert user["password"]

    # 落库校验：user 表
    row = db.query_one(
        "SELECT username FROM `user` WHERE id = %s", (user["id"],)
    )
    assert row["username"] == user["username"]

    # 落库校验：product + inventory 通过 product_id 关联
    row = db.query_one(
        "SELECT name, price, status FROM product WHERE id = %s", (product["id"],)
    )
    assert row["name"] == product["name"]
    assert float(row["price"]) == product["price"]
    assert row["status"] in ("ON_SALE", "OFF_SHELF")
    assert stock_of(product["id"]) >= 0

    # 批次档案里能看到本批生成的对象
    archive = OrderDataFactory.load_batch(data_factory.batch_id)
    assert user["id"] in archive["user_ids"]
    assert product["id"] in archive["product_ids"]


# ------------------------------------------------------------ 正常订单流程
def test_auto_data_order_flow(client, data_factory):
    """自动造数 → 下单 → 库存扣减 → 查单 → 取消 → 库存恢复。"""
    user = data_factory.create_user()
    product = data_factory.create_product(price=99.90, stock=10, status="ON_SALE")

    body = data_factory.place_order(
        user["id"], [{"product_id": product["id"], "quantity": 3}]
    )
    assert body["code"] == 0
    order = body["data"]
    assert order["total_amount"] == 299.70
    assert stock_of(product["id"]) == 7

    # 查询订单：明细与生成的商品正确关联
    r = client.get(f"/api/orders/{order['id']}")
    data = r.json()["data"]
    assert data["user_id"] == user["id"]
    assert data["items"][0]["product_id"] == product["id"]
    assert data["items"][0]["product_name"] == product["name"]
    assert data["items"][0]["quantity"] == 3

    # 取消订单并恢复库存
    r = client.post(f"/api/orders/{order['id']}/cancel")
    assert r.json()["data"]["status"] == "CANCELLED"
    assert stock_of(product["id"]) == 10


# ------------------------------------------------------------ 异常场景
def test_auto_generated_stock_not_enough(data_factory):
    """自动生成库存=3，购买 5 → 订单失败，库存保持 3。"""
    user = data_factory.create_user()
    product = data_factory.create_product(stock=3, status="ON_SALE")
    assert stock_of(product["id"]) == 3

    body = data_factory.place_order(
        user["id"], [{"product_id": product["id"], "quantity": 5}]
    )
    assert body["code"] == 3002
    assert body["message"] == "库存不足"
    assert stock_of(product["id"]) == 3          # 库存不变
    assert db.query_one(
        "SELECT COUNT(*) c FROM orders WHERE user_id = %s", (user["id"],)
    )["c"] == 0                                   # 没有半成品订单


def test_auto_generated_zero_stock(data_factory):
    """自动生成零库存商品 → 下单失败，库存仍为 0。"""
    user = data_factory.create_user()
    product = data_factory.create_product(stock=0, status="ON_SALE")
    body = data_factory.place_order(
        user["id"], [{"product_id": product["id"], "quantity": 1}]
    )
    assert body["code"] == 3002
    assert stock_of(product["id"]) == 0


def test_auto_generated_off_shelf_product(data_factory):
    """自动生成下架商品 → 下单失败，库存不变。"""
    user = data_factory.create_user()
    product = data_factory.create_product(status="OFF_SHELF", stock=10)
    body = data_factory.place_order(
        user["id"], [{"product_id": product["id"], "quantity": 1}]
    )
    assert body["code"] == 2002
    assert body["message"] == "商品已下架，不可购买"
    assert stock_of(product["id"]) == 10


def test_auto_generated_invalid_quantity(data_factory):
    """边界值：数量 0 / 负数 由数据工厂造出的商品配合校验拒绝。"""
    user = data_factory.create_user()
    product = data_factory.create_product(stock=5, status="ON_SALE")
    for qty in (0, -1):
        body = data_factory.place_order(
            user["id"], [{"product_id": product["id"], "quantity": qty}]
        )
        assert body["code"] == 3003
    assert stock_of(product["id"]) == 5
# ------------------------------------------------------------ 批次与清理
def test_batch_id_unique_and_queryable(client, data_factory):
    """每批数据有唯一 batch_id，可按 batch_id 查询本批数据。"""
    f2 = OrderDataFactory(client)
    try:
        assert f2.batch_id != data_factory.batch_id
        assert os.path.exists(data_factory.archive_path)

        user = data_factory.create_user()
        archive = OrderDataFactory.load_batch(data_factory.batch_id)
        assert archive["batch_id"] == data_factory.batch_id
        assert user["id"] in archive["user_ids"]
        assert archive["cleaned"] is False
    finally:
        f2.cleanup()


def test_cleanup_removes_all_batch_data(client, data_factory):
    """清理：本批次数据全部删除，库里无残留。"""
    user = data_factory.create_user()
    product = data_factory.create_product(stock=8, status="ON_SALE")
    body = data_factory.place_order(
        user["id"], [{"product_id": product["id"], "quantity": 2}]
    )
    order_id = body["data"]["id"]
    assert stock_of(product["id"]) == 6

    report = data_factory.cleanup()
    assert report["orders"] == 1
    assert report["order_items"] == 1
    assert report["product"] == 1
    assert report["user"] == 1

    # 直接查库确认删除
    assert db.query_one("SELECT id FROM `user` WHERE id = %s", (user["id"],)) is None
    assert db.query_one("SELECT id FROM product WHERE id = %s", (product["id"],)) is None
    assert db.query_one(
        "SELECT product_id FROM inventory WHERE product_id = %s", (product["id"],)
    ) is None
    assert db.query_one("SELECT id FROM orders WHERE id = %s", (order_id,)) is None
    assert db.query_one(
        "SELECT id FROM order_items WHERE order_id = %s", (order_id,)
    ) is None

    # 残留核对全部为 0
    assert data_factory.remaining() == {
        "user": 0, "product": 0, "inventory": 0, "orders": 0,
    }

    # 档案记录清理结果，且重复清理幂等（不会二次删除）
    archive = OrderDataFactory.load_batch(data_factory.batch_id)
    assert archive["cleaned"] is True
    assert data_factory.cleanup() == report


def test_cleanup_does_not_touch_other_batch(client, data_factory):
    """批次隔离：清理一个批次不影响另一批次的数据。"""
    other = OrderDataFactory(client)
    try:
        kept_user = other.create_user()
        kept_product = other.create_product(stock=5)

        data_factory.create_user()
        data_factory.create_product(stock=5)
        data_factory.cleanup()

        # 另一批次数据完好
        assert db.query_one(
            "SELECT id FROM `user` WHERE id = %s", (kept_user["id"],)
        ) is not None
        assert stock_of(kept_product["id"]) == 5
    finally:
        other.cleanup()