import json
import os
import time

class SessionManager:
    def __init__(self, path="SESSIONS.json"):
        self.path = path

        # Load sessions from the disk if available
        if os.path.exists(path):
            with open(path) as f:
                self.sessions = json.load(f)
            print(f" Restored previous session(s) from disk!")
        else:
            self.sessions = {}

    # Find an existing session or create a new one 
    def get_or_create_session(self, client_id, channel):
        session_id = f"{channel}:{client_id}" 

        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "client_id": client_id,
                "channel": channel,
                "created_at": time.time(),
                "history": [],
            }

        return session_id

    # Append a message from user or LLM to the session history
    def add_message(self, session_id, message):
        session = self.sessions.get(session_id)
        if session:
            session["history"].append(message)
            self._save()

    # Return the full conversation history for a session to send to LLM as context on every turn 
    def get_history(self, session_id):
        session = self.sessions.get(session_id)
        return session["history"] if session else []

    # Save sessions to disk
    def _save(self):
        with open(self.path, "w") as f:
            json.dump(self.sessions, f, indent=2, default=str)