import operator
from ..types import ToolResult

class Calculator:
    op_map = {
        "+": operator.add,
        "더하기": operator.add,
        "-": operator.sub,
        "빼기": operator.sub,
        "*": operator.mul,
        "곱하기": operator.mul,
        "/": lambda x, y: x / y if y != 0 else float("inf"),
        "나누기": lambda x, y: x / y if y != 0 else float("inf"),
        "^": operator.pow,
        "제곱": operator.pow
    }

    def calculator_tool(self, args: dict) -> ToolResult:
        x, y, op = args["x"], args["y"], args["op"]
        try:
            if op not in self.op_map:
                raise ValueError(f"지원하지 않는 연산자입니다: {op}")
            result = self.op_map[op](x, y)
            return ToolResult(tool="calculator", ok=True, content=str(result))
        except Exception as e:
            return ToolResult(tool="calculator", ok=False, content=str(e))
