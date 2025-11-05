from typing import Dict, Any, Callable
from .types import ToolCall, ToolResult
from tools.calculator import Calculator
from tools.hello_echo import HelloEcho

ToolFn = Callable[[Dict[str, Any]], ToolResult]

class ToolRegistry:
    def __init__(self): self._tools: Dict[str, ToolFn] = {}
    def register(self, name: str, fn: ToolFn): self._tools[name] = fn
    def has(self, name: str) -> bool: return name in self._tools
    def call(self, call: ToolCall) -> ToolResult:
        if call.tool not in self._tools:
            return ToolResult(tool=call.tool, ok=False, content=f"unknown tool: {call.tool}")
        return self._tools[call.tool](call.args)

def default_registry() -> ToolRegistry:
    reg = ToolRegistry()

    # 툴 인스턴스 생성
    calc = Calculator()
    hello = HelloEcho()

    # 툴 등록
    reg.register("calculator", calc.calculator_tool)
    reg.register("hello", hello.hello_tool)
    reg.register("echo", hello.echo_tool)

    return reg

