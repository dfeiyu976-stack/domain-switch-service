from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
)

from db.connection import Base, session_scope


class SwitchLock(Base):
    """业务线锁表 - 记录当前哪些业务线/全域正在被切换流程占用"""

    __tablename__ = "switch_lock"

    lock_key = Column(String(32), primary_key=True)
    apply_id = Column(String(64), nullable=False)
    current_node = Column(String(16), nullable=False)
    operator = Column(String(64), nullable=False)
    locked_at = Column(DateTime, nullable=False)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )

    __table_args__ = (Index("idx_apply", "apply_id"),)

    def to_dict(self) -> dict:
        return {
            "lock_key": self.lock_key,
            "apply_id": self.apply_id,
            "current_node": self.current_node,
            "operator": self.operator,
            "locked_at": self.locked_at.isoformat() if self.locked_at else None,
        }

    @classmethod
    def query_all(cls) -> List["SwitchLock"]:
        with session_scope() as s:
            rows = s.query(cls).all()
            for r in rows:
                s.expunge(r)
            return rows

    @classmethod
    def query_by_key(cls, key: str) -> Optional["SwitchLock"]:
        with session_scope() as s:
            row = s.query(cls).filter(cls.lock_key == key).one_or_none()
            if row is not None:
                s.expunge(row)
            return row

    @classmethod
    def create(cls, **kwargs) -> "SwitchLock":
        with session_scope() as s:
            row = cls(**kwargs)
            s.add(row)
            s.flush()
            s.expunge(row)
            return row

    def save(self) -> None:
        with session_scope() as s:
            s.merge(self)

    def delete(self) -> None:
        with session_scope() as s:
            s.query(SwitchLock).filter(SwitchLock.lock_key == self.lock_key).delete()


class SwitchTask(Base):
    """任务历史表 - 记录每次切换的完整历史,用于审计和排查"""

    __tablename__ = "switch_task"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_id = Column(String(64), unique=True, nullable=False)
    apply_id = Column(String(64), nullable=False)
    node_id = Column(String(16), nullable=False)
    biz = Column(String(32), nullable=False)
    action = Column(String(16), nullable=False)
    operator = Column(String(64), nullable=False)
    oos_execution_id = Column(String(64))
    oos_template_name = Column(String(64))
    status = Column(String(16), nullable=False)
    error_msg = Column(Text)
    queued_at = Column(DateTime)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("apply_id", "node_id", name="uk_apply_node"),
        Index("idx_biz_created", "biz", "created_at"),
        Index("idx_status", "status"),
        Index("idx_oos", "oos_execution_id"),
        Index("idx_queue", "status", "queued_at"),
    )

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "apply_id": self.apply_id,
            "node_id": self.node_id,
            "biz": self.biz,
            "action": self.action,
            "operator": self.operator,
            "oos_execution_id": self.oos_execution_id,
            "oos_template_name": self.oos_template_name,
            "status": self.status,
            "error_msg": self.error_msg,
            "queued_at": self.queued_at.isoformat() if self.queued_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def find_by_apply_node(
        cls, apply_id: str, node_id: str
    ) -> Optional["SwitchTask"]:
        with session_scope() as s:
            row = (
                s.query(cls)
                .filter(cls.apply_id == apply_id, cls.node_id == node_id)
                .one_or_none()
            )
            if row is not None:
                s.expunge(row)
            return row

    @classmethod
    def find_by_task_id(cls, task_id: str) -> Optional["SwitchTask"]:
        with session_scope() as s:
            row = s.query(cls).filter(cls.task_id == task_id).one_or_none()
            if row is not None:
                s.expunge(row)
            return row

    @classmethod
    def create(cls, **kwargs) -> "SwitchTask":
        with session_scope() as s:
            row = cls(**kwargs)
            s.add(row)
            s.flush()
            s.expunge(row)
            return row

    def update(self, **kwargs) -> None:
        with session_scope() as s:
            row = s.query(SwitchTask).filter(SwitchTask.task_id == self.task_id).one()
            for k, v in kwargs.items():
                setattr(row, k, v)
        for k, v in kwargs.items():
            setattr(self, k, v)

    @classmethod
    def find_oldest_queued(cls) -> Optional["SwitchTask"]:
        """FIFO: 取最早入队的 queued 任务,用于 chain-start。"""
        with session_scope() as s:
            row = (
                s.query(cls)
                .filter(cls.status == "queued")
                .order_by(cls.queued_at.asc())
                .first()
            )
            if row is not None:
                s.expunge(row)
            return row

    @classmethod
    def count_queued(cls) -> int:
        """返回当前 queued 任务数, 用于 queue_position 计算。"""
        with session_scope() as s:
            return s.query(cls).filter(cls.status == "queued").count()

    @classmethod
    def mark_queued_timeouts(cls, threshold_minutes: int) -> List["SwitchTask"]:
        """把入队超过 threshold_minutes 的 queued 任务批量标记为 timeout。
        返回被标记的任务列表(用于上层告警)。"""
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(minutes=threshold_minutes)
        with session_scope() as s:
            rows = (
                s.query(cls)
                .filter(cls.status == "queued", cls.queued_at < cutoff)
                .all()
            )
            for row in rows:
                row.status = "timeout"
                row.finished_at = datetime.now()
                row.error_msg = f"排队超过 {threshold_minutes} 分钟未启动"
            # 必须先 flush 把 UPDATE 推到 DB, 再 expunge 摘出 session,
            # 否则 expunge 后修改追踪丢失, UPDATE 不会落库。
            s.flush()
            for row in rows:
                s.expunge(row)
            return rows
