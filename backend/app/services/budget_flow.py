"""隐私预算预约与差分查询执行：预约、取消、执行回执与扣费记录。

一致性约定：
- 所有余额判定与状态变更都在同一把锁内完成，两个标签页并发提交时
  只会有一个先落库，另一个看到落库后的真实余额；
- 不变量：同一数据集「已确认预约的合计持有量 + 已消耗量」永不超过预算总额；
- 取消与执行互为竞争操作，锁保证只有一个生效，双方随后查到的都是同一份终态；
- 执行按预约幂等：同一预约重复提交只确认一次费用，返回同一份执行回执。
"""
from __future__ import annotations

import re
import threading
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.store import store

_lock = threading.RLock()

RESERVATION_TABLE = "budget_reservation"
CHARGE_TABLE = "budget_charge"

STATUS_CONFIRMED = "已确认"
STATUS_REJECTED = "已拒绝"
STATUS_CANCELLED = "已取消"
STATUS_EXECUTED = "已执行"


# ——————————— 数值与编号工具 ———————————


def _dec(value: Any) -> Decimal | None:
    """把字段值解析成 Decimal；空值、非数值都返回 None。"""
    if value is None:
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError):
        return None


def _fmt(value: Decimal) -> str:
    """定点 4 位小数后去掉多余的 0，避免浮点尾差写回台账。"""
    text = f"{value:.4f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _next_code(rows: list[dict[str, Any]], field: str, prefix: str) -> str:
    """按 PREFIX-NNNN 规则取当前最大序号 +1。"""
    top = 0
    for row in rows:
        match = re.fullmatch(rf"{re.escape(prefix)}-(\d+)", str(row.get(field, "")))
        if match:
            top = max(top, int(match.group(1)))
    return f"{prefix}-{top + 1:04d}"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ——————————— 余额核算 ———————————


def _budget_for_dataset(dataset: str) -> dict[str, Any] | None:
    for row in store.rows("privacy_budget"):
        if str(row.get("数据集名称", "")).strip().casefold() == dataset.strip().casefold():
            return row
    return None


def _held_amount(budget_code: str) -> Decimal:
    """某预算当前被「已确认」预约占用的额度合计。"""
    held = Decimal("0")
    for row in store.aux_rows(RESERVATION_TABLE):
        if row.get("预算编号") == budget_code and row.get("status") == STATUS_CONFIRMED:
            held += _dec(row.get("申请费用")) or Decimal("0")
    return held


def budget_balance(budget: dict[str, Any]) -> dict[str, str]:
    """单个预算台账的总额/已消耗/预约占用/可用额度快照。"""
    total = _dec(budget.get("总预算Epsilon")) or Decimal("0")
    consumed = _dec(budget.get("已消耗Epsilon")) or Decimal("0")
    held = _held_amount(str(budget.get("预算编号", "")))
    available = total - consumed - held
    return {
        "总预算Epsilon": _fmt(total),
        "已消耗Epsilon": _fmt(consumed),
        "预约占用Epsilon": _fmt(held),
        "可用额度Epsilon": _fmt(available),
    }


# ——————————— 预约 ———————————


def list_reservations(
    *, status: str | None = None, dataset: str | None = None
) -> list[dict[str, Any]]:
    rows = list(store.aux_rows(RESERVATION_TABLE))
    if status:
        rows = [row for row in rows if row.get("status") == status]
    if dataset:
        rows = [
            row for row in rows
            if str(row.get("数据集名称", "")).casefold() == dataset.casefold()
        ]
    return rows


def get_reservation(reservation_id: int) -> dict[str, Any] | None:
    for row in store.aux_rows(RESERVATION_TABLE):
        if int(row.get("id", 0)) == reservation_id:
            return row
    return None


def find_reservation_by_code(code: str) -> dict[str, Any] | None:
    for row in store.aux_rows(RESERVATION_TABLE):
        if str(row.get("预约编号", "")).casefold() == code.strip().casefold():
            return row
    return None


