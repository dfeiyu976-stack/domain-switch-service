# domain-switch-service

接收飞书表单审批节点回调,通过阿里云 OOS 模板执行域名切换的 FastAPI 服务。

## 这个服务在做什么

业务场景:一次"域名切换"流程要走 3 个审批节点(node_1 → node_2 → node_3),每个节点通过时由飞书表单回调本服务,本服务接到回调后:

1. **校验**当前是否允许此切换(三条互斥规则)
2. **加锁**(防止其他申请单同时操作同一业务线)
3. **拿执行槽**(全局唯一,防止跨业务线并发改 nginx 等共享资源)
4. **启动阿里云 OOS 模板**执行真正的切换动作
5. **后台轮询** OOS 状态,完成后**释放执行槽 + 链式启动队列下一个**
6. 全部 3 个节点跑完后释放业务锁,流程结束

校验失败时会自动调表单平台的"节点回退"接口把审批节点退回"待审批"状态。

## 架构概览

```
飞书表单 node_X 审批通过
    │
    ▼  POST /api/v1/switch/node1|2|3
    │  Header: Authorization: Bearer <AUTH_TOKEN>
    │
    ▼ api/switch._switch()
1. 鉴权 + 幂等检查 (apply_id, node_id 唯一)
2. 反查表单平台拿 biz/operator
3. 三互斥规则校验 (node_1)
4. 加业务锁 (Redis 短锁 + MySQL 长锁)
5. 拿执行槽 (全局唯一 Redis 锁)
      │
      ├─ 槽空闲 → 立即跑 OOS, status=running
      └─ 槽被占 → 入队, status=queued, 等链式调度
6. 调阿里云 OOS StartExecution
7. 后台轮询 (tasks/poll_oos.py)
      │
      └─ 终态 → 释放执行槽 → 队列 FIFO 取下一个跑

node_3 成功后才释放业务锁
```

## 关键机制

### 三条互斥规则 (service/validator.py)

业务层面的互斥,保证审批流程的语义正确性:

| 场景 | 行为 |
|---|---|
| 同一业务线 (jd) 已有流程,jd 又来 | ❌ 拒绝 (`BIZ_LOCKED`) |
| 业务线 (jd) 切换中,全域 ALL 来 | ❌ 拒绝 (`GLOBAL_BLOCKED_BY_BIZ`) |
| 全域 ALL 切换中,业务线 (jd) 来 | ❌ 拒绝 (`BIZ_BLOCKED_BY_GLOBAL`) |

校验失败时自动调表单平台的节点回退接口把审批退回。

### 两层锁 (service/lock_manager.py)

| | Redis 分布式锁 `dlock:biz:xxx` | MySQL `switch_lock` 表 |
|---|---|---|
| 角色 | 临界区互斥(读+判断+写) | 业务状态记录(谁占用) |
| 生命周期 | 毫秒级 | 全程 node_1→node_3 (分钟到小时) |
| 存哪 | Redis 内存 | MySQL 持久 |

Redis 锁防 race condition,MySQL 锁记录"谁持有这条业务线"以供后续节点校验和运维查看。

### 执行槽 + FIFO 队列 (service/lock_manager.py + tasks/poll_oos.py)

为防止**不同业务线**同时启动 OOS 改同一份 nginx 配置造成 race,加了一把**全局唯一的执行槽锁** (`dlock:exec_slot`)。

- 任何时刻最多 1 个 OOS 在跑
- 后到的不同业务线申请单进入 FIFO 队列 (`switch_task` 表 `status=queued`)
- 前一个 OOS 完成 → 自动 chain-start 队列下一个
- 队列任务 30 分钟未启动 → 自动标 `timeout` + 告警

注意:**同业务线/全域互斥规则保留**,只有"不同业务线"的场景从原"立即并发"改为"排队执行"。

### 节点回退 (service/form_platform_client.py)

当 node_1 校验失败时,本服务会反向调用表单平台的 `rollback_node` 接口,把对应审批节点的状态从"已通过"退回"待审批",防止"审批通过但切换没真执行"的不一致状态。

## 技术栈

- **FastAPI** + **uvicorn** — HTTP 服务
- **SQLAlchemy 2.x** + **pymysql** — MySQL ORM
- **redis-py** — Redis 客户端 + 分布式锁
- **aliyun-python-sdk-oos** — 阿里云 OOS SDK
- **httpx** — 异步 HTTP 客户端(表单平台 / 钉钉)
- **python-dotenv** — `.env` 加载

详见 [`requirements.txt`](domain-switch-service/requirements.txt)。

## 目录结构

```
domain-switch-service/
├── main.py                    FastAPI 入口
├── config.py                  所有环境变量 + 业务常量 (ALLOWED_BIZ, TEMPLATE_MAP)
├── requirements.txt
├── .env.example               配置模板,复制为 .env 填实际值
│
├── api/
│   ├── switch.py              主流程: /switch/node1|2|3
│   ├── status.py              只读查询: /status, /tasks
│   └── admin.py               运维接口: /admin/force_switch, /admin/release_lock,
│                                       /admin/release_exec_slot
│
├── db/
│   ├── connection.py          SQLAlchemy engine + session_scope
│   └── models.py              SwitchLock + SwitchTask
│
├── schemas/
│   └── switch.py              Pydantic DTO + 枚举
│
├── service/
│   ├── validator.py           三互斥规则校验
│   ├── lock_manager.py        Redis 分布式锁 + MySQL 业务锁 + 执行槽锁
│   ├── oos_client.py          阿里云 OOS SDK 封装
│   ├── form_platform_client.py 飞书表单反查/节点回退
│   └── notifier.py            钉钉 webhook
│
├── tasks/
│   └── poll_oos.py            后台轮询 + 链式调度
│
├── migrations/
│   ├── init.sql               表结构 (新装库直接跑)
│   └── 002_add_queue_support.sql  增量: 加 queued_at 字段
│
└── tests/                     pytest 单元测试
```

