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

    try:
        # Ask via inline keyboard (Yes/No buttons) — not a typed "yes" prompt,
        # which loops on headless boxes. Falls back to typed yes via the
        # pending_confirmations future resolved in router.handle_message.
        full_prompt = f"⚠️ **Confirmation Required**\n{prompt_text}\n\nTap ✅ Yes to proceed, or ❌ No to deny."
        confirm_data = "confirm_yes"
        cancel_data = "confirm_no"

        # Register the future BEFORE sending, so a fast tap isn't lost.
        future = asyncio.Future()
        if not hasattr(router, "pending_confirmations"):
            router.pending_confirmations = {}
        router.pending_confirmations[session_id] = future

        await router.send_confirmation(session_id, full_prompt, confirm_data, cancel_data)

        # Wait with timeout
        reply = await asyncio.wait_for(future, timeout=timeout)

        # Check answer (covers both inline-tap "yes"/"no" and typed fallback).
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
