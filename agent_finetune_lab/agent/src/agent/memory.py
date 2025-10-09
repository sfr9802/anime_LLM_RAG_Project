from typing import List
from .types import Message

class ConversationMemory:
    def __init__(self):
        self._msgs: List[Message] = []

    def seed(self, sys_prompt: str): self._msgs = [Message(role="system", content=sys_prompt)]
    def add_user(self, t: str): self._msgs.append(Message(role="user", content=t))
    def add_assistant(self, t: str): self._msgs.append(Message(role="assistant", content=t))
    def add_tool(self, name: str, t: str): self._msgs.append(Message(role="tool", name=name, content=t))
    @property
    def messages(self) -> List[Message]: return self._msgs
