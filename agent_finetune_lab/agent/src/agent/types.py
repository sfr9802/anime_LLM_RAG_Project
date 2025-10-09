from typing import Literal, Any, Dict
from pydantic import BaseModel

Role = Literal["system", "user", "assistant", "tool"]

class Message(BaseModel):
    role: Role
    content: str
    name: str | None = None  # tool 메시지용

class ToolCall(BaseModel):
    tool: str
    args: Dict[str, Any]

class ToolResult(BaseModel):
    tool: str
    ok: bool
    content: str  # 짧은 결과 텍스트