def create_reservation(values: dict[str, Any]) -> tuple[bool, str, dict[str, Any] | None]:
    """登记一笔预算预约。返回 (是否确认, 回执说明, 预约回执)。

    数据集未登记、申请费用非法时不产生回执；余额不足时产生「已拒绝」回执，
    让发起方能查到自己申请的真实去向。
    """
    dataset = str(values.get("数据集名称") or "").strip()
    applicant = str(values.get("申请人") or "").strip() or "未署名"
    purpose = str(values.get("用途说明") or "").strip()
    if not dataset:
        return False, "缺少必填字段：数据集名称", None
    budget = _budget_for_dataset(dataset)
    if budget is None:
        return False, f"数据集「{dataset}」没有登记的隐私预算，无法预约", None
    cost = _dec(values.get("申请费用"))
    if cost is None or cost <= 0:
        return False, "申请费用必须是大于 0 的数值", None

    with _lock:
        balance = budget_balance(budget)
        available = _dec(balance["可用额度Epsilon"]) or Decimal("0")
        reservation: dict[str, Any] = {
            "id": max(
                (int(row.get("id", 0)) for row in store.aux_rows(RESERVATION_TABLE)),
                default=0,
            ) + 1,
            "预约编号": _next_code(store.aux_rows(RESERVATION_TABLE), "预约编号", "RSRV"),
            "预算编号": budget.get("预算编号"),
            "数据集名称": budget.get("数据集名称"),
            "申请费用": _fmt(cost),
            "申请人": applicant,
            "用途说明": purpose,
            "申请时间": _now(),
            "可用额度": balance["可用额度Epsilon"],
            "拒绝原因": "",
            "执行回执": None,
            "扣费编号": "",
        }
        if cost > available:
            reservation["status"] = STATUS_REJECTED
            reservation["拒绝原因"] = (
                f"余额不足：可用 {balance['可用额度Epsilon']}，申请 {_fmt(cost)}"
            )
            store.aux_rows(RESERVATION_TABLE).append(reservation)
            return False, f"预约被拒绝：{reservation['拒绝原因']}", reservation
        reservation["status"] = STATUS_CONFIRMED
        store.aux_rows(RESERVATION_TABLE).append(reservation)
        return (
            True,
            f"预约已确认：为数据集「{dataset}」预留 {_fmt(cost)} Epsilon",
            reservation,
        )


def cancel_reservation(reservation_id: int) -> tuple[bool, str, dict[str, Any] | None]:
    """取消预约并释放占用额度；与执行竞争时由锁决定先后。"""
    with _lock:
        reservation = get_reservation(reservation_id)
        if reservation is None:
            return False, f"预约 {reservation_id} 不存在或已归档", None
        status = reservation.get("status")
        if status == STATUS_CONFIRMED:
            reservation["status"] = STATUS_CANCELLED
            reservation["取消时间"] = _now()
            return True, "预约已取消，占用额度已释放", reservation
        if status == STATUS_CANCELLED:
            return True, "预约已是取消状态", reservation
        if status == STATUS_EXECUTED:
            return False, "预约已执行，费用已确认，不能取消", reservation
        return False, "预约已被拒绝，没有可取消的占用额度", reservation


# ——————————— 执行与扣费 ———————————


def list_charges() -> list[dict[str, Any]]:
    return list(store.aux_rows(CHARGE_TABLE))


def _receipt_payload(reservation: dict[str, Any]) -> dict[str, Any]:
    """组装执行回执响应：回执本体 + 关联查询记录 + 预约当前状态。"""
    receipt = reservation.get("执行回执") or {}
    query = None
    code = receipt.get("查询编号")
    if code:
        for row in store.rows("differential_sql"):
            if row.get("查询编号") == code:
                query = row
                break
    return {"回执": receipt, "查询记录": query, "预约": reservation}


