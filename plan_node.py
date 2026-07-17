import os
import re
import logging
from typing import Tuple

logger = logging.getLogger(__name__)

plan_node_blocks_total = 0

IMPERATIVE_VERBS = {
    "build", "create", "fix", "add", "remove", "update", "implement", 
    "deploy", "test", "write", "refactor", "migrate"
}

CONJUNCTIONS = {
    "and", "then", "also", "plus", "after that", "next"
}

READONLY_KEYWORDS = {
    "show", "list", "display", "what is", "how many"
}

BYPASS_PHRASES = {
    "just do it", "skip the plan", "simple task"
}

URL_REGEX = re.compile(r"https?://\S+")
FILE_PATH_REGEX = re.compile(r"\b[\w\.\-]+/[\w\.\-/]+\b")

def count_features(text: str) -> int:
    text_lower = text.lower()
    
    # Check read-only
    for ro in READONLY_KEYWORDS:
        if re.search(r'\b' + re.escape(ro) + r'\b', text_lower):
            return 0 # Bypass
            
    count = 0
    words = text_lower.split()
    
    # Imperative verbs
    count += sum(1 for w in words if w.strip(".,!?:;") in IMPERATIVE_VERBS)
    
    # Conjunctions
    for c in CONJUNCTIONS:
        if c in text_lower:
            count += text_lower.count(c)
            
    # URLs
    count += len(URL_REGEX.findall(text))
    
    # File paths
    count += len(FILE_PATH_REGEX.findall(text))
    
    return count

def has_plan(workspace_dir: str) -> bool:
    paths = [
        os.path.join(workspace_dir, "tasks", "todo.md"),
        os.path.expanduser("~/.openclaw/workspace/tasks/todo.md")
    ]
    
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                if "- [ ]" in content:
                    return True
        except FileNotFoundError:
            continue
        except Exception as e:
            logger.warning(f"Error reading plan file {path}: {e}")
            # Fail open
            return True
            
    return False

def require_plan(workspace_dir: str, user_message: str) -> Tuple[bool, str]:
    text_lower = user_message.lower()
    
    # Check bypass
    for phrase in BYPASS_PHRASES:
        if phrase in text_lower:
            logger.warning(f"Plan bypass phrase used: '{phrase}'")
            return True, None
            
    features = count_features(user_message)
    if features < 3:
        return True, None
        
    if has_plan(workspace_dir):
        return True, None
        
    global plan_node_blocks_total
    plan_node_blocks_total += 1
    return False, "🛑 Plan needed. This task has 3+ steps but `tasks/todo.md` has no `- [ ]` items. Add a plan or say 'just do it' to bypass."
