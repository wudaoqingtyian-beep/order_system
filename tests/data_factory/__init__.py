"""测试数据工厂接入层（Phase 2）。

本包只做「桥接 + 适配」：
  - factory_bridge.py      复用 项目1 数据工厂的 core 生成能力（不做任何复制）
  - order_data_factory.py  把生成的数据落成 order_system 真实业务数据，并管理批次生命周期
  - templates/             order_system 专用的数据工厂 YAML 模板
"""