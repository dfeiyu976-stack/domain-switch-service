"""
对应文档 6.2 / 6.3：LK-001 ~ LK-005, AD-005

TODO: 需要 Redis 测试 fixture (fakeredis) + 数据库 fixture
"""
import pytest


class TestAcquire:
    def test_acquire_new_lock(self):
        """空表加锁 → 创建成功"""
        # TODO

    def test_acquire_same_apply_updates_node(self):
        """同 apply_id 二次加锁 → 更新 current_node, 返回 True"""
        # TODO

    def test_acquire_other_apply_fails(self):
        """已被其他 apply_id 占用 → 加锁失败"""
        # TODO


class TestVerifyOwner:
    def test_verify_owner_returns_true_when_match(self):
        # TODO
        pass

    def test_verify_owner_returns_false_when_lost(self):
        """锁被运维强释放后 verify_owner = False (SW-007)"""
        # TODO


class TestRelease:
    def test_release_lock_by_owner(self):
        """节点3成功 → 持有者释放锁"""
        # TODO

    def test_release_lock_by_non_owner_noop(self):
        """非持有者尝试释放 → 不动锁,返回 False"""
        # TODO


class TestForceRelease:
    def test_force_release_existing_lock(self):
        # TODO
        pass

    def test_force_release_missing_lock_returns_false(self):
        """AD-005 强制解锁不存在的 lock_key → False"""
        # TODO
