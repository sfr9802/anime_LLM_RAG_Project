from config import Settings
from infra.llm_client import LLMClient
from .memory import ConversationMemory
from .tools import ToolRegistry, default_registry
from .policy import SYSTEM_PROMPT, parse_reply, should_stop

class Agent:
    def __init__(self, cfg: Settings, tools: ToolRegistry | None = None):
        self.cfg = cfg
        self.llm = LLMClient(cfg)
        self.mem = ConversationMemory()
        self.tools = tools or default_registry()

    async def run(self, task: str) -> str:
        self.mem.seed(SYSTEM_PROMPT)
        self.mem.add_user(task)
        for _ in range(self.cfg.max_steps):
            out = await self.llm.ask(self.mem.messages, self.cfg.temperature, max_tokens=512)
            self.mem.add_assistant(out)
            if should_stop(out): return out
            step = parse_reply(out)
            if step.action:
                res = self.tools.call(step.action)
                self.mem.add_tool(step.action.tool, step.observation or res.content)
                # TODO: 관찰 반영 프롬프트를 넣고 싶으면 여기에서 user 메시지로 유도
        return "FINAL: 최대 스텝 초과"
