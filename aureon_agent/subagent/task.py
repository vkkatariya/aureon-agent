from dataclasses import dataclass
from typing import Optional, List

@dataclass
class SubagentTask:
    description: str
    backend: str = "claude-code"
    timeout_sec: int = 300
    files_to_inspect: Optional[List[str]] = None

@dataclass
class SubagentResult:
    exit_code: int
    duration_sec: float
    token_count: int
    summary: str
    diff: str = ""
