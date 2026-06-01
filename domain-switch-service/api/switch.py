import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query

from config import ALLOWED_BIZ, AUTH_TOKEN, NODE_ACTION_MAP
from db.models import SwitchTask
from schemas.switch import SwitchResponse
from service.form_platform_client import FormPlatformClient
from service.lock_manager import LockManager
from service.notifier import Notifier
from service.oos_client import OOSClient
from service.validator import SwitchValidator
from tasks.poll_oos import poll_oos_result

router = APIRouter(prefix="/api/v1")
validator = SwitchValidator()
lock_manager = LockManager()
oos_client = OOSClient()
form_client = FormPlatformClient()
notifier = Notifier()

# 队列中超过这个时长还没启动 OOS 的任务自动标 timeout 失败,
# 防止前面任务挂死导致队列无限堆积。
QUEUE_TIMEOUT_MINUTES = 30


@router.post("/switch/node1")
async def switch_node1(
    background_tasks: BackgroundTasks,
    applyId: str = Query(...),
    authorization: str = Header(...),
):
    return await _switch(applyId, "node_1", background_tasks, authorization)


@router.post("/switch/node2")
async def switch_node2(
    background_tasks: BackgroundTasks,
    applyId: str = Query(...),
    authorization: str = Header(...),
):
    return await _switch(applyId, "node_2", background_tasks, authorization)


@router.post("/switch/node3")
async def switch_node3(
    background_tasks: BackgroundTasks,
    applyId: str = Query(...),
    authorization: str = Header(...),
):
    return await _switch(applyId, "node_3", background_tasks, authorization)


