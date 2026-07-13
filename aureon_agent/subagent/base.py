from abc import ABC, abstractmethod
from .task import SubagentTask, SubagentResult
from .sandbox import Sandbox

class SubagentBackend(ABC):
    @abstractmethod
    async def dispatch(self, task: SubagentTask, sandbox: Sandbox) -> SubagentResult:
        """Execute the task in the provided sandbox."""
        pass
