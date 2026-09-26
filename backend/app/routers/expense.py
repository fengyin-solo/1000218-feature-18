"""费用报销接口：维护报销单、处理草稿、幂等动作和处理日志。"""
from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Header, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.expense import ExpenseService

router = APIRouter(prefix="/api/expense", tags=["费用报销"])

service = ExpenseService()

LIST_FIELDS = ["报销单号", "报销人", "费用类别", "发生日期", "报销金额", "票据张数", "所属科目", "报销状态"]
STATUSES = ["待提交", "待审核", "已通过", "已驳回", "已打款"]


def current_operator(x_operator: str | None) -> str:
    return unquote((x_operator or "值班管理员").strip()) or "值班管理员"


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


@router.get("/drafts", response_model=list[dict])
def list_drafts(x_operator: str | None = Header(default=None)) -> list[dict[str, Any]]:
    """列出当前处理人尚未提交的报销处理草稿。"""
    return service.list_drafts(current_operator(x_operator))


@router.put("/{entry_id}/draft", response_model=ActionResult)
def save_draft(
    entry_id: int,
    payload: EntryPayload,
    x_operator: str | None = Header(default=None),
) -> ActionResult:
    """保存未完成的动作选择、补充说明和当前所在位置。"""
    draft, message = service.save_draft(entry_id, current_operator(x_operator), payload.values)
    if draft is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=draft)


@router.get("/{entry_id}/draft", response_model=ActionResult)
def get_draft(
    entry_id: int,
    x_operator: str | None = Header(default=None),
) -> ActionResult:
    """恢复草稿；正式处理后草稿会被清掉，接口明确返回未找到。"""
    draft = service.get_draft(entry_id, current_operator(x_operator))
    if draft is None:
        return ActionResult(ok=False, message="未找到未提交草稿")
    return ActionResult(ok=True, message="已恢复未提交草稿", entry=draft)


@router.delete("/{entry_id}/draft", response_model=ActionResult)
def delete_draft(
    entry_id: int,
    x_operator: str | None = Header(default=None),
) -> ActionResult:
    """主动放弃草稿。"""
    removed = service.delete_draft(entry_id, current_operator(x_operator))
    return ActionResult(ok=removed, message="草稿已清除" if removed else "草稿不存在或已随正式处理失效")


@router.get("/{entry_id}/history", response_model=list[dict])
def list_history(entry_id: int) -> list[dict[str, Any]]:
    """查看只追加、不覆盖的原始处理记录。"""
    history = service.list_history(entry_id)
    if history is None:
        raise HTTPException(status_code=404, detail=f"报销单 {entry_id} 不存在或已归档")
    return history


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict[str, Any]:
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
def run_action(
    entry_id: int,
    payload: EntryPayload,
    x_operator: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
) -> ActionResult:
    """执行正式处理；相同 request_id 重试不重复落日志，已打款记录不可覆盖。"""
    action = str(payload.values.get("action") or "").strip()
    raw_version = payload.values.get("expected_version")
    try:
        expected_version = None if raw_version in (None, "") else int(raw_version)
    except (TypeError, ValueError):
        return ActionResult(ok=False, message="处理版本号格式不正确，请刷新后重试")

    entry, message, meta = service.run_action(
        entry_id,
        action,
        remark=payload.remark or str(payload.values.get("remark") or ""),
        operator=current_operator(x_operator),
        expected_version=expected_version,
        request_id=x_request_id or str(payload.values.get("request_id") or ""),
    )
    if entry is None:
        return ActionResult(ok=False, message=message, conflict=bool(meta.get("conflict")))
    return ActionResult(
        ok=True,
        message=message,
        entry=entry,
        conflict=bool(meta.get("conflict")),
        duplicate=bool(meta.get("duplicate")),
        request_id=meta.get("request_id"),
    )


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出费用报销清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "expense", "total": total, "items": items}
