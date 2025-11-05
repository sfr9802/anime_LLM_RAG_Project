from ..types import ToolResult

class HelloEcho:
    
    def hello(self) -> str:
        return "hello"
    
    def echo(self, txt: str) -> str:
        return txt
    
    def hello_tool(self, args: dict) -> ToolResult:
        return ToolResult(tool="hello", ok=True, content="hello")
    
    def echo_tool(self, args: dict) -> ToolResult:
        return ToolResult(tool="echo", ok=True, content=args.get("txt", ""))
