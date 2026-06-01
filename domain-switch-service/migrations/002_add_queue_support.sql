-- =====================================================
-- 002: 给 switch_task 加排队支持
-- 用途: 配合应用层"OOS 执行级串行化 + 队列"功能
-- 在已有库上一次性执行;新装库直接跑 init.sql 即可。
-- =====================================================

ALTER TABLE switch_task
    ADD COLUMN queued_at DATETIME NULL
        COMMENT '入队时间(status=queued 时记录, 用于 FIFO 排序和超时判定)'
        AFTER error_msg;

ALTER TABLE switch_task
    MODIFY COLUMN status VARCHAR(16) NOT NULL
        COMMENT 'pending/queued/running/success/failed/timeout/admin_forced';

ALTER TABLE switch_task
    ADD INDEX idx_queue (status, queued_at)
        COMMENT 'FIFO 队列查询: WHERE status=queued ORDER BY queued_at';
