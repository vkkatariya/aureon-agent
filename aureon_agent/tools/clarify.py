import asyncio
import logging
from .log import log_tool_usage

logger = logging.getLogger(__name__)

async def clarify_tool(context: dict, question: str, options: list = None, timeout_sec: int = 300) -> str:
    """
    Ask the Captain a clarifying question before proceeding.
    Blocks the ReAct loop until an answer is received or timeout.
    """
    router = context.get("router")
    session_id = context.get("session_id")
    
    if not router or not session_id:
        return "Error: Missing router/session context."
        
    # Cap timeout
    if timeout_sec > 1800:
        timeout_sec = 1800
        
    # 1-per-iteration cap (we store iteration clarify count in context)
    iteration_clarifies = context.get("iteration_clarifies", 0)
    if iteration_clarifies >= 1:
        log_tool_usage("clarify", {"question": question}, "Blocked: 1-per-iteration cap", "error")
        return "Error: Only 1 clarification allowed per iteration."
        
    # 3-per-session cap (we store it in router to persist across turns)
    if not hasattr(router, "session_clarify_counts"):
        router.session_clarify_counts = {}
        
    session_clarifies = router.session_clarify_counts.get(session_id, 0)
    if session_clarifies >= 3:
        log_tool_usage("clarify", {"question": question}, "Blocked: 3-per-session cap", "error")
        return "Error: Reached the limit of 3 clarifications per session."
        
    # Increment counts
    context["iteration_clarifies"] = iteration_clarifies + 1
    router.session_clarify_counts[session_id] = session_clarifies + 1
    
    # Format message
    msg = f"❓ **Clarification Needed**\n{question}"
    if options:
        msg += "\n\nOptions:\n"
        for i, opt in enumerate(options, 1):
            msg += f"{i}. {opt}\n"
            
    try:
        await router.send_message(session_id, msg)
        
        future = asyncio.Future()
        
        if not hasattr(router, "pending_clarifications"):
            router.pending_clarifications = {}
            
        router.pending_clarifications[session_id] = future
        
        reply = await asyncio.wait_for(future, timeout=timeout_sec)
        
        log_tool_usage("clarify", {"question": question, "options": options}, "Received reply", "success")
        return reply
        
    except asyncio.TimeoutError:
        logger.warning(f"Clarification timed out after {timeout_sec}s.")
        log_tool_usage("clarify", {"question": question}, "Timed out", "timeout")
        return "" # Empty string and WARN per spec
    except Exception as e:
        logger.error(f"Error during clarification: {e}")
        log_tool_usage("clarify", {"question": question}, str(e), "error")
        return f"Error: {e}"
    finally:
        if hasattr(router, "pending_clarifications") and session_id in router.pending_clarifications:
            del router.pending_clarifications[session_id]
