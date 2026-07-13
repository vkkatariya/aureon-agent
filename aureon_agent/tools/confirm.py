import asyncio
import logging

logger = logging.getLogger(__name__)

async def confirm_with_captain(context: dict, prompt_text: str, timeout: int = 60) -> bool:
    """
    Ask the Captain for confirmation before executing a destructive or expensive operation.
    Requires passing the context containing `router`, `session_id`, etc.
    Default is deny (False) if timeout expires.
    """
    router = context.get("router")
    session_id = context.get("session_id")
    
    if not router or not session_id:
        logger.warning("confirm_with_captain called without router/session_id in context. Denying.")
        return False
        
    # We will register a pending clarification with the router
    # For now, we mock the logic since clarify tool is Tier 2, but the prompt says Tier 1 needs confirmation.
    # Wait, the prompt says "confirm_with_captain() helper for destructive/expensive ops (60s timeout, default = deny)."
    # Let's use the router's send_message and wait for reply.
    # The router might not have a wait_for_reply mechanism yet. We need to implement it in the router.
    
    try:
        # Ask question
        full_prompt = f"⚠️ **Confirmation Required**\n{prompt_text}\n\nReply 'yes' to proceed, or anything else to deny."
        await router.send_message(session_id, full_prompt)
        
        # Wait for reply via a future registered in router
        future = asyncio.Future()
        
        # We need the router to have a pending_confirmations dict: session_id -> future
        if not hasattr(router, "pending_confirmations"):
            router.pending_confirmations = {}
            
        router.pending_confirmations[session_id] = future
        
        # Wait with timeout
        reply = await asyncio.wait_for(future, timeout=timeout)
        
        # Check answer
        is_confirmed = reply.strip().lower() in ["yes", "y", "confirm", "proceed", "approve"]
        return is_confirmed
        
    except asyncio.TimeoutError:
        logger.warning(f"Confirmation timed out after {timeout}s.")
        return False
    except Exception as e:
        logger.error(f"Error during confirmation: {e}")
        return False
    finally:
        # Clean up future
        if hasattr(router, "pending_confirmations") and session_id in router.pending_confirmations:
            del router.pending_confirmations[session_id]