def execute_query(values: dict[str, Any]) -> tuple[bool, str, dict[str, Any] | None]:
    """凭有效预约执行一次差分查询。返回 (是否执行成功, 说明, 执行回执)。

    同一预约重复提交时直接返回首次执行的回执，费用只确认一次。
    """
    code = str(values.get("预约编号") or "").strip()
    statement = str(values.get("查询语句") or "").strip()
    user = str(values.get("查询用户") or "").strip()
    if not code:
        return False, "缺少必填字段：预约编号", None
    if not statement:
        return False, "缺少必填字段：查询语句", None
    if not user:
        return False, "缺少必填字段：查询用户", None

    with _lock:
        reservation = find_reservation_by_code(code)
        if reservation is None:
            return False, f"预约「{code}」不存在，请先在隐私预算页完成预约", None
        status = reservation.get("status")
        if status == STATUS_EXECUTED:
            return True, "该预约已执行过，返回原执行回执，费用不重复扣减", _receipt_payload(reservation)
        if status == STATUS_CANCELLED:
            return False, "预约已取消，不能执行查询", _receipt_payload(reservation)
        if status == STATUS_REJECTED:
            return False, "预约未确认（余额不足），不能执行查询", _receipt_payload(reservation)

        budget = None
        for row in store.rows("privacy_budget"):
            if row.get("预算编号") == reservation.get("预算编号"):
                budget = row
                break
        if budget is None:
            return False, "预约关联的预算台账不存在，执行被拦截", None

        cost = _dec(reservation.get("申请费用")) or Decimal("0")
        total = _dec(budget.get("总预算Epsilon")) or Decimal("0")
        consumed = (_dec(budget.get("已消耗Epsilon")) or Decimal("0")) + cost
        remaining = total - consumed

        query_code = _next_code(store.rows("differential_sql"), "查询编号", "DIFF")
        scale = _fmt(Decimal("1") / cost) if cost > 0 else "0"
        query_record: dict[str, Any] = {
            "id": max(
                (int(row.get("id", 0)) for row in store.rows("differential_sql")),
                default=0,
            ) + 1,
            "status": "已执行",
            "pending": False,
            "abnormal": False,
            "查询编号": query_code,
            "查询语句": statement,
            "查询用户": user,
            "消耗Epsilon": _fmt(cost),
            "噪声注入量": f"Laplace(0,{scale})",
            "返回行数": "1",
            "执行时间": _now(),
            "预算剩余": f"{budget.get('预算编号')}剩余{_fmt(remaining)}",
        }
        store.rows("differential_sql").append(query_record)

        charge: dict[str, Any] = {
            "id": len(store.aux_rows(CHARGE_TABLE)) + 1,
            "扣费编号": _next_code(store.aux_rows(CHARGE_TABLE), "扣费编号", "CHG"),
            "预约编号": reservation.get("预约编号"),
            "预算编号": budget.get("预算编号"),
            "数据集名称": reservation.get("数据集名称"),
            "扣费Epsilon": _fmt(cost),
            "扣费后剩余": _fmt(remaining),
            "扣费时间": _now(),
        }
        store.aux_rows(CHARGE_TABLE).append(charge)

        budget["已消耗Epsilon"] = _fmt(consumed)
        note = f"{query_code}扣费{_fmt(cost)}"
        budget["消耗记录"] = (
            f"{budget.get('消耗记录')}；{note}" if budget.get("消耗记录") else note
        )
        if remaining <= 0:
            budget["status"] = "已耗尽"

        receipt: dict[str, Any] = {
            "执行编号": f"EXEC-{charge['id']:04d}",
            "预约编号": reservation.get("预约编号"),
            "查询编号": query_code,
            "扣费编号": charge["扣费编号"],
            "数据集名称": reservation.get("数据集名称"),
            "查询语句": statement,
            "查询用户": user,
            "扣费Epsilon": _fmt(cost),
            "预算剩余": _fmt(remaining),
            "执行时间": query_record["执行时间"],
            "结论": "执行成功，费用已确认",
        }
        reservation["status"] = STATUS_EXECUTED
        reservation["执行回执"] = receipt
        reservation["扣费编号"] = charge["扣费编号"]
        return True, f"查询已执行，扣费 {_fmt(cost)} Epsilon", _receipt_payload(reservation)
