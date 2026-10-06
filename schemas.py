"""Pydantic 请求/响应模型。"""
from typing import List

from pydantic import BaseModel, Field


# ---------- 请求 ----------
class UserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=50, description="用户名")
    password: str = Field(..., min_length=1, max_length=100, description="密码")


class OrderItemIn(BaseModel):
    product_id: int = Field(..., description="商品 ID")
    quantity: int = Field(..., description="购买数量，必须大于 0")


class OrderCreate(BaseModel):
    user_id: int = Field(..., description="下单用户 ID")
    items: List[OrderItemIn] = Field(..., min_length=1, description="商品明细列表")


# ---------- 响应 ----------
class ApiResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: dict | None = None


class OrderItemOut(BaseModel):
    product_id: int
    product_name: str
    quantity: int
    price: float
    subtotal: float


class OrderOut(BaseModel):
    id: int
    user_id: int
    status: str
    total_amount: float
    items: List[OrderItemOut] = []
