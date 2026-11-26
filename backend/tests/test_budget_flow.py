"""预算预约与差分查询执行的一致性测试：并发预约、取消/执行竞争、幂等扣费。

运行：cd backend && python3 -m pytest tests/test_budget_flow.py -v
"""
from __future__ import annotations

import itertools
import threading

from app.services import budget_flow
from app.services.privacy_budget import PrivacyBudgetService
from app.store import store

_counter = itertools.count(1)


def _fresh_budget(total: str, consumed: str = "0") -> dict:
    """登记一条独立数据集的预算台账，避免用例之间互相影响。"""
    seq = next(_counter)
    service = PrivacyBudgetService()
    entry, missing = service.create_entry({
        "预算编号": f"PRIV-T{seq:04d}",
        "数据集名称": f"预约测试数据集-{seq}",
        "总预算Epsilon": total,
        "已消耗Epsilon": consumed,
        "消耗记录": "",
        "预算周期": "月度",
        "重置时间": "2026-12-01",
        "超额策略": "拒绝新查询",
    })
    assert not missing
    assert entry is not None
    return entry


def _reserve(dataset: str, cost: str):
    return budget_flow.create_reservation({
        "数据集名称": dataset, "申请费用": cost, "申请人": "测试员", "用途说明": "一致性测试",
    })


def _confirmed_total(budget_code: str) -> str:
    held = budget_flow._held_amount(budget_code)
    return budget_flow._fmt(held)


# ================================================================
# 1. 预约核验与额度不变量
# ================================================================

