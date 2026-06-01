from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query

from db.connection import session_scope
from db.models import SwitchLock, SwitchTask

router = APIRouter(prefix="/api/v1")


@router.get("/status")
def get_status():
    """查看当前各业务线和全域的锁定状态"""
    locks = SwitchLock.query_all()
    now = datetime.now()

    lock_list = []
    longest = 0
    global_locked = False
    for lock in locks:
        duration = (
            int((now - lock.locked_at).total_seconds() / 60)
            if lock.locked_at
            else 0
        )
        if duration > longest:
            longest = duration
        if lock.lock_key == "GLOBAL":
            global_locked = True
        lock_list.append(
            {
                "lock_key": lock.lock_key,
                "apply_id": lock.apply_id,
                "operator": lock.operator,
                "current_node": lock.current_node,
                "locked_at": lock.locked_at.isoformat()
                if lock.locked_at
                else None,
                "duration_minutes": duration,
            }
        )

    return {
        "code": 0,
        "data": {
            "locks": lock_list,
            "global_locked": global_locked,
            "summary": {
                "total_locks": len(lock_list),
                "longest_holding_minutes": longest,
            },
        },
    }


@router.get("/tasks")
def list_tasks(
    applyId: Optional[str] = Query(None),
    biz: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    """查询历史任务记录"""
    with session_scope() as s:
        q = s.query(SwitchTask)
        if applyId:
            q = q.filter(SwitchTask.apply_id == applyId)
        if biz:
            q = q.filter(SwitchTask.biz == biz)
        if status:
            q = q.filter(SwitchTask.status == status)
        rows = q.order_by(SwitchTask.created_at.desc()).limit(limit).all()
        data = [r.to_dict() for r in rows]

    return {"code": 0, "data": data}
