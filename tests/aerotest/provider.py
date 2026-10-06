"""AeroTest 造数钩子：把 Phase 2 数据工厂接到框架的 setup / teardown 上。

AeroTest（项目2）用例生命周期契约（core/runner.py）：
    setup(declarations, ctx) -> batch_id    前置造数，数据回填变量池
    teardown(batch_id) -> dict              后置清理（runner 放在 finally，用例失败也执行）

本适配层不新增造数能力，只用 Phase 2 的 OrderDataFactory：
数据一律通过 order_system 自己的业务 API 创建（不写死 ID、不直接插库），
清理按批次主键精确删除，跑完即回到基线。

YAML setup 段声明格式：
    - template: user               创建用户（用户名/密码由数据工厂随机生成）
      var: user_id                 变量池名，值为用户 id
    - template: product            创建商品 + 库存（一次调用同时建两张表的数据）
      var: product_id
      price: 30.00                 可选：固定价格（金额断言需要可预测的价格）
      stock: 10                    可选：库存数量
      status: ON_SALE              可选：ON_SALE / OFF_SHELF
    - template: order              创建前置订单（用于取消类场景）
      user: "${user_id}"           引用前面造出的用户
      product: "${product_id}"     或 items: [{product_id: ..., quantity: ...}]
      quantity: 3
      cancel: true                 可选：创建后立即取消（构造「已取消订单」）
      var: order_id

声明里的 ${var} 走 AeroTest 变量池渲染，整串占位符保留原生类型，故 id 仍是 int。
"""
from order_system.tests.data_factory.order_data_factory import (
    DataFactoryError,
    OrderDataFactory,
)

SUPPORTED_TEMPLATES = ("user", "product", "order")


class _ResponseAdapter:
    """把 AeroTest 的 ApiResponse 适配成数据工厂期望的响应接口。

    差异：AeroTest 的 `ApiResponse.json` 是属性（直接给 dict），
    Phase 2 工厂按 FastAPI TestClient 习惯写成 `resp.json()`，
    这里包一层，两边源码都不用改。
    """

    def __init__(self, response):
        self._response = response
        self.status_code = response.status
        self.text = response.text

    def json(self):
        return self._response.json


class _ClientAdapter:
    """把 AeroTest HttpClient 适配成数据工厂期望的 client 接口。

    工厂只用 get/post + resp.json()；请求仍由 AeroTest 的请求引擎发出，
    超时、日志、多环境 base_url 等能力全部复用。
    """

    def __init__(self, client):
        self._client = client

    def get(self, url, **kw):
        return _ResponseAdapter(self._client.get(url, **kw))

    def post(self, url, **kw):
        return _ResponseAdapter(self._client.post(url, **kw))


class OrderDataProvider:
    """AeroTest 造数钩子实现（接口与 core.data_provider.DataProvider 一致）。"""

    def __init__(self, client, factory_cls=OrderDataFactory):
        self.client = client            # AeroTest HttpClient（复用其超时/日志/多环境能力）
        self.factory_client = _ClientAdapter(client)   # 交给数据工厂用的适配视图
        self.factory_cls = factory_cls
        self._batches: dict = {}        # batch_id -> OrderDataFactory（teardown 用）

    # ------------------------------------------------------------ 前置造数
    def setup(self, declarations: list, ctx) -> str | None:
        """执行 setup 声明，返回本用例的批次号（一条用例 = 一个批次 = 一次精准清理）。"""
        if not declarations:
            return None
        factory = self.factory_cls(self.factory_client)
        # 先登记再创建：造数中途失败时 runner 拿不到批次号，
        # 但批次仍留在内存里，集成层的兜底清理（cleanup_all）能把它清干净
        self._batches[factory.batch_id] = factory
        for decl in declarations:
            d = ctx.render_deep({"template": decl} if isinstance(decl, str) else dict(decl))
            template = d.get("template")
            if template not in SUPPORTED_TEMPLATES:
                raise ValueError(
                    f"不支持的数据声明 template={template!r}（可用: {list(SUPPORTED_TEMPLATES)}）")
            var = d.get("var") or template
            ctx.set(var, self._create(factory, template, d))
        return factory.batch_id

    def _create(self, factory, template: str, d: dict):
        """按声明创建业务数据，返回回填变量池的值（业务主键 id）。"""
        if template == "user":
            return factory.create_user()["id"]

        if template == "product":
            return factory.create_product(
                price=d.get("price"), stock=d.get("stock"),
                status=d.get("status"), name=d.get("name"),
            )["id"]

        # template == "order"：前置订单，造不出来说明场景前提不成立，直接失败
        items = d.get("items") or [
            {"product_id": d["product"], "quantity": d["quantity"]}
        ]
        body = factory.place_order(d["user"], items)
        if body.get("code") != 0:
            raise DataFactoryError(f"前置订单创建失败: {body}")
        order_id = body["data"]["id"]
        if d.get("cancel"):
            factory.cancel_order(order_id)
        return order_id

    # ------------------------------------------------------------ 后置清理
    def teardown(self, batch_id: str | None) -> dict:
        """按批次精确清理（无声明时返回 skipped，与框架原语义一致）。"""
        factory = self._batches.pop(batch_id, None)
        if factory is None:
            return {"skipped": True, "batch_id": batch_id}
        return factory.cleanup()

    def cleanup_all(self) -> dict:
        """兜底清理：把仍留在内存里的批次全部清掉。

        runner 的正常路径是 setup 返回 batch_id → finally 调 teardown(batch_id)。
        但 setup 中途抛异常时批次号来不及返回，已落库的数据会没人清理；
        集成层在用例结束时调用本方法补齐，保证「失败用例零残留」。
        清理幂等（Phase 2 已实现），正常路径下不会重复删。
        """
        return {batch_id: self._batches.pop(batch_id).cleanup()
                for batch_id in list(self._batches)}