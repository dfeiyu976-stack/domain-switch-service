import logging

import httpx

from config import FEISHU_WEBHOOK, NODE_ACTION_MAP

logger = logging.getLogger(__name__)

# action 业务语义 (给人看的): 内1外2 / 内2外1 / 双
ACTION_LABEL = {
    "in1_out2": "内1外2",
    "in2_out1": "内2外1",
    "dual": "双",
}


def _action_label(action: str) -> str:
    return ACTION_LABEL.get(action, action or "?")


class Notifier:
    """通知模块 - 飞书自定义机器人 webhook 封装"""

    def _send(self, content: str) -> None:
        if not FEISHU_WEBHOOK:
            logger.info(f"[NOTIFY-DRYRUN] {content}")
            return
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(
                    FEISHU_WEBHOOK,
                    json={"msg_type": "text", "content": {"text": content}},
                )
            # 飞书即使 HTTP 200 也可能业务失败 (code != 0), 需看 body
            body = resp.json()
            if body.get("code", body.get("StatusCode", 0)) != 0:
                logger.error(f"飞书通知被拒: {body}")
        except Exception as e:
            logger.error(f"通知发送失败: {e}")

    def notify_success(self, task) -> None:
        """切换成功通知。一眼看清: 哪个业务线、切了什么动作、流程到哪一步。"""
        finished = (
            task.finished_at.strftime("%Y-%m-%d %H:%M:%S")
            if task.finished_at
            else "-"
        )
        # node_3(双)是流程最后一步, 成功即整体完成并释放业务锁
        if task.node_id == "node_3":
            progress = "整体切换流程已完成 ✅ (业务锁已释放)"
        else:
            progress = "当前步骤完成, 流程进行中 (等待后续节点)"
        self._send(
            f"✅ 切换成功 | 业务线 {task.biz}\n"
            f"动作: {_action_label(task.action)} ({task.node_id})\n"
            f"状态: {progress}\n"
            f"操作人: {task.operator}\n"
            f"完成时间: {finished}\n"
            f"任务号: {task.task_id}\n"
            f"执行号: {task.oos_execution_id or '-'}"
        )

    def notify_failure(self, task, reason: str) -> None:
        """切换失败告警。定位优先: 带 exec_id + 模板 + 排查指引。"""
        lines = [
            f"🔴 切换失败告警 | 业务线 {task.biz}",
            f"动作: {_action_label(task.action)} ({task.node_id})",
            f"失败原因: {reason}",
            f"申请单: {task.apply_id}",
            f"任务号: {task.task_id}",
        ]
        if task.oos_execution_id:
            lines.append(f"执行号: {task.oos_execution_id}")
            lines.append(f"模板: {task.oos_template_name or '-'}")
            lines.append(
                f"排查: 阿里云 OOS 控制台 → 执行管理 → 搜 {task.oos_execution_id}"
            )
        else:
            lines.append("执行号: 未生成 (OOS 启动阶段就失败)")
            lines.append("排查: 检查 AK/SK、网络连通、模板是否存在")
        lines.append("⚠️ 业务锁未释放, 需运维确认后手动处理")
        self._send("\n".join(lines))

    def alert_conflict(
        self,
        apply_id: str,
        biz: str,
        node_id: str,
        msg: str,
        rollback_ok: bool,
    ) -> None:
        action = NODE_ACTION_MAP.get(node_id, "")
        rollback_status = "成功" if rollback_ok else "失败"
        self._send(
            "[切换冲突告警]\n"
            f"业务线: {biz} (动作 {_action_label(action)})\n"
            f"申请单: {apply_id}\n"
            f"节点: {node_id}\n"
            f"原因: {msg}\n"
            f"节点回退: {rollback_status}"
        )

    def urgent_alert(self, msg: str) -> None:
        self._send(f"[紧急告警]\n{msg}")
