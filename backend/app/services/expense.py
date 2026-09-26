"""费用报销业务规则：状态流转、草稿持久化、并发提交与处理留痕都收在这里。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "expense"
DRAFT_MODULE = "expense_draft"
HISTORY_MODULE = "expense_history"
REQUIRED_FIELDS = ["报销单号", "报销人", "费用类别"]
STATUS_ORDER = ["待提交", "待审核", "已通过", "已驳回", "已打款"]
TERMINAL_STATUS = "已打款"
# 动作 -> 目标状态；以后提交为准，因此不做来源状态限制，仅拦截已打款终态。
ACTION_RULES = {"提交报销": "待审核", "审核通过": "已通过", "驳回报销": "已驳回", "确认打款": "已打款"}
NEGATIVE_ACTIONS = ["驳回报销"]
DRAFT_ACTIONS = ["提交报销", "审核通过", "驳回报销", "确认打款"]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ExpenseService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("报销单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    # ------------------------------------------------------------------
    # 处理草稿：离开后再进入可恢复；正式通过/驳回/打款后草稿同步失效。
    # ------------------------------------------------------------------
    def list_drafts(self, operator: str) -> list[dict[str, Any]]:
        drafts = [
            dict(row)
            for row in store.rows(DRAFT_MODULE)
            if row.get("operator") == operator and row.get("active", True)
        ]
        for draft in drafts:
            entry = store.find(MODULE, int(draft.get("entry_id", 0)))
            # 报销单已进入终态时，草稿即便没来得及批量失效也不再视为可用。
            draft["valid"] = entry is not None and entry.get("status") != TERMINAL_STATUS
            draft["entry_status"] = entry.get("status") if entry else None
        return [draft for draft in drafts if draft["valid"]]

    def save_draft(
        self,
        entry_id: int,
        operator: str,
        *,
        action: str | None = None,
        note: str | None = None,
        position: int | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"报销单 {entry_id} 不存在或已归档"
        if entry.get("status") == TERMINAL_STATUS:
            return None, f"报销单 {entry_id} 已打款，处理流程已结束，草稿无法再保存"
        if action is not None and action.strip() and action.strip() not in DRAFT_ACTIONS:
            return None, f"动作「{action}」不属于费用报销可执行范围"

        drafts = store.rows(DRAFT_MODULE)
        draft = next(
            (
                row
                for row in drafts
                if int(row.get("entry_id", 0)) == entry_id and row.get("operator") == operator
            ),
            None,
        )
        if draft is None:
            draft = {
                "id": max((int(row.get("id", 0)) for row in drafts), default=0) + 1,
                "entry_id": entry_id,
                "operator": operator,
                "action": None,
                "note": "",
                "position": 0,
                "active": True,
                "submitted": False,
                "created_at": _now(),
            }
            drafts.append(draft)
        # 只更新调用方显式给出的字段，避免一次只存位置时把动作/说明抹掉。
        if action is not None:
            draft["action"] = action.strip() or None
        if note is not None:
            draft["note"] = note
        if position is not None:
            draft["position"] = max(int(position), 0)
        draft["active"] = True
        draft["updated_at"] = _now()
        return dict(draft), "处理草稿已保存"

    def get_draft(self, entry_id: int, operator: str) -> dict[str, Any] | None:
        # 已失效的草稿也要找出来，便于恢复时说明「为什么没了」。
        draft = next(
            (
                row
                for row in store.rows(DRAFT_MODULE)
                if int(row.get("entry_id", 0)) == entry_id and row.get("operator") == operator
            ),
            None,
        )
        if draft is None:
            return None
        entry = store.find(MODULE, entry_id)
        result = dict(draft)
        result["valid"] = (
            draft.get("active", True)
            and entry is not None
            and entry.get("status") != TERMINAL_STATUS
        )
        result["entry_status"] = entry.get("status") if entry else None
        if not draft.get("active", True):
            result["invalid_reason"] = f"报销单已被正式处理（当前状态：{result['entry_status'] or '未知'}），原草稿已失效"
        elif entry is not None and entry.get("status") == TERMINAL_STATUS:
            result["invalid_reason"] = "报销单已打款，处理流程已结束，原草稿已失效"
        return result

    def discard_draft(self, entry_id: int, operator: str) -> str:
        for row in store.rows(DRAFT_MODULE):
            if int(row.get("entry_id", 0)) == entry_id and row.get("operator") == operator:
                row["active"] = False
                row["updated_at"] = _now()
        return "处理草稿已丢弃"

    # ------------------------------------------------------------------
    # 正式处理：以后提交为准，但已打款记录不允许覆盖；每次动作只增留痕。
    # ------------------------------------------------------------------
    def run_action(
        self,
        entry_id: int,
        action: str,
        *,
        operator: str = "值班管理员",
        note: str | None = None,
        request_id: str | None = None,
    ) -> tuple[dict[str, Any] | None, str, bool]:
        """返回 (报销单, 说明, 是否为重放的幂等请求)。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"报销单 {entry_id} 不存在或已归档", False
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于费用报销可执行范围", False

        # 网络失败重试时带上同一个 request_id：直接返回首次结果，不重复落记录。
        if request_id:
            existed = next(
                (
                    row
                    for row in store.rows(HISTORY_MODULE)
                    if row.get("request_id") == request_id
                ),
                None,
            )
            if existed is not None:
                return entry, f"请求已处理过，沿用上一次结果：{existed.get('message')}", True

        target = ACTION_RULES[action]
        if entry.get("status") == TERMINAL_STATUS:
            return None, f"报销单 {entry_id} 已打款，处理记录不可覆盖", False

        before_status = entry.get("status")
        entry["status"] = target
        entry["pending"] = target != TERMINAL_STATUS
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        message = f"报销单已{action}"

        history = store.rows(HISTORY_MODULE)
        history.append({
            "id": max((int(row.get("id", 0)) for row in history), default=0) + 1,
            "entry_id": entry_id,
            "operator": operator,
            "action": action,
            "before_status": before_status,
            "after_status": target,
            "note": (note or "").strip(),
            "request_id": request_id,
            "acted_at": _now(),
            "message": message,
        })

        # 正式通过、驳回或打款后，该报销单上所有人的草稿同步失效；
        # 「提交报销」只是把单据送审，不影响其他人未完成的处理草稿。
        if action in ("审核通过", "驳回报销", "确认打款"):
            for draft in store.rows(DRAFT_MODULE):
                if int(draft.get("entry_id", 0)) == entry_id and draft.get("active", True):
                    draft["active"] = False
                    draft["updated_at"] = _now()
        return entry, message, False

    def list_history(self, entry_id: int) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in store.rows(HISTORY_MODULE)
            if int(row.get("entry_id", 0)) == entry_id
        ]
