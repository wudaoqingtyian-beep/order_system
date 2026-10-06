"""数据工厂桥接层：复用 项目1「测试数据工厂」的生成能力。

设计原则（Phase 2 要求）：
  1. 不重写、不复制数据工厂代码 —— 直接复用其 core 包（loader / generator / rules）
  2. 不改动数据工厂任何文件 —— 模板放在本项目 tests/data_factory/templates 下，
     通过绝对路径传给工厂的 loader，工厂目录保持零改动
  3. 工厂只负责「生成数据」，落库由 order_system 适配层走业务 API 完成

工厂目录解析顺序：
  环境变量 DATA_FACTORY_HOME → 默认 ../../..（测开相关）/项目1
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
# order_system/tests/data_factory -> order_system/tests -> order_system -> 工作目录
WORKSPACE = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
FACTORY_HOME = os.getenv("DATA_FACTORY_HOME", os.path.join(WORKSPACE, "项目1"))
TEMPLATE_DIR = os.path.join(HERE, "templates")
# 工厂 file 输出目录：放系统临时目录，用完即删，不在项目里留文件
OUTPUT_DIR = os.path.join(tempfile.gettempdir(), "order_system_factory_out")


def factory_available() -> bool:
    """数据工厂 core 是否可复用（目录 + 核心模块都在）。"""
    return os.path.isdir(os.path.join(FACTORY_HOME, "core"))


def _ensure_on_path():
    if not factory_available():
        raise RuntimeError(f"未找到测试数据工厂: {FACTORY_HOME}")
    if FACTORY_HOME not in sys.path:
        sys.path.insert(0, FACTORY_HOME)


def factory_config() -> dict:
    """给工厂引擎用的配置：不连数据库（output=file），输出到临时目录。"""
    return {
        "database": {"url": "", "batch_size": 100},
        "marker": {"field": "env_tag", "value": "ORDER_SYSTEM_TEST"},
        "snapshot_dir": os.path.join(OUTPUT_DIR, "snapshots"),
        "export_dir": OUTPUT_DIR,
    }


def generate_rows(template="order_system", model=None, count=1, boundary=False) -> dict:
    """调用数据工厂生成数据，返回 {模型名: [数据行]}。

    参数:
        template: templates/ 下的模板名（不带 .yaml）
        model:    只生成指定模型（多个模型可写在同一个模板文件里）
        count:    每个模型生成条数
        boundary: 是否启用工厂的边界值模式（额外产出异常数据行）

    返回:
        {"user": [{...}]} 或 {"product": [{...}]}
    """
    _ensure_on_path()
    from core.loader import load_templates, sort_by_dependency
    from core.generator import generate

    path = os.path.join(TEMPLATE_DIR, f"{template}.yaml")
    templates = sort_by_dependency(load_templates(path))
    if model:
        templates = [t for t in templates if t["model"] == model]
    report = generate(templates, count=count, boundary=boundary, config=factory_config())
    return {name: stat["records"] for name, stat in report.items()}


def clear_output_dir():
    """清理工厂产生的临时导出文件（数据已由适配层落库，文件不需要保留）。"""
    shutil.rmtree(OUTPUT_DIR, ignore_errors=True)