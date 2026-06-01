from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class BizEnum(str, Enum):
    JD = "jd"
    GNJP = "gnjp"
    GJJP = "gjjp"
    HCP = "hcp"
    CAR = "car"
    SP = "sp"
    JS = "js"
    MEAL = "meal"
    COMMON = "common"
    USER = "user"
    ALL = "ALL"


class ActionEnum(str, Enum):
    IN1_OUT2 = "in1_out2"
    IN2_OUT1 = "in2_out1"
    DUAL = "dual"


class SwitchResponse(BaseModel):
    code: int
    task_id: Optional[str] = None
    oos_execution_id: Optional[str] = None
    biz: Optional[str] = None
    action: Optional[str] = None
    msg: str
    rollback_triggered: Optional[bool] = None
    rollback_result: Optional[str] = None
    detail: Optional[dict] = None


class ValidationResult(BaseModel):
    allowed: bool
    code: str = ""
    msg: str = ""
    detail: dict = {}


class ForceSwitchRequest(BaseModel):
    biz: BizEnum
    action: ActionEnum
    operator: str
    reason: str = Field(..., min_length=10, description="必须填写原因")
    ticket_id: Optional[str] = None


class ReleaseLockRequest(BaseModel):
    lock_key: str
    operator: str
    reason: str = Field(..., min_length=10)
