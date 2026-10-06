"""框架与工厂的 core 包共存处理（Phase 3 接入必需）。

背景（实测问题）：
    AeroTest（项目2）把框架代码放在顶层包 `core`（core.runner / core.assertions ...），
    Phase 2 复用的测试数据工厂（项目1）也把核心代码放在顶层包 `core`
    （core.loader / core.generator / core.rules ...）。
    Python 的 sys.modules 只允许一个 `core`，两者放在同一进程会互相顶掉：
    先导入框架 core 后，工厂的 `from core.loader import ...` 会直接
    ModuleNotFoundError: No module named 'core.loader'。

处理（为什么不改任何一方源码）：
    两个 core 目录下的文件名互不重叠，因此把 项目1/core 追加到 `core` 包的 __path__，
    让 `core` 成为「一个包名，两个代码目录」：
        core.runner  → 项目2/core/runner.py     （框架请求/断言/执行）
        core.loader  → 项目1/core/loader.py     （工厂模板加载/生成）
    框架与工厂都继续用原来的 `from core.x import y` 写法，双方源码零改动。
"""
import importlib.util
import os
import sys


def merge_core_namespaces(aero_home: str, factory_home: str):
    """把框架与工厂的 core 目录合并到同一个 `core` 包下（幂等）。"""
    frame_dir = os.path.join(aero_home, "core")
    factory_dir = os.path.join(factory_home, "core")
    if not os.path.isdir(frame_dir):
        raise RuntimeError(f"未找到 AeroTest 框架 core: {frame_dir}")
    if not os.path.isdir(factory_dir):
        raise RuntimeError(f"未找到数据工厂 core: {factory_dir}")

    paths = [frame_dir, factory_dir]
    pkg = sys.modules.get("core")
    if pkg is None:
        spec = importlib.util.spec_from_file_location(
            "core", os.path.join(frame_dir, "__init__.py"),
            submodule_search_locations=list(paths),
        )
        pkg = importlib.util.module_from_spec(spec)
        sys.modules["core"] = pkg
        spec.loader.exec_module(pkg)
    else:
        for path in paths:
            if path not in pkg.__path__:
                pkg.__path__.append(path)
    return pkg