class TestReservation:
    def test_confirm_then_reject_when_balance_short(self):
        """余额 0.5 收到两笔 0.3：第一笔确认，第二笔拒绝且原因可查。"""
        budget = _fresh_budget("0.5")
        ok1, _, r1 = _reserve(budget["数据集名称"], "0.3")
        ok2, msg2, r2 = _reserve(budget["数据集名称"], "0.3")
        assert ok1 and r1["status"] == "已确认"
        assert not ok2 and r2["status"] == "已拒绝"
        assert "余额不足" in r2["拒绝原因"] and "余额不足" in msg2
        # 已确认合计不得超过可用额度
        assert _confirmed_total(budget["预算编号"]) == "0.3"
        balance = budget_flow.budget_balance(
            budget_flow._budget_for_dataset(budget["数据集名称"]))
        assert balance["可用额度Epsilon"] == "0.2"

    def test_unknown_dataset_rejected_without_receipt(self):
        ok, msg, receipt = _reserve("不存在的数据集", "0.3")
        assert not ok and receipt is None
        assert "没有登记" in msg

    def test_invalid_cost_rejected(self):
        budget = _fresh_budget("1.0")
        for bad in ("0", "-0.5", "abc", ""):
            ok, _, receipt = _reserve(budget["数据集名称"], bad)
            assert not ok and receipt is None

    def test_concurrent_reservations_only_one_confirmed(self):
        """两个标签页同时各约 0.3（余额 0.5）：恰好一笔确认、一笔拒绝。"""
        budget = _fresh_budget("0.5")
        results = [None, None]

        def apply(slot: int):
            results[slot] = _reserve(budget["数据集名称"], "0.3")

        threads = [threading.Thread(target=apply, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        statuses = {r[2]["status"] for r in results}
        assert statuses == {"已确认", "已拒绝"}
        # 不变量：已确认合计 + 已消耗 ≤ 总额
        assert _confirmed_total(budget["预算编号"]) == "0.3"


# ================================================================
# 2. 取消与释放
# ================================================================

class TestCancel:
    def test_cancel_releases_quota(self):
        budget = _fresh_budget("0.5")
        _, _, r1 = _reserve(budget["数据集名称"], "0.3")
        ok, msg, cancelled = budget_flow.cancel_reservation(r1["id"])
        assert ok and cancelled["status"] == "已取消"
        assert _confirmed_total(budget["预算编号"]) == "0"
        # 额度释放后可以再约
        ok2, _, r2 = _reserve(budget["数据集名称"], "0.5")
        assert ok2 and r2["status"] == "已确认"

    def test_cancel_is_idempotent(self):
        budget = _fresh_budget("1.0")
        _, _, r1 = _reserve(budget["数据集名称"], "0.3")
        budget_flow.cancel_reservation(r1["id"])
        ok, _, again = budget_flow.cancel_reservation(r1["id"])
        assert ok and again["status"] == "已取消"

    def test_cancelled_cannot_execute(self):
        budget = _fresh_budget("1.0")
        _, _, r1 = _reserve(budget["数据集名称"], "0.3")
        budget_flow.cancel_reservation(r1["id"])
        ok, msg, _ = budget_flow.execute_query({
            "预约编号": r1["预约编号"], "查询语句": "SELECT COUNT(*) FROM t", "查询用户": "tester",
        })
        assert not ok and "已取消" in msg


# ================================================================
# 3. 执行、幂等扣费与竞争
# ================================================================

class TestExecute:
    def test_execute_consumes_budget_and_writes_records(self):
        budget = _fresh_budget("1.0")
        _, _, r1 = _reserve(budget["数据集名称"], "0.3")
        ok, msg, payload = budget_flow.execute_query({
            "预约编号": r1["预约编号"], "查询语句": "SELECT COUNT(*) FROM t", "查询用户": "tester",
        })
        assert ok, msg
        receipt = payload["回执"]
        assert receipt["扣费Epsilon"] == "0.3"
        assert receipt["预算剩余"] == "0.7"
        assert payload["查询记录"]["status"] == "已执行"
        # 预算台账与预约状态同步更新
        fresh = budget_flow._budget_for_dataset(budget["数据集名称"])
        assert fresh["已消耗Epsilon"] == "0.3"
        assert receipt["预约编号"] in str(fresh["消耗记录"]) or \
            payload["查询记录"]["查询编号"] in str(fresh["消耗记录"])
        assert budget_flow.get_reservation(r1["id"])["status"] == "已执行"

    def test_same_reservation_charged_only_once(self):
        """重复提交同一执行请求：回执相同、扣费记录只有一条、余额只减一次。"""
        budget = _fresh_budget("1.0")
        _, _, r1 = _reserve(budget["数据集名称"], "0.3")
        values = {"预约编号": r1["预约编号"], "查询语句": "SELECT 1", "查询用户": "tester"}
        ok1, _, p1 = budget_flow.execute_query(values)
        ok2, msg2, p2 = budget_flow.execute_query(values)
        assert ok1 and ok2 and "不重复" in msg2
        assert p1["回执"]["执行编号"] == p2["回执"]["执行编号"]
        charges = [c for c in budget_flow.list_charges() if c["预约编号"] == r1["预约编号"]]
        assert len(charges) == 1
        fresh = budget_flow._budget_for_dataset(budget["数据集名称"])
        assert fresh["已消耗Epsilon"] == "0.3"
        queries = [q for q in store.rows("differential_sql")
                   if q.get("查询编号") == p1["回执"]["查询编号"]]
        assert len(queries) == 1

    def test_execute_unknown_or_rejected_reservation(self):
        budget = _fresh_budget("0.2")
        ok, msg, _ = budget_flow.execute_query({
            "预约编号": "RSRV-9999", "查询语句": "SELECT 1", "查询用户": "tester",
        })
        assert not ok and "不存在" in msg
        _, _, rejected = _reserve(budget["数据集名称"], "0.3")  # 余额不足 → 已拒绝
        assert rejected["status"] == "已拒绝"
        ok2, msg2, _ = budget_flow.execute_query({
            "预约编号": rejected["预约编号"], "查询语句": "SELECT 1", "查询用户": "tester",
        })
        assert not ok2 and "未确认" in msg2

    def test_executed_cannot_cancel(self):
        budget = _fresh_budget("1.0")
        _, _, r1 = _reserve(budget["数据集名称"], "0.3")
        budget_flow.execute_query({
            "预约编号": r1["预约编号"], "查询语句": "SELECT 1", "查询用户": "tester",
        })
        ok, msg, _ = budget_flow.cancel_reservation(r1["id"])
        assert not ok and "已执行" in msg

    def test_cancel_execute_race_single_winner(self):
        """取消与查询开始相遇：恰好一个生效，两页查到同一终态。"""
        budget = _fresh_budget("1.0")
        _, _, r1 = _reserve(budget["数据集名称"], "0.3")
        outcomes: dict[str, tuple] = {}

        def do_cancel():
            outcomes["cancel"] = budget_flow.cancel_reservation(r1["id"])

        def do_execute():
            outcomes["execute"] = budget_flow.execute_query({
                "预约编号": r1["预约编号"], "查询语句": "SELECT 1", "查询用户": "tester",
            })

        threads = [threading.Thread(target=do_cancel), threading.Thread(target=do_execute)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        final = budget_flow.get_reservation(r1["id"])
        charges = [c for c in budget_flow.list_charges() if c["预约编号"] == r1["预约编号"]]
        winners = [name for name, (ok, *_rest) in outcomes.items() if ok]
        # 取消是幂等的：只有执行成功才算执行方赢下竞争
        if final["status"] == "已执行":
            assert outcomes["execute"][0] is True
            assert len(charges) == 1
            fresh = budget_flow._budget_for_dataset(budget["数据集名称"])
            assert fresh["已消耗Epsilon"] == "0.3"
        else:
            assert final["status"] == "已取消"
            assert outcomes["execute"][0] is False
            assert len(charges) == 0
        assert winners  # 至少取消一方是成功的
