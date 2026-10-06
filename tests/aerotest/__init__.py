"""AeroTest 接入层（Phase 3）。

把接口自动化测试框架 AeroTest（项目2）接到订单系统上，只做「桥接」：
  - provider.py   AeroTest 造数钩子 → 复用 Phase 2 数据工厂准备/清理订单业务数据
  - config/       AeroTest 环境配置（被测服务地址 + 业务库连接，供 db_eq 断言）
  - 用例           order_system/testcases/order/*.yaml（业务语义命名）

框架本身（YAML 加载、请求、断言、报告）来自 项目2/core，不做任何复制。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(HERE)
PROJECT_ROOT = os.path.dirname(TESTS_DIR)
WORKSPACE = os.path.dirname(PROJECT_ROOT)

AERO_HOME = os.path.join(WORKSPACE, "项目2")          # AeroTest 仓库位置
ENV_NAME = "order_system"                             # 环境配置名
CONFIG_DIR = os.path.join(HERE, "config")             # AeroTest 配置目录（--config-dir）
ENV_CONFIG_PATH = os.path.join(CONFIG_DIR, "envs", f"{ENV_NAME}.yaml")
CASE_DIR = os.path.join(PROJECT_ROOT, "testcases", "order")


def ensure_aerotest_on_path():
    """把 AeroTest 与工作区根目录加入 import 路径（复用 core，不复制）。"""
    for path in (AERO_HOME, WORKSPACE):
        if path not in sys.path:
            sys.path.insert(0, path)


ensure_aerotest_on_path()

# 框架（项目2）与数据工厂（项目1）的 core 包同名，先合并命名空间再导入任何 core
from order_system.tests.data_factory.factory_bridge import FACTORY_HOME  # noqa: E402
from .framework import merge_core_namespaces  # noqa: E402

merge_core_namespaces(AERO_HOME, FACTORY_HOME)

from .provider import OrderDataProvider  # noqa: E402

__all__ = ["OrderDataProvider", "ensure_aerotest_on_path",
           "AERO_HOME", "ENV_NAME", "CONFIG_DIR", "ENV_CONFIG_PATH", "CASE_DIR"]
