import logging

import httpx

from config import (
    FORM_PLATFORM_ROLLBACK_PATH,
    FORM_PLATFORM_TOKEN,
    FORM_PLATFORM_URL,
)

logger = logging.getLogger(__name__)


class FormPlatformClient:
    """飞书表单引擎客户端"""

    def __init__(self):
        self.base_url = FORM_PLATFORM_URL
        self.headers = {"Authorization": f"Bearer {FORM_PLATFORM_TOKEN}"}

    def get_apply_detail(self, apply_id: str) -> dict:
        """查询申请单详情"""
        url = f"{self.base_url}/api/openapi/instance/{apply_id}"
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=self.headers)
            resp.raise_for_status()
            data = resp.json()
        if data.get("code") != 0:
            raise Exception(f"查询申请单失败: {data.get('msg')}")
        return data["data"]

    def get_biz_and_operator(self, apply_id: str) -> tuple[str, str]:
        detail = self.get_apply_detail(apply_id)
        biz = detail.get("formData", {}).get("biz", "").strip()
        operator = detail.get("creator", {}).get("name", "unknown")
        if not biz:
            raise ValueError(f"申请单{apply_id}的biz字段为空")
        return biz, operator

    def rollback_node(self, apply_id: str, node_id: str, reason: str) -> bool:
        """
        调用表单引擎节点回退接口,将节点状态从"已通过"回退到"待审批"

        TODO: 接口路径和参数待飞书表单平台方确认,以下为预期实现
        预期能力:
        - 传入 apply_id, node_id
        - 平台将该节点回退到审批中状态
        - 审批人可以重新审批
        """
        url = f"{self.base_url}{FORM_PLATFORM_ROLLBACK_PATH}"
        payload = {
            "apply_id": apply_id,
            "node_id": node_id,
            "reason": reason,
        }
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, headers=self.headers, json=payload)
                resp.raise_for_status()
                data = resp.json()

            if data.get("code") == 0:
                logger.info(
                    f"节点回退成功: apply_id={apply_id}, node={node_id}"
                )
                return True
            else:
                logger.error(f"节点回退失败: {data.get('msg')}")
                return False
        except Exception as e:
            logger.error(f"调用节点回退接口异常: {e}")
            return False