## 快速开始

### 依赖

| 依赖 | 用途 | 备注 |
|---|---|---|
| MySQL 5.7+ / 8.0 | `switch_lock` + `switch_task` 两张表 | 跑 [migrations/init.sql](domain-switch-service/migrations/init.sql) |
| Redis 5+ | 分布式锁 + 执行槽 | 单机即可 |
| 阿里云 OOS | 实际执行模板 | 需要 RAM 子账号 AK/SK,权限至少 `oos:ListExecutions` + `oos:StartExecution` |
| 飞书表单平台 | 反查申请单 / 节点回退 | 平台方提供 base URL + token |
| 钉钉机器人 | 告警通知 | 可选,不填走 dry-run 日志 |

### 配置

复制 `.env.example` 为 `.env`,填入真实值:

```bash
cd domain-switch-service
cp .env.example .env
# 编辑 .env 填入各项配置
```

关键配置项见 [`.env.example`](domain-switch-service/.env.example) 和 [`config.py`](domain-switch-service/config.py)。**不要**把真实 `.env` 提交进 git。

### 启动

```bash
pip install -r requirements.txt
python main.py
# 服务默认监听 :8080, 健康检查 GET /health
```

### 数据库初始化

**新装库**:

```bash
mysql -u <user> -p <db_name> < migrations/init.sql
```

**已有库做版本升级**(早期没有队列字段的库):

```bash
mysql -u <user> -p <db_name> < migrations/002_add_queue_support.sql
```

## API 速查

### 业务接口(需 `Bearer <AUTH_TOKEN>`)

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/v1/switch/node1?applyId=<X>` | 第 1 节点回调(完整校验) |
| POST | `/api/v1/switch/node2?applyId=<X>` | 第 2 节点回调(仅校验锁所有权) |
| POST | `/api/v1/switch/node3?applyId=<X>` | 第 3 节点回调(成功后释放锁) |
| GET | `/api/v1/status` | 当前所有业务锁状态 |
| GET | `/api/v1/tasks?applyId=&biz=&status=&limit=` | 历史任务查询 |
| GET | `/health` | 健康检查 |

### 运维接口(需 `Bearer <ADMIN_TOKEN>`)

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/v1/admin/force_switch` | 紧急强切(绕过业务锁,守执行槽) |
| POST | `/api/v1/admin/release_lock` | 强制释放业务锁 |
| POST | `/api/v1/admin/release_exec_slot` | 强制释放执行槽 |

返回码约定(`/switch/nodeX`):

| code | 含义 |
|---|---|
| 0 | 成功(`detail.status` = `running` / `queued`) |
| 4090 | `BIZ_LOCKED` — 同业务线已被其他申请单占用 |
| 4091 | `BIZ_BLOCKED_BY_GLOBAL` — 全域操作进行中 |
| 4092 | `GLOBAL_BLOCKED_BY_BIZ` — 有业务线在切,全域被拒 |

## 数据模型

**switch_lock** — 业务线锁表,记录"谁正在用这条业务线":

```
lock_key (PK)      业务线名 或 GLOBAL
apply_id           持锁的申请单号
current_node       当前节点
operator           持锁人
locked_at          加锁时间
```

**switch_task** — 任务历史,审计 + 队列:

```
task_id (UK)       系统生成
apply_id, node_id  幂等关键 (UNIQUE)
biz, action
oos_execution_id   阿里云 OOS 执行 ID
status             pending / queued / running / success / failed / timeout / admin_forced
queued_at          入队时间 (FIFO 排序 + 超时判定)
started_at, finished_at
```

## 已知局限 / 未来改进

- **`BackgroundTasks` 进程内存活** — 当前轮询用 FastAPI `BackgroundTasks`,进程重启会丢失正在轮询的任务,业务锁 + 执行槽会卡死直到 admin 手动释放。生产部署建议:启动时扫 `status=running` 续上轮询,或换 Celery / APScheduler。
- **业务锁无 TTL** — `switch_lock` 没有过期时间字段,异常崩溃后需要 admin 手动 `release_lock`。
- **飞书 OpenAPI token 续期** — 如果对接的是飞书原生 OpenAPI,`tenant_access_token` 2 小时过期,当前实现把 token 当静态值,需补刷新逻辑。
- **OOS 模板版本** — 现在 `StartExecution` 用 `Latest`,运维改模板会无感知影响业务,生产建议显式 pin 版本。
- **同步 SDK 阻塞 async loop** — 阿里云 SDK 是同步的,在 async 轮询里建议包 `asyncio.to_thread`。

## 开发提示

- **本地联调**:`.env` 里配上 dev MySQL / 本地 Docker Redis / 阿里云 dev RAM 子账号,先跑 `python main.py` 启动,再 curl 调 `/health` `/status`。
- **OOS 联调**:不要直接用生产 6 个 `DomainSwitch-*` 模板,让运维提供一个 `DomainSwitch-Smoke` 之类的无副作用模板(只 `ACS::Sleep`),用它做参数透传 + 启动 + 轮询的端到端验证。
- **测试约定**:本地一次性冒烟测试脚本命名为 `_*.py`(已加进 `.gitignore`),不进 git。
