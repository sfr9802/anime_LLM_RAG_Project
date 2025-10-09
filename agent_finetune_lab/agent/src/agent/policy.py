import re, json
from pydantic import BaseModel
from .types import ToolCall

SYSTEM_PROMPT = """너는 단계적 에이전트다.
- 도구가 필요 없으면 바로 답하고 마지막 줄에 'FINAL:'을 붙인다.
- 도구가 필요하면 아래 형식으로만 출력한다:
THOUGHT: (간단한 계획)
ACTION: {"tool": "<name>", "args": {...}}
"""

class Step(BaseModel):
    thought: str
    action: ToolCall | None = None
    observation: str | None = None

PAT = re.compile(r"(?s)^\s*THOUGHT:(.+?)(?:\n+ACTION:(.+))?$")

def parse_reply(text: str) -> Step:
    m = PAT.match(text.strip())
    if not m: return Step(thought=text)
    thought = m.group(1).strip()
    act_raw = (m.group(2) or "").strip()
    if not act_raw: return Step(thought=thought)
    try:
        d = json.loads(act_raw)
        return Step(thought=thought, action=ToolCall(tool=d["tool"], args=d.get("args", {})))
    except Exception:
        return Step(thought=thought, observation="ACTION parse error")

def should_stop(text: str) -> bool:
    return "FINAL:" in text
