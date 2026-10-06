"""统一错误定义：稳定的错误码 + 明确的中文错误信息，便于自动化测试断言。"""


class BizError(Exception):
    """业务异常。code 稳定，message 稳定，不暴露内部细节。"""

    def __init__(self, code: int, message: str, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


# 错误码约定：模块前缀 * 1000
# 1000 段：用户
E_USER_NOT_FOUND = (1001, "用户不存在")
# 2000 段：商品
E_PRODUCT_NOT_FOUND = (2001, "商品不存在")
E_PRODUCT_OFF_SHELF = (2002, "商品已下架，不可购买")
# 3000 段：库存与数量
E_STOCK_NOT_FOUND = (3001, "库存记录不存在")
E_STOCK_NOT_ENOUGH = (3002, "库存不足")
E_QUANTITY_INVALID = (3003, "购买数量必须大于 0")
E_ITEMS_EMPTY = (3004, "订单商品明细不能为空")
# 4000 段：订单
E_ORDER_NOT_FOUND = (4001, "订单不存在")
E_ORDER_ALREADY_CANCELLED = (4002, "订单已取消，不能重复取消")
E_ORDER_STATUS_NOT_CANCELABLE = (4003, "当前订单状态不允许取消")
# 9000 段：通用
E_PARAM_INVALID = (9001, "请求参数不合法")
E_INTERNAL_ERROR = (9000, "服务内部错误")
