"""pytest 公共 fixture：真实 MySQL + TestClient + 数据工厂自动造数。

测试库使用 order_system_test，每个测试 session 开始时重建，
表结构与 schema.sql 一致（CREATE TABLE 语句共用）。
"""
import os
import shutil
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from order_system import db, main  # noqa: E402
from order_system.init_db import split_sql  # noqa: E402
from order_system.tests.data_factory import factory_bridge  # noqa: E402
from order_system.tests.data_factory.order_data_factory import (  # noqa: E402
    BATCH_DIR,
    OrderDataFactory,
)

TEST_DB = os.getenv("TEST_DB_NAME", "order_system_test")
SCHEMA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql"
)


def _rebuild_test_db():
    sql_text = open(SCHEMA_FILE, encoding="utf-8").read()
    conn = db.connect(with_db=False, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
            for stmt in split_sql(sql_text):
                stmt = stmt.replace("order_system", TEST_DB)
                cur.execute(stmt)
    finally:
        conn.close()


@pytest.fixture(scope="session", autouse=True)
def prepare_db():
    _rebuild_test_db()
    # 让应用层连接指向测试库
    db.DB_NAME = TEST_DB
    main.service.db.DB_NAME = TEST_DB
    yield


@pytest.fixture(scope="session")
def client(prepare_db):
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def make_user(client):
    def _make(username=None):
        username = username or f"u{os.urandom(4).hex()}"
        r = client.post("/api/users", json={"username": username, "password": "pwd123"})
        assert r.status_code == 200 and r.json()["code"] == 0
        return r.json()["data"]["id"]
    return _make


@pytest.fixture
def make_product(client):
    """创建商品并设置库存，返回 (product_id, price, stock)。"""
    def _make(price=100.00, stock=10, status="ON_SALE"):
        r = client.post("/api/products/setup",
                        json={"price": str(price), "stock": stock, "status": status})
        assert r.status_code == 200, r.text
        return r.json()["data"]
    return _make


# ---------------------------------------------------------------- 测试数据工厂接入
@pytest.fixture(scope="session", autouse=True)
def clean_factory_artifacts():
    """会话开始清空上一轮遗留的批次档案与工厂临时导出，避免长期累积。"""
    shutil.rmtree(BATCH_DIR, ignore_errors=True)
    factory_bridge.clear_output_dir()
    os.makedirs(BATCH_DIR, exist_ok=True)
    yield
    factory_bridge.clear_output_dir()


@pytest.fixture
def data_factory(client):
    """自动造数 fixture：测试结束自动按批次清理，并断言库里无残留。"""
    factory = OrderDataFactory(client)
    yield factory
    factory.cleanup()
    remaining = factory.remaining()
    assert all(v == 0 for v in remaining.values()), (
        f"批次 {factory.batch_id} 清理后仍有残留: {remaining}"
    )
