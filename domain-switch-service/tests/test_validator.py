"""
对应文档 6.2 锁机制测试：LK-001 ~ LK-005

TODO: 初步骨架,需要引入数据库 fixture(测试库 / SQLite 内存 / mock SwitchLock)后补全
"""
from unittest.mock import patch

import pytest

from schemas.switch import ValidationResult
from service.validator import SwitchValidator


@pytest.fixture
def validator():
    return SwitchValidator()


class TestSingleBiz:
    def test_no_locks_allows_biz_switch(self, validator):
        """LK-001 业务线无任何锁 → 准入通过"""
        with patch("service.validator.SwitchLock") as MockLock:
            MockLock.query_by_key.return_value = None
            result = validator.validate("jd", apply_id="REQ001")
        assert isinstance(result, ValidationResult)
        assert result.allowed is True

    def test_biz_locked_by_other_apply_is_rejected(self, validator):
        """LK-005 同业务线第二个流程审批通过 → 被拒"""
        # TODO: 构造已有 jd 锁(apply_id=REQ001)的场景, 用 REQ002 申请, 期望 BIZ_LOCKED

    def test_biz_blocked_when_global_locked(self, validator):
        """LK-003 全域占用时 jd 审批通过 → 被拒"""
        # TODO: GLOBAL 锁存在, jd 申请 → BIZ_BLOCKED_BY_GLOBAL


class TestGlobal:
    def test_global_blocked_when_any_biz_locked(self, validator):
        """LK-002 jd 占用时全域审批通过 → 被拒"""
        # TODO: jd 锁存在, ALL 申请 → GLOBAL_BLOCKED_BY_BIZ

    def test_global_allowed_when_no_locks(self, validator):
        """全域且无锁 → 准入通过"""
        with patch("service.validator.SwitchLock") as MockLock:
            MockLock.query_all.return_value = []
            result = validator.validate("ALL", apply_id="REQ999")
        assert result.allowed is True
