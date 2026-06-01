import uuid
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException

from config import ADMIN_TOKEN
from db.models import SwitchTask
from schemas.switch import ForceSwitchRequest, ReleaseLockRequest
from service.lock_manager import LockManager
from service.notifier import Notifier
from service.oos_client import OOSClient

router = APIRouter(prefix="/api/v1/admin")
lock_manager = LockManager()
oos_client = OOSClient()
notifier = Notifier()


def _check_admin(authorization: str) -> None:
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Invalid admin token")


@router.post("/force_switch")
def force_switch(
    req: ForceSwitchRequest, authorization: str = Header(...)
):
    """紧急强制切换 - 绕过业务锁机制, 但仍然遵守执行槽串行化。

    设计:即使是强切, 也不允许跟其他 OOS 并发执行(防 nginx race);
    若需要彻底接管, 先调 /admin/release_exec_slot 把槽清掉再切。
    """
    _check_admin(authorization)

    task_id = (
        f"TASK_FORCED_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
    )
    apply_id = req.ticket_id or task_id

    # 拿执行槽 (非阻塞, 拿不到直接拒)
    if not lock_manager.try_acquire_exec_slot(holder=task_id):
        current_holder = lock_manager.get_exec_slot_holder()
        raise HTTPException(
            status_code=409,
            detail=(
                f"执行槽被占 (holder={current_holder}), 不允许并发 OOS 执行。"
                f"如确需强制接管, 先调用 /api/v1/admin/release_exec_slot"
            ),
        )

    task = SwitchTask.create(
        task_id=task_id,
        apply_id=apply_id,
        node_id="admin",
        biz=req.biz.value,
        action=req.action.value,
        operator=req.operator,
        status="running",
        started_at=datetime.now(),
    )

    try:
        execution_id, template_name = oos_client.start_execution(
            req.action.value, req.biz.value
        )
        task.update(
            oos_execution_id=execution_id, oos_template_name=template_name
        )
    except Exception as e:
        # 启动失败: 释放执行槽 + 标失败
        lock_manager.release_exec_slot(holder=task_id)
        task.update(status="admin_forced", error_msg=str(e))
        notifier.urgent_alert(f"[强制切换OOS调用失败] {e}")
        raise HTTPException(status_code=500, detail=f"OOS调用失败: {e}")

    notifier.urgent_alert(
        "[强制切换执行]\n"
        f"业务线: {req.biz.value}\n"
        f"动作: {req.action.value}\n"
        f"操作人: {req.operator}\n"
        f"原因: {req.reason}\n"
        f"工单: {req.ticket_id}"
    )

    return {
        "code": 0,
        "task_id": task_id,
        "oos_execution_id": execution_id,
        "warning": (
            "已绕过业务锁, 仍占用执行槽。"
            "终态需运维手动跟踪 OOS 控制台, 完成后调 /admin/release_exec_slot"
        ),
    }


@router.post("/release_exec_slot")
def release_exec_slot(
    operator: str, reason: str, authorization: str = Header(...)
):
    """强制释放执行槽 (运维兜底, 用于槽被卡死时清理)。"""
    _check_admin(authorization)

    if len(reason) < 10:
        raise HTTPException(status_code=400, detail="reason 至少 10 个字符")

    released = lock_manager.force_release_exec_slot(operator, reason)

    notifier.urgent_alert(
        "[强制释放执行槽]\n"
        f"操作人: {operator}\n"
        f"原因: {reason}\n"
        f"结果: {'已释放' if released else '槽本来就空'}"
    )

    return {
        "code": 0,
        "released": released,
        "msg": "执行槽已释放" if released else "槽本来就空",
    }


@router.post("/release_lock")
def release_lock(
    req: ReleaseLockRequest, authorization: str = Header(...)
):
    """强制释放锁"""
    _check_admin(authorization)

    released = lock_manager.force_release(
        req.lock_key, req.operator, req.reason
    )

    notifier.urgent_alert(
        "[强制释放锁]\n"
        f"lock_key: {req.lock_key}\n"
        f"操作人: {req.operator}\n"
        f"原因: {req.reason}\n"
        f"结果: {'已释放' if released else '锁不存在'}"
    )

    return {
        "code": 0,
        "released": released,
        "msg": "锁已释放" if released else "锁不存在或已释放",
    }
