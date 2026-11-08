"""Chat slash/bang commands shared by channel adapters: name -> aureon-agent CLI
subcommand (reused 1:1, no logic duplication)."""

SLASH_COMMANDS = {
    "sessions": ["sessions"],
    "doctor": ["doctor"],
    "status": ["status"],
    "version": ["version"],
    "mcp": ["mcp", "list"],
    "cron": ["cron", "list"],
    "logs": ["logs"],
    "skills": ["skills", "list"],
}
