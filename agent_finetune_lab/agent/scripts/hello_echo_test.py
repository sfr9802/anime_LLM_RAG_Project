from ..src.agent.toolkit import default_registry
from ..src.agent.types import ToolCall

def test_tool_calls():
    reg = default_registry()

    calls = [
        ToolCall(tool="hello", args={}),
        ToolCall(tool="echo", args={"txt": "hello world!"}),
        ToolCall(tool="calculator", args={"x": 7, "y": 3, "op": "*"}),
        ToolCall(tool="calculator", args={"x": 10, "y": 0, "op": "/"}),
        ToolCall(tool="not_real_tool", args={})
    ]

    for c in calls:
        res = reg.call(c)
        print(f"[{res.tool}] ok={res.ok} -> {res.content}")

if __name__ == "__main__":
    test_tool_calls()