async def _switch(
    apply_id: str,
    node_id: str,
    background_tasks: BackgroundTasks,
    authorization: str,
) -> SwitchResponse:
    """
    审批节点通过后的执行入口
    流程:
      1. 鉴权 + 幂等检查
      2. 反查表单拿到 biz
      3. 执行前校验(三条互斥规则)
         - 校验不通过 → 调用表单引擎回退接口 → 返回 409
      4. 加锁
      5. 调用 OOS 异步执行
    """
    if authorization != f"Bearer {AUTH_TOKEN}":
        raise HTTPException(status_code=401, detail="Invalid token")

    # 1. 幂等检查
    existing = SwitchTask.find_by_apply_node(apply_id, node_id)
    if existing:
        return SwitchResponse(
            code=0,
            task_id=existing.task_id,
            oos_execution_id=existing.oos_execution_id,
            biz=existing.biz,
            action=existing.action,
            msg="任务已存在(幂等返回)",
        )

    # 2. 反查表单
    try:
        biz, operator = form_client.get_biz_and_operator(apply_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询申请单失败: {e}")

    if biz not in ALLOWED_BIZ:
        raise HTTPException(status_code=400, detail=f"非法业务线: {biz}")

    action = NODE_ACTION_MAP[node_id]

    # 3. 执行前校验
    if node_id == "node_1":
        # 节点1: 完整校验三条互斥规则
        result = validator.validate(biz, apply_id)
        if not result.allowed:
            # 校验失败 → 调用表单引擎回退接口
            rollback_ok = form_client.rollback_node(
                apply_id=apply_id,
                node_id=node_id,
                reason=f"切换冲突: {result.msg}",
            )

            notifier.alert_conflict(
                apply_id, biz, node_id, result.msg, rollback_ok
            )

            # 错误码映射: BIZ_LOCKED=4090, BIZ_BLOCKED_BY_GLOBAL=4091, GLOBAL_BLOCKED_BY_BIZ=4092
            code_map = {
                "BIZ_LOCKED": 4090,
                "BIZ_BLOCKED_BY_GLOBAL": 4091,
                "GLOBAL_BLOCKED_BY_BIZ": 4092,
            }
            return SwitchResponse(
                code=code_map.get(result.code, 4090),
                msg=result.msg,
                rollback_triggered=True,
                rollback_result="success" if rollback_ok else "failed",
                detail=result.detail,
            )

        # 校验通过 → 加锁
        if not lock_manager.acquire_biz_lock(biz, apply_id, node_id, operator):
            # 极小概率: 校验通过但加锁失败(并发) → 也走回退
            rollback_ok = form_client.rollback_node(
                apply_id=apply_id,
                node_id=node_id,
                reason="并发加锁失败",
            )
            return SwitchResponse(
                code=4090,
                msg="并发加锁失败,已触发节点回退",
                rollback_triggered=True,
                rollback_result="success" if rollback_ok else "failed",
            )
    else:
        # 节点2/3: 验证锁仍由本申请持有
        if not lock_manager.verify_owner(biz, apply_id):
            # 锁丢失(异常情况) → 告警,不回退(因为前节点已执行)
            notifier.urgent_alert(
                f"[锁状态异常] apply_id={apply_id}, biz={biz}, node={node_id}"
            )
            raise HTTPException(status_code=409, detail="锁状态异常,请联系运维")

    # 4. 创建任务记录(暂时不定状态, 由下面决定 running / queued)
    task_id = f"TASK_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
    task = SwitchTask.create(
        task_id=task_id,
        apply_id=apply_id,
        node_id=node_id,
        biz=biz,
        action=action,
        operator=operator,
        status="pending",
    )

    # 5. 决定立即执行还是排队 (queue_decision 临界区)
    # 规则: 队列非空 或 执行槽被占 → 排队 (status=queued)
    #       队列空 且 槽空闲     → 拿槽立即跑 (status=running)
    with lock_manager.distributed_lock("queue_decision"):
        # 顺手清理超时的 queued 任务(lazy sweep)
        SwitchTask.mark_queued_timeouts(threshold_minutes=QUEUE_TIMEOUT_MINUTES)

        queued_count = SwitchTask.count_queued()
        slot_busy = lock_manager.get_exec_slot_holder() is not None

        if queued_count > 0 or slot_busy:
            task.update(status="queued", queued_at=datetime.now())
            return SwitchResponse(
                code=0,
                task_id=task_id,
                biz=biz,
                action=action,
                msg=f"切换任务已入队, 前面有 {queued_count} 个等待中",
                detail={
                    "status": "queued",
                    "queue_position": queued_count + 1,
                    "current_slot_holder": lock_manager.get_exec_slot_holder(),
                },
            )

        # 队列空 + 槽空 → 拿槽
        if not lock_manager.try_acquire_exec_slot(holder=task_id):
            # 竞争失败 (极小概率, 因为我们在 dlock 里), 兜底也排队
            task.update(status="queued", queued_at=datetime.now())
            return SwitchResponse(
                code=0,
                task_id=task_id,
                biz=biz,
                action=action,
                msg="切换任务已入队 (槽竞争失败)",
                detail={"status": "queued", "queue_position": 1},
            )

        task.update(status="running", started_at=datetime.now())

    # 6. 调 OOS (在 queue_decision 锁外执行, 避免持锁时间过长)
    try:
        execution_id, template_name = oos_client.start_execution(action, biz)
        task.update(
            oos_execution_id=execution_id, oos_template_name=template_name
        )
    except Exception as e:
        # 启动失败: 释放执行槽 + 标记 task 失败 + 顺势启动队列下一个
        lock_manager.release_exec_slot(holder=task_id)
        task.update(status="failed", error_msg=str(e), finished_at=datetime.now())
        notifier.urgent_alert(
            f"[OOS调用失败] apply_id={apply_id}, error={e}"
        )
        # 异步触发 chain-start (导入放在函数内避免循环引用)
        from tasks.poll_oos import chain_start_next_queued
        background_tasks.add_task(chain_start_next_queued)
        raise HTTPException(status_code=500, detail=f"OOS调用失败: {e}")

    # 7. 异步轮询
    background_tasks.add_task(
        poll_oos_result, task_id, execution_id, apply_id, biz, node_id
    )

    return SwitchResponse(
        code=0,
        task_id=task_id,
        oos_execution_id=execution_id,
        biz=biz,
        action=action,
        msg="切换任务已提交,异步执行中",
        detail={"status": "running"},
    )
