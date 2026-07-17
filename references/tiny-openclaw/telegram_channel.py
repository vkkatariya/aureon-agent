import time
import asyncio
from telegram import Update
from telegram.ext import Application, MessageHandler, filters

# Translates between Telegram Bot API and Tiny-OpenClaw
class TelegramChannel:
    def __init__(self, token, agent, sessions):
        self.token = token   # Telegram bot token from @BotFather
        self.agent = agent   # Agent runtime instance
        self.sessions = sessions # Session manager instance

    # Start polling Telegram for new messages
    async def start(self):
        # Build the Telegram bot app using the bot token
        app = Application.builder().token(self.token).build()

        # Listen for messages and route them to _on_message
        app.add_handler(MessageHandler(filters.TEXT, self._on_message))

        # Initialize the bot and start checking for new messages
        await app.initialize()
        await app.start()
        await app.updater.start_polling()

        # Keep the bot running forever
        await asyncio.Future()

    # Called every time a user sends a message to the bot
    async def _on_message(self, update: Update, context):
        # Get the sender's unique chat ID 
        chat_id = str(update.effective_chat.id)

        # Get the text the user sent
        user_text = update.message.text

        # Ignore empty messages
        if not user_text:
            return

        # Get or create one session per Telegram chat using chat_id as the user identifier
        session_id = self.sessions.get_or_create_session(chat_id, "telegram")

        # Save user message to session history
        self.sessions.add_message(session_id, {
            "role": "user",
            "content": user_text,
            "timestamp": time.time(),
        })

        # Show "typing..." indicator in Telegram chat
        await update.effective_chat.send_action("typing")

        try:
            # Get full conversation history for this user
            history = self.sessions.get_history(session_id)

            full_response = ""

           # Collect each word the agent generates into the full response
            async def on_token(token):
                nonlocal full_response
                full_response += token

        # Refresh typing indicator when the agent uses a tool
            async def on_tool_use(name, input):
                await update.effective_chat.send_action("typing")

            # Run the agent loop 
            await self.agent.run(history, session_id, {
                "on_token": on_token,
                "on_tool_use": on_tool_use,
            })

            # Send reply back to Telegram (split if over 4096 chars due to Telegram's limit)
            if full_response:
                for i in range(0, len(full_response), 4096):
                    await update.message.reply_text(full_response[i:i + 4096])

            # Save LLM response to session history
            self.sessions.add_message(session_id, {
                "role": "assistant",
                "content": full_response,
                "timestamp": time.time(),
            })

        # Send error message if something goes wrong
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")