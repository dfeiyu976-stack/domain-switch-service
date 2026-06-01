"""
对应文档 6.1 切换接口测试：SW-001 ~ SW-017

TODO: 需要 FastAPI TestClient + 完整 mock(form_client / oos_client / db)
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app

    return TestClient(app)


class TestNode1Path:
    def test_sw001_node1_normal_switch(self, client):
        """SW-001 节点1正常切换 → 200, code=0, OOS 被调用, 锁建立"""
        # TODO

    def test_sw002_biz_locked_triggers_rollback(self, client):
        """SW-002 同业务线已锁 → 4090, rollback_triggered=True"""
        # TODO

    def test_sw003_biz_blocked_by_global(self, client):
        """SW-003 全域锁存在 → 4091, rollback_triggered=True"""
        # TODO

    def test_sw004_global_blocked_by_biz(self, client):
        """SW-004 业务线锁存在,全域申请 → 4092, rollback_triggered=True"""
        # TODO

    def test_sw005_rollback_api_failure(self, client):
        """SW-005 冲突但回退接口失败 → rollback_result=failed, 紧急告警"""
        # TODO


class TestNode2Path:
    def test_sw006_node2_with_owned_lock(self, client):
        """SW-006 节点2: 锁仍由本申请持有 → 校验通过 → OOS 调用"""
        # TODO

    def test_sw007_node2_lock_lost(self, client):
        """SW-007 节点2: 锁丢失 → 409 + 告警"""
        # TODO


class TestNode3Path:
    def test_sw008_node3_releases_lock_on_success(self, client):
        """SW-008 节点3 OOS 成功 → 锁记录被删除"""
        # TODO


class TestIdempotency:
    def test_sw009_duplicate_call_returns_same_task(self, client):
        """SW-009 同 apply_id + node_1 调用2次 → 第二次返回首次结果"""
        # TODO


class TestErrorCases:
    def test_sw010_invalid_biz(self, client):
        """SW-010 非法业务线 → 400"""
        # TODO

    def test_sw011_unauthorized(self, client):
        """SW-011 错误 token → 401"""
        # TODO

    def test_sw012_oos_call_failure(self, client):
        """SW-012 OOS 调用异常 → 任务 failed + 告警"""
        # TODO

    def test_sw013_oos_execution_failed(self, client):
        """SW-013 OOS 异步返回 Failed → 锁保留 + 告警"""
        # TODO

    def test_sw014_form_platform_unreachable(self, client):
        """SW-014 反查发版平台失败 → 500"""
        # TODO

    def test_sw015_apply_id_not_found(self, client):
        """SW-015 applyId 不存在 → 500"""
        # TODO


class TestGlobalSwitch:
    def test_sw016_global_switch_normal(self, client):
        """SW-016 全域切换正常 → 走全域模板,不传 biz 参数"""
        # TODO


class TestConcurrency:
    def test_sw017_concurrent_node1_one_wins(self, client):
        """SW-017 两个申请同时通过审批 → 1成功, 1被拒并回退"""
        # TODO
