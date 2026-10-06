"""Phase 3：用 AeroTest 执行订单业务 YAML 用例。

组成：
    用例   order_system/testcases/order/*.yaml     业务语义命名，接口断言 + 数据库断言
    框架   AeroTest（项目2）core：用例加载/静态校验、请求引擎、断言引擎、allure 步骤
    数据   Phase 2 数据工厂（tests/data_factory），按批次准备与清理
    环境   tests/aerotest/config/envs/order_system.yaml（被测服务地址 + 业务库）

执行（需先启动被测服务：uvicorn order_system.main:app --port 8000）：
    python -m pytest order_system/tests -m suite -v
    python -m pytest order_system/tests -m suite -v --alluredir=order_system/reports/allure-results
"""
import os
import pathlib

import pytest

# 先导入接入层：内部会把 AeroTest（项目2）加入 import 路径
from order_system.tests.aerotest import (  # noqa: E402
    CASE_DIR,
    CONFIG_DIR,
    ENV_CONFIG_PATH,
    ENV_NAME,
)
from order_system.tests.aerotest.provider import OrderDataProvider  # noqa: E402

from core.case_loader import load_case_with_params  # noqa: E402  AeroTest 用例加载
from core.config import load_env_config  # noqa: E402
from core.context import Context  # noqa: E402
from core.http_client import HttpClient  # noqa: E402
from core.runner import run_case  # noqa: E402

pytestmark = pytest.mark.suite

# 收集期加载（AeroTest 的加载器会做静态校验：method/断言类型/占位符来源）
CASES: list = []
for _path in sorted(pathlib.Path(CASE_DIR).glob("*.yaml")):
    CASES.extend(load_case_with_params(str(_path)))

if not CASES:
    pytest.skip(f"未找到 YAML 用例: {CASE_DIR}", allow_module_level=True)


# ---------------------------------------------------------------- fixtures
@pytest.fixture(scope="session")
def aerotest_env_config():
    """AeroTest 环境配置；并把 db 配置告知框架内置 db_eq 断言（AEROTEST_DB_CONFIG）。"""
    os.environ.setdefault("AEROTEST_DB_CONFIG", ENV_CONFIG_PATH)
    return load_env_config(ENV_NAME, CONFIG_DIR)


@pytest.fixture(scope="session", autouse=True)
def point_db_to_business_db(aerotest_env_config):
    """把进程内 db 指向环境配置里的业务库。

    tests/conftest.py 的 prepare_db 是 session autouse，会把进程内 db 指向
    order_system_test（供 Phase 1/2 的 TestClient 使用）。但 Phase 3 走真实 HTTP 服务，
    服务连的是业务库；数据工厂清理必须落在同一个库，否则主库会残留测试数据。
    """
    from order_system import db as order_db

    business_db = (aerotest_env_config.get("db") or {}).get("database")
    if business_db:
        order_db.DB_NAME = business_db
    yield


@pytest.fixture(scope="session")
def aerotest_client(aerotest_env_config):
    """AeroTest 请求引擎（复用其超时/重试/日志/多环境能力）。"""
    return HttpClient(cfg=aerotest_env_config)


@pytest.fixture
def aerotest_ctx():
    """function 级变量池：每条用例独立，互不串扰。"""
    return Context()


@pytest.fixture
def aerotest_provider(aerotest_client):
    """造数钩子：复用 Phase 2 数据工厂，按批次准备数据、按批次精确清理。"""
    provider = OrderDataProvider(aerotest_client)
    yield provider
    # 兜底：runner 走正常 teardown 时这里无事可做；
    # setup 中途失败（批次号没返回给 runner）时，由这里补齐清理
    provider.cleanup_all()


# ---------------------------------------------------------------- 执行
@pytest.mark.parametrize("yaml_case", CASES, ids=[c.name for c in CASES])
def test_order_api_case(yaml_case, aerotest_client, aerotest_ctx, aerotest_provider):
    """通用执行器：跑通「造数 → 请求 → 接口断言 → 数据库断言 → 清理」闭环。"""
    run_case(yaml_case, aerotest_client, aerotest_ctx, aerotest_provider)