import logging
from typing import Optional

from db.models import SwitchLock
from schemas.switch import ValidationResult

logger = logging.getLogger(__name__)


class SwitchValidator:
    """切换准入校验器 - 实现三条互斥规则"""

    def validate(self, biz: str, apply_id: Optional[str] = None) -> ValidationResult:
        """
        三条互斥规则:
        1. 同一业务线只允许一个流程
        2. 业务线在切换时,不允许全域切换
        3. 全域在切换时,不允许业务线切换
        """
        if biz == "ALL":
            return self._validate_global(apply_id)
        else:
            return self._validate_single_biz(biz, apply_id)

    def _validate_global(self, apply_id: Optional[str]) -> ValidationResult:
        """规则3: 全域切换 → 不允许任何业务线锁存在"""
        all_locks = SwitchLock.query_all()

        others = [l for l in all_locks if l.apply_id != apply_id]
        if others:
            biz_list = [
                f"{l.lock_key}(单号{l.apply_id}, {l.operator})" for l in others
            ]
            return ValidationResult(
                allowed=False,
                code="GLOBAL_BLOCKED_BY_BIZ",
                msg=f"全域切换被拒: 以下业务线正在切换中: {', '.join(biz_list)}",
                detail={
                    "rule": "GLOBAL_BLOCKED_BY_BIZ",
                    "conflicting_locks": [l.to_dict() for l in others],
                    "suggestion": "请等待相关业务线完成切换后再提交",
                },
            )
        return ValidationResult(allowed=True, msg="全域切换准入通过")

    def _validate_single_biz(
        self, biz: str, apply_id: Optional[str]
    ) -> ValidationResult:
        """规则2 + 规则1"""
        # 规则2: 全域锁存在 → 业务线不能切
        global_lock = SwitchLock.query_by_key("GLOBAL")
        if global_lock and global_lock.apply_id != apply_id:
            return ValidationResult(
                allowed=False,
                code="BIZ_BLOCKED_BY_GLOBAL",
                msg=f"业务线[{biz}]切换被拒: 全域操作进行中(单号{global_lock.apply_id})",
                detail={
                    "rule": "BIZ_BLOCKED_BY_GLOBAL",
                    "global_lock": global_lock.to_dict(),
                    "suggestion": "请等待全域操作完成",
                },
            )

        # 规则1: 同业务线已被占用
        biz_lock = SwitchLock.query_by_key(biz)
        if biz_lock and biz_lock.apply_id != apply_id:
            return ValidationResult(
                allowed=False,
                code="BIZ_LOCKED",
                msg=f"业务线[{biz}]已被申请单{biz_lock.apply_id}占用",
                detail={
                    "rule": "BIZ_LOCKED",
                    "conflict_apply_id": biz_lock.apply_id,
                    "conflict_operator": biz_lock.operator,
                    "current_node": biz_lock.current_node,
                    "locked_at": biz_lock.locked_at.isoformat(),
                    "suggestion": f"请等待{biz_lock.apply_id}完成或联系{biz_lock.operator}",
                },
            )

        return ValidationResult(allowed=True, msg="单业务线切换准入通过")
