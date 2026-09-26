"""费用报销接口：维护报销单，覆盖提交报销、审核通过、驳回报销、确认打款等动作。

另提供处理草稿的保存/恢复/丢弃接口：离开页面后重新进入可恢复未提交内容；
正式通过、驳回或打款后草稿同步失效。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import (
    ActionPayload,
    ActionResult,
    DraftPayload,
    EntryPayload,
    PageResult,
)
from app.services.expense import ExpenseService

router = APIRouter(prefix="/api/expense", tags=["费用报销"])

service = ExpenseService()

LIST_FIELDS = ["报销单号", "报销人", "费用类别", "发生日期", "报销金额", "票据张数", "所属科目", "报销状态"]
STATUSES = ["待提交", "待审核", "已通过", "已驳回", "已打款"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按报销单号检索"),
    status: str | None = Query(default=None, description="待提交、待审核、已通过、已驳回、已打款"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按报销单号与状态过滤费用报销列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出费用报销清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "expense", "total": total, "items": items}


@router.get("/drafts")
def list_drafts(
    operator: str = Query(default="值班管理员", description="按处理人查询其未提交草稿"),
) -> dict[str, Any]:
    """列出当前处理人仍有效的草稿，用于进入页面时提示并恢复。"""
    return {"items": service.list_drafts(operator)}


@router.get("/{entry_id}/drafts")
def get_draft(
    entry_id: int,
    operator: str = Query(default="值班管理员", description="按处理人定位草稿"),
) -> dict[str, Any]:
    """恢复某张报销单的处理草稿；草稿已失效或不存在时 ok=False 并说明原因。"""
    draft = service.get_draft(entry_id, operator)
    if draft is None:
        return {"ok": False, "message": "没有可恢复的处理草稿", "draft": None}
    if not draft.get("valid"):
        return {
            "ok": False,
            "message": draft.get("invalid_reason") or f"报销单已为「{draft.get('entry_status')}」，原草稿已失效",
            "draft": draft,
        }
    return {"ok": True, "message": "已恢复未提交的处理草稿", "draft": draft}


@router.put("/{entry_id}/drafts", response_model=ActionResult)
def save_draft(entry_id: int, payload: DraftPayload) -> ActionResult:
    """保存处理中的动作选择、补充说明和当前位置；只更新提交的字段。"""
    operator = (payload.operator or "值班管理员").strip() or "值班管理员"
    draft, message = service.save_draft(
        entry_id,
        operator,
        action=payload.action,
        note=payload.note,
        position=payload.position,
    )
    if draft is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=draft)


@router.delete("/{entry_id}/drafts", response_model=ActionResult)
def discard_draft(
    entry_id: int,
    operator: str = Query(default="值班管理员", description="按处理人丢弃草稿"),
) -> ActionResult:
    """主动丢弃未提交草稿（如关闭面板、放弃恢复）。"""
    return ActionResult(ok=True, message=service.discard_draft(entry_id, operator))


@router.get("/{entry_id}/history")
def list_history(entry_id: int) -> dict[str, Any]:
    """处理记录只增不改：返回该报销单的全部历史动作，供随时查阅。"""
    if service.get_entry(entry_id) is None:
        raise HTTPException(status_code=404, detail=f"报销单 {entry_id} 不存在或已归档")
    return {"items": service.list_history(entry_id)}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条报销单明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"报销单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条报销单，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="报销单已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: ActionPayload) -> ActionResult:
    """正式提交处理动作。

    - 多人处理同一报销单时以后提交为准；
    - 已打款为终态，任何后续动作都不会覆盖打款记录；
    - 同一 request_id 重试只生效一次，网络失败可安全重试；
    - 每次动作追加处理记录，原记录保持可查。
    """
    operator = (payload.operator or "值班管理员").strip() or "值班管理员"
    entry, message, replayed = service.run_action(
        entry_id,
        payload.action,
        operator=operator,
        note=payload.note,
        request_id=(payload.request_id or "").strip() or None,
    )
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry, replayed=replayed)
