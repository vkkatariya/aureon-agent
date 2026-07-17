# Aureon Agent Setup Script

The `aureon-agent setup` wizard automates the installation and configuration of the Aureon Agent.

## Modes

- **Interactive (default):** A guided text-based user interface using `questionary` and `rich`. Prompts you for your model endpoints, API keys, Telegram/Discord tokens, and offers to install the systemd user service.
- **Quick (`--quick`):** Accelerates the setup by skipping fields that are already configured in `.env`.
- **Non-interactive (`--non-interactive`):** Designed for automation. Suppresses all prompts. Can be driven entirely by command-line arguments like `--telegram-bot-token` or by pre-existing environment variables.
- **Reset (`--reset`):** Wipes out the current configuration (`.env` file) and begins a fresh setup. Will ask for confirmation unless used with `--non-interactive`.

## Sections

The wizard is divided into logical sections that can be individually re-run using the `--section` flag:

- **model**: Ollama Base URL, API Key, and Model name.
- **channel**: Telegram and Discord bot tokens.
- **daemon**: Health check port and logging level configuration.
- **skills**: Validates and reports the loaded skills.

Example:
`aureon-agent setup --section channel` will only prompt you to update your bot tokens, leaving Ollama settings intact.

## Under the Hood

- Config values are stored in a plaintext `.env` file with `chmod 600` permissions.
- The `aureon_agent.config.AureonConfig` dataclass manages typing and validation.
- The `aureon-agent doctor` command acts as a comprehensive diagnostic suite, confirming Python version, dependency state, systemd service status, and reachable endpoints.
