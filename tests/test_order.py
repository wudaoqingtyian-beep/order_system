"""订单核心业务测试：正常流程 + 异常场景 + 数据库一致性。"""
import pytest

from order_system import db


def order_body(user_id, product_id, quantity):
    return {"user_id": user_id, "items": [{"product_id": product_id, "quantity": quantity}]}


# ------------------------------------------------------------ 正常流程
def test_create_order_success_and_stock_deducted(client, make_user, make_product):
    uid = make_user()
    p = make_product(price=100.00, stock=10)

    r = client.post("/api/orders", json=order_body(uid, p["id"], 3))
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    order = body["data"]
    assert order["status"] == "PENDING"
    assert order["total_amount"] == 300.00
    assert len(order["items"]) == 1
    assert order["items"][0]["quantity"] == 3
    assert order["items"][0]["subtotal"] == 300.00

    # 接口查库存
    r = client.get(f"/api/inventory/{p['id']}")
    assert r.json()["data"]["stock"] == 7

    # 直接查数据库校验扣减
    row = db.query_one("SELECT stock FROM inventory WHERE product_id = %s", (p["id"],))
    assert row["stock"] == 7
    o = db.query_one("SELECT total_amount, status FROM orders WHERE id = %s", (order["id"],))
    assert float(o["total_amount"]) == 300.00
    assert o["status"] == "PENDING"
    assert db.query_one(
        "SELECT COUNT(*) c FROM order_items WHERE order_id = %s", (order["id"],)
    )["c"] == 1


def test_order_amount_calculation_multi_items(client, make_user, make_product):
    uid = make_user()
    p1 = make_product(price=19.99, stock=10)
    p2 = make_product(price=100.00, stock=10)

    r = client.post("/api/orders", json={
        "user_id": uid,
        "items": [
            {"product_id": p1["id"], "quantity": 3},
            {"product_id": p2["id"], "quantity": 2},
        ],
    })
    order = r.json()["data"]
    # 19.99*3 + 100*2 = 259.97
    assert order["total_amount"] == 259.97
    assert sum(i["subtotal"] for i in order["items"]) == 259.97


def test_query_order_detail(client, make_user, make_product):
    uid = make_user()
    p = make_product(price=50.00, stock=10)
    order = client.post("/api/orders", json=order_body(uid, p["id"], 2)).json()["data"]

    r = client.get(f"/api/orders/{order['id']}")
    data = r.json()["data"]
    assert data["user_id"] == uid
    assert data["items"][0]["price"] == 50.00
    assert data["items"][0]["quantity"] == 2
    assert data["items"][0]["subtotal"] == 100.00
    assert data["total_amount"] == 100.00


# ------------------------------------------------------------ 异常场景
def test_stock_not_enough_rejected_and_stock_unchanged(client, make_user, make_product):
    uid = make_user()
    p = make_product(price=10.00, stock=5)
    r = client.post("/api/orders", json=order_body(uid, p["id"], 6))
    assert r.json()["code"] == 3002
    assert "库存不足" in r.json()["message"]
    # 库存不变
    assert db.query_one(
        "SELECT stock FROM inventory WHERE product_id = %s", (p["id"],)
    )["stock"] == 5


@pytest.mark.parametrize("qty", [0, -1, -100])
def test_invalid_quantity_rejected(client, make_user, make_product, qty):
    uid = make_user()
    p = make_product(price=10.00, stock=5)
    r = client.post("/api/orders", json=order_body(uid, p["id"], qty))
    assert r.json()["code"] == 3003
    assert db.query_one(
        "SELECT stock FROM inventory WHERE product_id = %s", (p["id"],)
    )["stock"] == 5


def test_product_not_found(client, make_user):
    uid = make_user()
    r = client.post("/api/orders", json=order_body(uid, 99999999, 1))
    assert r.json()["code"] == 2001
    assert "商品不存在" in r.json()["message"]


def test_product_off_shelf_rejected(client, make_user, make_product):
    uid = make_user()
    p = make_product(price=10.00, stock=5, status="OFF_SHELF")
    r = client.post("/api/orders", json=order_body(uid, p["id"], 1))
    assert r.json()["code"] == 2002
    assert "下架" in r.json()["message"]
    assert db.query_one(
        "SELECT stock FROM inventory WHERE product_id = %s", (p["id"],)
    )["stock"] == 5


