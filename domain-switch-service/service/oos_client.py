import json
import logging

from aliyunsdkcore.client import AcsClient
from aliyunsdkoos.request.v20190601.ListExecutionsRequest import ListExecutionsRequest
from aliyunsdkoos.request.v20190601.StartExecutionRequest import StartExecutionRequest

from config import ALIYUN_AK, ALIYUN_REGION, ALIYUN_SK, TEMPLATE_MAP

logger = logging.getLogger(__name__)


class OOSClient:
    def __init__(self):
        self.client = AcsClient(ALIYUN_AK, ALIYUN_SK, ALIYUN_REGION)

    def start_execution(self, action: str, biz: str) -> tuple[str, str]:
        is_all = biz == "ALL"
        template_name = TEMPLATE_MAP[(action, is_all)]

        req = StartExecutionRequest()
        req.set_TemplateName(template_name)
        if not is_all:
            req.set_Parameters(json.dumps({"biz": biz}))

        resp = self.client.do_action_with_exception(req)
        data = json.loads(resp)
        execution_id = data["Execution"]["ExecutionId"]
        logger.info(
            f"OOS执行启动: template={template_name}, exec={execution_id}, biz={biz}"
        )
        return execution_id, template_name

    def get_status(self, execution_id: str) -> str:
        # 用 ListExecutions(ExecutionId=xxx) 替代 GetExecutions,
        # 行为一致但权限名一目了然: 只需 RAM 权限 oos:ListExecutions。
        req = ListExecutionsRequest()
        req.set_ExecutionId(execution_id)
        resp = self.client.do_action_with_exception(req)
        data = json.loads(resp)
        exec_info = (
            data.get("Executions", [{}])[0] if data.get("Executions") else {}
        )
        return exec_info.get("Status", "Unknown")
