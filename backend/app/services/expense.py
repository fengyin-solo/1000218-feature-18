"""费用报销业务规则：状态流转、草稿、并发提交与处理日志都收在这里。"""
from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Any
from uuid import uuid4

from app.store import store

MODULE = "expense"
REQUIRED_FIELDS = ["报销单号", "报销人", "费用类别"]
STATUS_ORDER = ["待提交", "待审核", "已通过", "已驳回", "已打款"]
ACTION_RULES = {"提交报销": "待审核", "审核通过": "已通过", "驳回报销": "已驳回", "确认打款": "已打款"}
NEGATIVE_ACTIONS = ["驳回报销"]
DRAFTABLE_STATUS = ["待提交", "待审核"]
_ACTION_LOCK = Lock()


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
        entry = store.find(MODULE, entry_id)
        if entry is not None:
            entry.setdefault("version", 1)
        return entry

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["报销状态"] = STATUS_ORDER[0]
        entry["version"] = 1
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def save_draft(
        self,
        entry_id: int,
        operator: str,
        values: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str]:
        entry = self.get_entry(entry_id)
        if entry is None:
            return None, f"报销单 {entry_id} 不存在或已归档"
        operator = operator.strip() or "值班管理员"
        action = str(values.get("action") or "").strip()
        if action not in ACTION_RULES:
            return None, "请选择有效的处理动作"
        if entry["status"] not in DRAFTABLE_STATUS:
            return None, "该报销单已有正式处理结果，草稿已失效"

        location = values.get("location")
        draft = {
            "entry_id": entry_id,
            "operator": operator,
            "action": action,
            "remark": str(values.get("remark") or "").strip(),
            "location": str(location or "").strip()[:500],
            "entry_version": int(entry.get("version", 1)),
            "updated_at": _now(),
        }
        store.bucket("expense_drafts")[(entry_id, operator)] = draft
        return draft, "处理草稿已保存"

    def get_draft(self, entry_id: int, operator: str) -> dict[str, Any] | None:
        return store.bucket("expense_drafts").get((entry_id, operator.strip() or "值班管理员"))

    def list_drafts(self, operator: str) -> list[dict[str, Any]]:
        operator = operator.strip() or "值班管理员"
        drafts = [
            draft for draft in store.bucket("expense_drafts").values()
            if draft.get("operator") == operator
        ]
        return sorted(drafts, key=lambda item: str(item.get("updated_at", "")), reverse=True)

    def delete_draft(self, entry_id: int, operator: str) -> bool:
        return store.bucket("expense_drafts").pop((entry_id, operator.strip() or "值班管理员"), None) is not None

    def list_history(self, entry_id: int) -> list[dict[str, Any]] | None:
        entry = self.get_entry(entry_id)
        if entry is None:
            return None
        logs = store.bucket("expense_history").setdefault(entry_id, [])
        if not logs:
            logs.append({
                "seq": 0,
                "request_id": None,
                "action": "初始状态",
                "from_status": None,
                "to_status": entry["status"],
                "remark": "报销单进入处理流程",
                "operator": "系统",
                "created_at": _now(),
            })
        return sorted(logs, key=lambda item: int(item["seq"]))

    def run_action(
        self,
        entry_id: int,
        action: str,
        *,
        remark: str = "",
        operator: str = "值班管理员",
        expected_version: int | None = None,
        request_id: str | None = None,
    ) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
        entry = self.get_entry(entry_id)
        if entry is None:
            return None, f"报销单 {entry_id} 不存在或已归档", {}
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于费用报销可执行范围", {}

        with _ACTION_LOCK:
            request_id = (request_id or str(uuid4())).strip()
            previous_request = store.bucket("expense_requests").get(request_id)
            if previous_request is not None:
                if previous_request.get("entry_id") != entry_id:
                    return None, "请求编号已用于其他报销单，请刷新后重新提交", {"conflict": True, "request_id": request_id}
                return entry, "请求已处理，未重复生成处理记录", {"duplicate": True, "request_id": request_id}

            current_status = entry["status"]
            if current_status == STATUS_ORDER[-1]:
                return None, "报销单已打款，不能再覆盖正式处理结果", {"conflict": True, "request_id": request_id}

            target = ACTION_RULES[action]
            allowed, message = self._is_transition_allowed(action, current_status, target)
            if not allowed:
                return None, message, {"request_id": request_id}

            version = int(entry.get("version", 1))
            stale = expected_version is not None and int(expected_version) != version
            operator = operator.strip() or "值班管理员"
            log = {
                "seq": version,
                "request_id": request_id,
                "action": action,
                "from_status": current_status,
                "to_status": target,
                "remark": remark.strip(),
                "operator": operator,
                "created_at": _now(),
            }
            store.bucket("expense_history").setdefault(entry_id, []).append(log)
            store.bucket("expense_requests")[request_id] = {"entry_id": entry_id, "seq": version}

            entry["status"] = target
            entry["报销状态"] = target
            entry["version"] = version + 1
            entry["pending"] = target != STATUS_ORDER[-1]
            entry["abnormal"] = action in NEGATIVE_ACTIONS

            # 正式提交、通过、驳回或打款后，所有未完成处理均不得再恢复。
            self._clear_entry_drafts(entry_id)

            if stale:
                message = f"报销单已按最新提交{action}，此前处理记录仍可查"
            else:
                message = f"报销单已{action}"
            return entry, message, {"conflict": stale, "request_id": request_id}

    def _is_transition_allowed(
        self,
        action: str,
        current_status: str,
        target: str,
    ) -> tuple[bool, str]:
        if action == "提交报销":
            if current_status != "待提交":
                return False, "只有待提交报销单可以提交审核"
        elif action == "确认打款":
            if current_status != "已通过":
                return False, "只有审核通过的报销单可以确认打款"
        elif current_status not in {"待审核", "已通过", "已驳回"}:
            return False, f"当前状态为「{current_status}」，不能执行「{action}」"
        elif current_status == target:
            return False, f"报销单已是「{target}」，无需重复处理"
        return True, ""

    def _clear_entry_drafts(self, entry_id: int) -> None:
        drafts = store.bucket("expense_drafts")
        for key in [key for key in drafts if key[0] == entry_id]:
            drafts.pop(key, None)
