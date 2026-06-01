-- =====================================================
-- 表1: switch_lock (业务线锁表)
-- 用途: 记录当前哪些业务线/全域正在被切换流程占用
-- =====================================================
CREATE TABLE switch_lock (
    lock_key     VARCHAR(32) PRIMARY KEY COMMENT '业务线名(jd/gnjp/...) 或 GLOBAL',
    apply_id     VARCHAR(64) NOT NULL COMMENT '持锁的申请单号',
    current_node VARCHAR(16) NOT NULL COMMENT '当前节点 node_1/node_2/node_3',
    operator     VARCHAR(64) NOT NULL COMMENT '持锁人',
    locked_at    DATETIME    NOT NULL COMMENT '加锁时间',
    updated_at   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_apply (apply_id)
) COMMENT='切换锁表 - 业务线/全域互斥';

-- =====================================================
-- 表2: switch_task (任务历史表)
-- 用途: 记录每次切换的完整历史,用于审计和排查
-- =====================================================
CREATE TABLE switch_task (
    id                BIGINT PRIMARY KEY AUTO_INCREMENT,
    task_id           VARCHAR(64) UNIQUE NOT NULL COMMENT '任务ID(系统生成)',
    apply_id          VARCHAR(64) NOT NULL COMMENT '发版申请单号',
    node_id           VARCHAR(16) NOT NULL COMMENT '节点 node_1/node_2/node_3',
    biz               VARCHAR(32) NOT NULL COMMENT '业务线 jd/gnjp/.../ALL',
    action            VARCHAR(16) NOT NULL COMMENT 'in1_out2/in2_out1/dual',
    operator          VARCHAR(64) NOT NULL COMMENT '触发人',
    oos_execution_id  VARCHAR(64) COMMENT '阿里云OOS执行ID',
    oos_template_name VARCHAR(64) COMMENT '使用的OOS模板名',
    status            VARCHAR(16) NOT NULL COMMENT 'pending/queued/running/success/failed/timeout/admin_forced',
    error_msg         TEXT COMMENT '失败原因',
    queued_at         DATETIME COMMENT '入队时间(status=queued 时记录, 用于 FIFO 排序和超时判定)',
    started_at        DATETIME COMMENT '开始时间(OOS 启动时, 即 status 转为 running 时)',
    finished_at       DATETIME COMMENT '结束时间',
    created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_apply_node (apply_id, node_id) COMMENT '幂等关键 - 同节点只能执行一次',
    INDEX idx_biz_created (biz, created_at),
    INDEX idx_status (status),
    INDEX idx_oos (oos_execution_id),
    INDEX idx_queue (status, queued_at) COMMENT 'FIFO 队列查询: WHERE status=queued ORDER BY queued_at'
) COMMENT='切换任务表 - 历史记录与审计';
