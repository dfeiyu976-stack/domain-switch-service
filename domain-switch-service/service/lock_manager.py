import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

import redis

from config import REDIS_URL
from db.models import SwitchLock

logger = logging.getLogger(__name__)

r = redis.from_url(REDIS_URL, decode_responses=True)

# 全局唯一的"OOS 执行槽" Redis key。
# 设计:任何时刻最多 1 个 OOS 在跑,防止两个不同业务线的云助手脚本
# 同时去改 nginx.conf 等共享资源(应用层串行,资源层 flock 兜底)。
EXEC_SLOT_KEY = "exec_slot"
# TTL: OOS 执行最长时间预留 + 缓冲。略大于 poll_oos 的 60 轮 × 10s = 600s。
# 真实 OOS 跑超过这个时间会被算"挂住", lock 自动过期让队列继续推进。
EXEC_SLOT_TTL_SECONDS = 900

# Lua 脚本:仅在 holder 匹配时才删除 key, 避免误释放别人的锁。
_RELEASE_SLOT_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""
_release_slot_script = r.register_script(_RELEASE_SLOT_LUA)


class LockManager:
    """锁管理 - 含分布式锁防并发"""

    @contextmanager
    def distributed_lock(self, key: str, timeout: int = 10):
        lock_name = f"dlock:{key}"
        lock = r.lock(lock_name, timeout=timeout, blocking_timeout=5)
        acquired = lock.acquire()
        try:
            if not acquired:
                raise Exception(f"无法获取分布式锁: {key}")
            yield
        finally:
            try:
                lock.release()
            except Exception:
                pass

    def acquire_biz_lock(
        self, biz: str, apply_id: str, node_id: str, operator: str
    ) -> bool:
        lock_key = "GLOBAL" if biz == "ALL" else biz

        with self.distributed_lock(f"biz:{lock_key}"):
            existing = SwitchLock.query_by_key(lock_key)

            if existing:
                if existing.apply_id == apply_id:
                    existing.current_node = node_id
                    existing.save()
                    return True
                else:
                    logger.warning(
                        f"锁已被占用: {lock_key} by {existing.apply_id}"
                    )
                    return False

            SwitchLock.create(
                lock_key=lock_key,
                apply_id=apply_id,
                current_node=node_id,
                operator=operator,
                locked_at=datetime.now(),
            )
            logger.info(f"加锁成功: {lock_key} -> {apply_id}")
            return True

    def verify_owner(self, biz: str, apply_id: str) -> bool:
        lock_key = "GLOBAL" if biz == "ALL" else biz
        lock = SwitchLock.query_by_key(lock_key)
        return lock is not None and lock.apply_id == apply_id

    def release_lock(self, biz: str, apply_id: str) -> bool:
        lock_key = "GLOBAL" if biz == "ALL" else biz
        with self.distributed_lock(f"biz:{lock_key}"):
            lock = SwitchLock.query_by_key(lock_key)
            if lock and lock.apply_id == apply_id:
                lock.delete()
                logger.info(f"锁已释放: {lock_key} (apply_id={apply_id})")
                return True
            return False

    def force_release(self, lock_key: str, operator: str, reason: str) -> bool:
        with self.distributed_lock(f"biz:{lock_key}"):
            lock = SwitchLock.query_by_key(lock_key)
            if lock:
                logger.warning(
                    f"强制释放锁: {lock_key}, 原持有={lock.apply_id}, "
                    f"操作人={operator}, 原因={reason}"
                )
                lock.delete()
                return True
            return False

    # ============================================
    # 执行槽锁 (OOS 串行化, 防 nginx 资源 race)
    # ============================================

    def try_acquire_exec_slot(
        self, holder: str, ttl_seconds: int = EXEC_SLOT_TTL_SECONDS
    ) -> bool:
        """非阻塞拿执行槽。拿到返回 True 立即调 OOS;拿不到返回 False 排队。

        holder: 通常用 task_id, 用于 release 时校验所有者。
        """
        slot_key = f"dlock:{EXEC_SLOT_KEY}"
        got = r.set(slot_key, holder, nx=True, ex=ttl_seconds)
        if got:
            logger.info(f"执行槽 acquired: holder={holder}, ttl={ttl_seconds}s")
        return bool(got)

    def release_exec_slot(self, holder: str) -> bool:
        """释放执行槽。仅当当前持有者匹配时才释放(避免误释放)。"""
        slot_key = f"dlock:{EXEC_SLOT_KEY}"
        result = _release_slot_script(keys=[slot_key], args=[holder])
        if result:
            logger.info(f"执行槽 released: holder={holder}")
        else:
            logger.warning(
                f"执行槽释放失败 (持有者已变更或已过期): expected_holder={holder}, "
                f"current={r.get(slot_key)}"
            )
        return bool(result)

    def get_exec_slot_holder(self) -> Optional[str]:
        """诊断用: 看当前执行槽被谁占着。"""
        return r.get(f"dlock:{EXEC_SLOT_KEY}")

    def force_release_exec_slot(self, operator: str, reason: str) -> bool:
        """运维强释放执行槽,不校验 holder。"""
        slot_key = f"dlock:{EXEC_SLOT_KEY}"
        current = r.get(slot_key)
        if current:
            r.delete(slot_key)
            logger.warning(
                f"强制释放执行槽: 原持有={current}, 操作人={operator}, 原因={reason}"
            )
            return True
        return False
