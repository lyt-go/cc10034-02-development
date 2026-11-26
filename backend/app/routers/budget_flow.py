"""隐私预算预约与差分查询执行接口：预约回执、取消、执行回执、扣费记录。

业务判断全部在 app/services/budget_flow.py，路由层只做参数搬运。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services import budget_flow

router = APIRouter(prefix="/api", tags=["预算预约与差分执行"])


@router.get("/privacy_budget/reservations", response_model=PageResult[dict])
def list_reservations(
    status: str | None = Query(default=None),
    dataset: str | None = Query(default=None, alias="数据集名称"),
) -> PageResult[dict]:
    items = budget_flow.list_reservations(status=status, dataset=dataset)
    return PageResult(items=items, total=len(items), page=1, size=max(len(items), 1))


@router.post("/privacy_budget/reservations", response_model=ActionResult)
def create_reservation(payload: EntryPayload) -> ActionResult:
    ok, message, entry = budget_flow.create_reservation(payload.values)
    return ActionResult(ok=ok, message=message, entry=entry)


@router.get("/privacy_budget/reservations/{reservation_id}", response_model=dict)
def get_reservation(reservation_id: int) -> dict[str, Any]:
    entry = budget_flow.get_reservation(reservation_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"预约 {reservation_id} 不存在或已归档")
    return entry


@router.post("/privacy_budget/reservations/{reservation_id}/cancel", response_model=ActionResult)
def cancel_reservation(reservation_id: int) -> ActionResult:
    ok, message, entry = budget_flow.cancel_reservation(reservation_id)
    return ActionResult(ok=ok, message=message, entry=entry)


@router.get("/privacy_budget/charges", response_model=PageResult[dict])
def list_charges() -> PageResult[dict]:
    items = budget_flow.list_charges()
    return PageResult(items=items, total=len(items), page=1, size=max(len(items), 1))


@router.post("/differential_sql/execute", response_model=ActionResult)
def execute_query(payload: EntryPayload) -> ActionResult:
    ok, message, entry = budget_flow.execute_query(payload.values)
    return ActionResult(ok=ok, message=message, entry=entry)
