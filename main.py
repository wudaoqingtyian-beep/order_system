"""FastAPI 应用入口。

统一响应格式: {"code": 0, "message": "ok", "data": {...}}
code == 0 表示成功；非 0 为稳定的业务错误码。
"""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import errors, service
from .schemas import ApiResponse, OrderCreate, UserCreate
from .service import STATUS_ON_SALE

app = FastAPI(
    title="轻量订单管理系统",
    description="用于接口测试 / 边界值测试 / 数据库校验的被测业务系统",
    version="1.0.0",
)


def ok(data=None, message="ok"):
    return JSONResponse({"code": 0, "message": message, "data": data})


def fail(code: int, message: str, http_status: int = 400):
    return JSONResponse(
        {"code": code, "message": message, "data": None}, status_code=http_status
    )


@app.exception_handler(errors.BizError)
async def biz_error_handler(request: Request, exc: errors.BizError):
    return fail(exc.code, exc.message, exc.http_status)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    # 参数类型/格式错误统一成 9001，不把内部细节抛给调用方
    return fail(errors.E_PARAM_INVALID[0], errors.E_PARAM_INVALID[1], 422)


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    return fail(errors.E_INTERNAL_ERROR[0], errors.E_INTERNAL_ERROR[1], 500)


# ---------------------------------------------------------------- API
@app.post("/api/users", summary="创建用户")
def api_create_user(body: UserCreate):
    return ok(service.create_user(body.username, body.password), "created")


@app.get("/api/products", summary="商品列表")
def api_list_products():
    return ok(service.list_products())


@app.get("/api/products/{product_id}", summary="商品详情")
def api_get_product(product_id: int):
    return ok(service.get_product(product_id))


@app.get("/api/inventory/{product_id}", summary="查询库存")
def api_get_inventory(product_id: int):
    return ok(service.get_inventory(product_id))


@app.post("/api/orders", summary="创建订单")
def api_create_order(body: OrderCreate):
    items = [{"product_id": i.product_id, "quantity": i.quantity} for i in body.items]
    return ok(service.create_order(body.user_id, items), "created")


@app.get("/api/orders/{order_id}", summary="查询订单")
def api_get_order(order_id: int):
    return ok(service.get_order(order_id))


@app.post("/api/orders/{order_id}/cancel", summary="取消订单并恢复库存")
def api_cancel_order(order_id: int):
    return ok(service.cancel_order(order_id), "cancelled")


# ---------------------------------------------------------------- 测试辅助接口（非核心业务，仅用于准备数据）
@app.post("/api/products/setup", summary="【测试用】创建商品并设置库存")
def api_setup_product(body: dict):
    return ok(service.setup_product(
        body.get("name"),
        str(body.get("price", "0")),
        int(body.get("stock", 0)),
        body.get("status", STATUS_ON_SALE),
    ), "created")


@app.post("/api/products/{product_id}/inventory", summary="【测试用】设置库存")
def api_set_inventory(product_id: int, body: dict):
    return ok(service.set_inventory(product_id, int(body.get("stock", 0))))


@app.put("/api/products/{product_id}/status", summary="【测试用】上架/下架")
def api_set_status(product_id: int, body: dict):
    return ok(service.set_product_status(product_id, body.get("status", "")))