def test_user_not_found(client, make_product):
    p = make_product(price=10.00, stock=5)
    r = client.post("/api/orders", json=order_body(99999999, p["id"], 1))
    assert r.json()["code"] == 1001
    assert db.query_one(
        "SELECT stock FROM inventory WHERE product_id = %s", (p["id"],)
    )["stock"] == 5




def test_multi_item_partial_failure_rolls_back(client, make_user, make_product):
    """第二个商品库存不足时，第一个商品的扣减必须整体回滚。"""
    uid = make_user()
    p1 = make_product(price=10.00, stock=10)
    p2 = make_product(price=10.00, stock=1)
    before = db.query_one("SELECT COUNT(*) c FROM orders")["c"]
    r = client.post("/api/orders", json={
        "user_id": uid,
        "items": [
            {"product_id": p1["id"], "quantity": 2},
            {"product_id": p2["id"], "quantity": 9},
        ],
    })
    assert r.json()["code"] == 3002
    # 事务回滚：p1 库存没有被动过，且没有订单落库
    assert db.query_one(
        "SELECT stock FROM inventory WHERE product_id = %s", (p1["id"],)
    )["stock"] == 10
    assert db.query_one("SELECT COUNT(*) c FROM orders")["c"] == before


# ------------------------------------------------------------ 取消订单
def test_cancel_order_restores_stock(client, make_user, make_product):
    uid = make_user()
    p = make_product(price=80.00, stock=10)
    order = client.post("/api/orders", json=order_body(uid, p["id"], 4)).json()["data"]
    assert db.query_one(
        "SELECT stock FROM inventory WHERE product_id = %s", (p["id"],)
    )["stock"] == 6

    r = client.post(f"/api/orders/{order['id']}/cancel")
    assert r.json()["data"]["status"] == "CANCELLED"
    # 接口 + 数据库双重确认库存恢复
    assert client.get(f"/api/inventory/{p['id']}").json()["data"]["stock"] == 10
    assert db.query_one(
        "SELECT stock FROM inventory WHERE product_id = %s", (p["id"],)
    )["stock"] == 10
    assert db.query_one(
        "SELECT status FROM orders WHERE id = %s", (order["id"],)
    )["status"] == "CANCELLED"


def test_cancel_twice_does_not_restore_stock_again(client, make_user, make_product):
    uid = make_user()
    p = make_product(price=30.00, stock=10)
    order = client.post("/api/orders", json=order_body(uid, p["id"], 2)).json()["data"]
    client.post(f"/api/orders/{order['id']}/cancel")
    assert db.query_one(
        "SELECT stock FROM inventory WHERE product_id = %s", (p["id"],)
    )["stock"] == 10

    r = client.post(f"/api/orders/{order['id']}/cancel")
    assert r.json()["code"] == 4002
    assert "已取消" in r.json()["message"]
    # 库存没有被二次恢复
    assert db.query_one(
        "SELECT stock FROM inventory WHERE product_id = %s", (p["id"],)
    )["stock"] == 10


def test_cancel_not_found_order(client):
    r = client.post("/api/orders/99999999/cancel")
    assert r.json()["code"] == 4001


# ------------------------------------------------------------ 商品/库存/用户
def test_list_and_get_product(client, make_product):
    p = make_product(price=12.34, stock=3)
    r = client.get("/api/products")
    ids = [i["id"] for i in r.json()["data"]]
    assert p["id"] in ids

    r = client.get(f"/api/products/{p['id']}")
    assert r.json()["data"]["price"] == 12.34
    assert r.json()["data"]["status"] == "ON_SALE"

    r = client.get("/api/products/99999999")
    assert r.json()["code"] == 2001


def test_get_inventory(client, make_product):
    p = make_product(price=1.00, stock=42)
    r = client.get(f"/api/inventory/{p['id']}")
    assert r.json()["data"]["stock"] == 42
    r = client.get("/api/inventory/99999999")
    assert r.json()["code"] == 2001


def test_create_user(client):
    r = client.post("/api/users", json={"username": "unique_user_1", "password": "p"})
    assert r.json()["code"] == 0
    assert r.json()["data"]["id"] > 0
    r = client.post("/api/users", json={"username": "unique_user_1", "password": "p"})
    assert r.json()["code"] == 1002

def test_order_not_found(client):
    r = client.get("/api/orders/99999999")
    assert r.json()["code"] == 4001
