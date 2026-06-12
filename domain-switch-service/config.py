import os

# 服务
SERVICE_PORT = int(os.getenv("PORT", 8080))
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")    # 与发版平台约定的token
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")  # 运维管理接口token

# 数据库
DB_URL = os.getenv("DB_URL", "mysql+pymysql://user:pass@localhost/domain_switch")

# Redis (分布式锁)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# 阿里云
ALIYUN_AK = os.getenv("ALIYUN_AK")
ALIYUN_SK = os.getenv("ALIYUN_SK")
ALIYUN_REGION = os.getenv("ALIYUN_REGION", "cn-beijing")

# 发版平台
FORM_PLATFORM_URL = os.getenv("FORM_PLATFORM_URL")
FORM_PLATFORM_TOKEN = os.getenv("FORM_PLATFORM_TOKEN")
# TODO: 表单引擎节点回退接口路径,待平台方确认
FORM_PLATFORM_ROLLBACK_PATH = os.getenv("FORM_PLATFORM_ROLLBACK_PATH", "/api/openapi/node/rollback")

# 业务白名单
ALLOWED_BIZ = {"jd", "gnjp", "gjjp", "hcp", "car", "sp", "js", "meal", "common", "user", "ALL"}

# 节点到action的映射
NODE_ACTION_MAP = {
    "node_1": "in1_out2",
    "node_2": "in2_out1",
    "node_3": "dual",
}

# OOS模板名映射
TEMPLATE_MAP = {
    ("in1_out2", False): "DomainSwitch-Biz-In1Out2",
    ("in2_out1", False): "DomainSwitch-Biz-In2Out1",
    ("dual",     False): "DomainSwitch-Biz-Dual",
    ("in1_out2", True):  "DomainSwitch-All-In1Out2",
    ("in2_out1", True):  "DomainSwitch-All-In2Out1",
    ("dual",     True):  "DomainSwitch-All-Dual",
}

# 通知 (飞书自定义机器人 webhook)
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK")
