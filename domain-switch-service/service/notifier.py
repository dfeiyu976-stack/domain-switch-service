import logging

import httpx

from config import DINGTALK_WEBHOOK

logger = logging.getLogger(__name__)


class Notifier:
    """通知模块 - 钉钉/飞书 webhook 封装"""

    def _send(self, content: str) -> None:
        if not DINGTALK_WEBHOOK:
            logger.info(f"[NOTIFY-DRYRUN] {content}")
            return
        try:
            with httpx.Client(timeout=5.0) as client:
                client.post(
                    DINGTALK_WEBHOOK,
                    json={"msgtype": "text", "text": {"content": content}},
                )
        except Exception as e:
            logger.error(f"通知发送失败: {e}")

    def alert_conflict(
        self,
        apply_id: str,
        biz: str,
        node_id: str,
        msg: str,
        rollback_ok: bool,
    ) -> None:
        rollback_status = "成功" if rollback_ok else "失败"
        self._send(
            "[切换冲突告警]\n"
            f"申请单: {apply_id}\n"
            f"业务线: {biz}\n"
            f"节点: {node_id}\n"
            f"原因: {msg}\n"
            f"节点回退: {rollback_status}"
        )

    def urgent_alert(self, msg: str) -> None:
        self._send(f"[紧急告警]\n{msg}")

    def notify_success(self, apply_id: str, biz: str, node_id: str) -> None:
        self._send(
            "[切换成功]\n"
            f"申请单: {apply_id}\n"
            f"业务线: {biz}\n"
            f"节点: {node_id}"
        )
