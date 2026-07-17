import asyncio
import os
from dotenv import load_dotenv

from memory import Memory
from session_manager import SessionManager
from skill_loader import SkillLoader
from agent_runtime import AgentRuntime
from telegram_channel import TelegramChannel

# Load environment variables
load_dotenv()

async def main():
    print("Tiny OpenClaw starting up...")

    # Create the Memory store
    memory = Memory()

    # Create the Session manager 
    sessions = SessionManager()

    # Load all Skills
    skills = SkillLoader()
    skills.load_from_directory(os.path.join(os.path.dirname(__file__), "skills"))

    # Create the agent runtime with LLM provider, model, and API key
    agent = AgentRuntime(
        provider = os.getenv("MODEL_PROVIDER"),
        model = os.getenv("MODEL_NAME"),
        api_key = os.getenv("ANTHROPIC_API_KEY"), # or os.getenv("OPENAI_API_KEY"),
        skills = skills,
        memory = memory,
    )

    # Create the Telegram channel and connect it to the agent and sessions
    telegram = TelegramChannel(
        token = os.getenv("TELEGRAM_BOT_TOKEN"),
        agent = agent,
        sessions = sessions,
    )

    print("\nTiny OpenClaw is running on Telegram.")
    print("\nGo CLAW! 🦞🦞🦞")

    # Start the Telegram bot 
    await telegram.start()

if __name__ == "__main__":
    asyncio.run(main())