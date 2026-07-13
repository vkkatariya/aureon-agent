import json
import os

# Key-value store for the AI agent
class Memory:
    def __init__(self, path="MEMORY.json"):
        self.path = path

        # Load existing memory from disk if available
        if os.path.exists(path):
            with open(path) as f:
                self._data = json.load(f)
        else:
            self._data = {} # Dictionary used to store user memories

    # Set a key-value pair
    def set(self, key, value):
        self._data[key] = value
        self._save()

    # Get a value by key
    def get(self, key):
        return self._data.get(key)

    # Get all keys
    def keys(self):
        return list(self._data.keys())

    # Save memory to disk
    def _save(self):
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2, default=str)