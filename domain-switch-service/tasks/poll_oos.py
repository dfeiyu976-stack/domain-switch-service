import asyncio
import logging
from datetime import datetime

from db.models import SwitchTask
from service.lock_manager import LockManager
from service.notifier import Notifier
from service.oos_client import OOSClient

logger = logging.getLogger(__name__)

oos_client = OOSClient()
lock_manager = LockManager()
notifier = Notifier()

# 同步 api.switch 里的同名常量, 避免循环 import
QUEUE_TIMEOUT_MINUTES = 30


async def poll_oos_result(
    task_id: str,
    execution_id: str,
    apply_id: str,
    biz: str,
    node_id: str,
) -> None:
    """轮询 OOS 执行结果, 终态后释放执行槽并 chain-start 下一个排队任务。"""
    max_polls = 60  # 10 分钟超时
    interval = 10
    terminal_status = None

    for _ in range(max_polls):
        await asyncio.sleep(interval)
        try:
            status = oos_client.get_status(execution_id)
        except Exception as e:
            logger.error(f"查询OOS状态失败: {e}")
            continue

        if status == "Success":
            task = SwitchTask.find_by_task_id(task_id)
            task.update(status="success", finished_at=datetime.now())
            logger.info(f"切换成功: task={task_id}")
            notifier.notify_success(task)

            # 节点3成功后释放业务锁
            if node_id == "node_3":
                lock_manager.release_lock(biz, apply_id)
            terminal_status = "success"
            break

        elif status in ("Failed", "Cancelled"):
            task = SwitchTask.find_by_task_id(task_id)
            task.update(
                status="failed",
                finished_at=datetime.now(),
                error_msg=f"OOS执行状态: {status}",
            )
            notifier.notify_failure(task, f"OOS 执行终态为 {status}")
            terminal_status = "failed"
            break

    if terminal_status is None:
        # 轮询超时
        task = SwitchTask.find_by_task_id(task_id)
        task.update(
            status="failed",
            finished_at=datetime.now(),
            error_msg="轮询超时",
        )
        notifier.notify_failure(
            task, f"轮询超时: {max_polls * interval}s 内未拿到终态"
        )

    # 不管成功失败超时, 都要释放执行槽 + 推进队列
    lock_manager.release_exec_slot(holder=task_id)
    await chain_start_next_queued()


async def chain_start_next_queued() -> None:
    """从队列里 FIFO 取下一个 queued 任务, 启动它的 OOS, 并触发新一轮轮询。

    设计:
    - 入口处先 sweep 超时任务, 避免 chain 拿到一个早就该 fail 的
    - 整个"取队头 + 拿执行槽 + 标 running"在 queue_decision 锁里保证原子
    - 启动 OOS 在锁外执行(可能耗时)
    - OOS 启动失败 → 把这条 task 标 failed, 递归继续推进队列下一个
    """
    with lock_manager.distributed_lock("queue_decision"):
        timed_out = SwitchTask.mark_queued_timeouts(threshold_minutes=QUEUE_TIMEOUT_MINUTES)
        for t in timed_out:
            notifier.urgent_alert(
                f"[排队超时] task={t.task_id}, biz={t.biz}, apply_id={t.apply_id}, "
                f"排队超过 {QUEUE_TIMEOUT_MINUTES} 分钟未启动, 已标 timeout"
            )

        next_task = SwitchTask.find_oldest_queued()
        if next_task is None:
            logger.info("queue 已空, chain 结束")
            return

        if not lock_manager.try_acquire_exec_slot(holder=next_task.task_id):
            # 极小概率: dlock 内还有人抢到槽? 不太可能。打 warning 让运维知道。
            logger.warning(
                f"chain-start 拿不到执行槽, 当前 holder={lock_manager.get_exec_slot_holder()}"
            )
            return

        next_task.update(status="running", started_at=datetime.now())

    # 锁外: 调 OOS
    try:
        execution_id, template_name = oos_client.start_execution(
            next_task.action, next_task.biz
        )
        next_task.update(
            oos_execution_id=execution_id, oos_template_name=template_name
        )
        logger.info(
            f"chain-start 已启动: task={next_task.task_id}, exec={execution_id}"
        )
    except Exception as e:
        # 启动失败: 释放槽 + 标失败 + 继续推进下一个
        lock_manager.release_exec_slot(holder=next_task.task_id)
        next_task.update(
            status="failed", error_msg=str(e), finished_at=datetime.now()
        )
        notifier.notify_failure(next_task, f"队列启动 OOS 失败: {e}")
        # 递归: 这条挂了, 试下一条
        await chain_start_next_queued()
        return

    # 启动 polling (fire-and-forget, 由 asyncio 事件循环托管)
    asyncio.create_task(
        poll_oos_result(
            next_task.task_id,
            execution_id,
            next_task.apply_id,
            next_task.biz,
            next_task.node_id,
        )
    )
