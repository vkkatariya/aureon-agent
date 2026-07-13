import argparse
import os
import subprocess
import sys
from typing import Optional

from aureon_agent.config import AureonConfig, get_chat_id_from_update
from aureon_agent.tui import (
    print_banner,
    print_section,
    print_status,
    confirm,
    select,
    checkbox,
    text,
    password,
    print_table,
    spinner,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")
WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")

def get_skills_count() -> int:
    skills_dir = os.path.join(WORKSPACE_DIR, "skills")
    if not os.path.exists(skills_dir):
        return 0
    count = 0
    for item in os.listdir(skills_dir):
        if os.path.isdir(os.path.join(skills_dir, item)):
            skill_md = os.path.join(skills_dir, item, "SKILL.md")
            if os.path.exists(skill_md):
                count += 1
    return count

def run_systemd_setup():
    unit_dir = os.path.expanduser("~/.config/systemd/user")
    os.makedirs(unit_dir, exist_ok=True)
    unit_path = os.path.join(unit_dir, "aureon-agent.service")
    venv_python = os.path.join(BASE_DIR, ".venv", "bin", "python")
    
    unit_content = f"""# ~/.config/systemd/user/aureon-agent.service
[Unit]
Description=aureon-agent (Telegram + Discord personal AI agent)
After=network.target

[Service]
Type=simple
WorkingDirectory={BASE_DIR}
ExecStart={venv_python} -m aureon_agent
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
"""
    with open(unit_path, "w") as f:
        f.write(unit_content)
        
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "aureon-agent.service"], check=True)
    subprocess.run(["systemctl", "--user", "start", "aureon-agent.service"], check=True)

def step_existing_config(args) -> AureonConfig:
    exists = os.path.exists(ENV_PATH)
    
    if args.reset:
        if not args.non_interactive:
            if not confirm("Are you sure you want to completely reset your configuration?", default=False):
                print_status("Reset cancelled.", "warn")
                sys.exit(0)
        if exists:
            subprocess.run(["trash", ENV_PATH], check=False)
        return AureonConfig()

    if exists:
        config = AureonConfig.from_file(ENV_PATH)
        if args.non_interactive:
            print_status("Running in non-interactive mode. Existing config loaded.")
            return config
            
        print_section("Existing Configuration Detected", "You already have an .env file.")
        action = select(
            "What would you like to do?",
            choices=["Keep", "Modify", "Reset"],
            default="Keep"
        )
        if action == "Keep":
            return config
        elif action == "Modify":
            return config
        elif action == "Reset":
            if confirm("Are you sure you want to completely reset your configuration?", default=False):
                subprocess.run(["trash", ENV_PATH], check=False)
                return AureonConfig()
            else:
                return config
    else:
        return AureonConfig()

def step_model(config: AureonConfig, args):
    print_section("Model & LLM Provider", "Configure your Ollama endpoint and model.")
    
    if args.quick and config.OLLAMA_BASE_URL and config.OLLAMA_MODEL:
        print_status("Model config already set, skipping (--quick).")
        return
        
    if not args.non_interactive:
        config.OLLAMA_BASE_URL = text("Ollama Base URL:", default=config.OLLAMA_BASE_URL)
        
        has_api_key = bool(config.OLLAMA_API_KEY)
        needs_api_key = config.OLLAMA_BASE_URL.startswith("https://ollama.com")
        
        default_model = "minimax-m3" if needs_api_key else "minimax-m2.5:cloud"
        # Only override default if we are switching to cloud and had the local default
        if needs_api_key and config.OLLAMA_MODEL == "minimax-m2.5:cloud":
            config.OLLAMA_MODEL = default_model

        if needs_api_key:
            config.OLLAMA_API_KEY = password("Ollama API Key (required for cloud):")
        else:
            ask_key = confirm("Do you have an API key for this endpoint?", default=has_api_key)
            if ask_key:
                config.OLLAMA_API_KEY = password("Ollama API Key:")
            else:
                config.OLLAMA_API_KEY = None
                
        config.OLLAMA_MODEL = text("Ollama Model:", default=config.OLLAMA_MODEL)
    
    # Test connection
    import httpx
    try:
        with spinner("Testing Ollama connection..."):
            res = httpx.get(f"{config.OLLAMA_BASE_URL}/models", timeout=3)
            res.raise_for_status()
            print_status(f"Connected to Ollama successfully. Status: {res.status_code}")
    except Exception as e:
        print_status(f"Could not connect to Ollama: {e}", "warn")
        if not args.non_interactive:
            confirm("Proceed anyway?", default=True)

def step_telegram(config: AureonConfig, args):
    print_section("Telegram Channel", "Configure your primary communication channel.")
    
    if args.quick and config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_ALLOWED_CHATS:
        print_status("Telegram config already set, skipping (--quick).")
        return

    if not args.non_interactive:
        enable = confirm("Enable Telegram bot?", default=bool(config.TELEGRAM_BOT_TOKEN))
        if not enable:
            config.TELEGRAM_BOT_TOKEN = None
            return
            
        config.TELEGRAM_BOT_TOKEN = password("Telegram Bot Token:")
        if config.TELEGRAM_BOT_TOKEN:
            import httpx
            try:
                with spinner("Validating token..."):
                    res = httpx.get(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getMe").json()
                    if res.get("ok"):
                        print_status(f"Token valid. Bot: @{res['result']['username']}")
                    else:
                        print_status("Invalid Telegram bot token", "error")
            except Exception as e:
                print_status(f"Could not validate token: {e}", "warn")
                
            config.TELEGRAM_ALLOWED_CHATS = text("Allowed Chat IDs (comma-separated):", default=config.TELEGRAM_ALLOWED_CHATS)
            
            if not config.TELEGRAM_ALLOWED_CHATS:
                print_status("TELEGRAM_ALLOWED_CHATS is empty. All messages will be dropped.", "warn")
                chat_id = get_chat_id_from_update(config.TELEGRAM_BOT_TOKEN)
                if chat_id:
                    print_status(f"Found a recent chat ID: {chat_id}")
                    if confirm(f"Add {chat_id} to allowed chats?", default=True):
                        config.TELEGRAM_ALLOWED_CHATS = chat_id

def step_discord(config: AureonConfig, args):
    print_section("Discord Channel", "Configure secondary Discord bot.")
    
    if args.quick and config.DISCORD_BOT_TOKEN:
        print_status("Discord config already set, skipping (--quick).")
        return
        
    if not args.non_interactive:
        enable = confirm("Enable Discord bot?", default=bool(config.DISCORD_BOT_TOKEN))
        if enable:
            config.DISCORD_BOT_TOKEN = password("Discord Bot Token:")
        else:
            config.DISCORD_BOT_TOKEN = None

def step_daemon_skills(config: AureonConfig, args):
    print_section("Daemon & Skills", "System integration and capabilities.")
    
    if not args.non_interactive:
        if not args.quick or not config.HEALTH_PORT:
            hp = text("Health Check Port (blank to disable):", default=config.HEALTH_PORT)
            config.HEALTH_PORT = hp
            
        if not args.quick or not config.LOG_LEVEL:
            config.LOG_LEVEL = select("Log Level:", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default=config.LOG_LEVEL)
            
    count = get_skills_count()
    print_status(f"Found {count} skills in workspace/skills/")
    
    if sys.platform.startswith("linux") and not args.non_interactive:
        if confirm("Install systemd user service?", default=True):
            with spinner("Installing systemd unit..."):
                run_systemd_setup()
            print_status("systemd unit installed and started.")
            
            try:
                out = subprocess.check_output(["systemctl", "--user", "status", "aureon-agent.service", "--no-pager"], text=True)
                print(out)
            except subprocess.CalledProcessError as e:
                print(e.output)
            print_status("To view logs, run: journalctl --user -u aureon-agent.service -f")

def run_setup(args):
    print_banner()
    
    config = step_existing_config(args)
    
    if args.non_interactive:
        # Override config with cli args
        if args.telegram_bot_token: config.TELEGRAM_BOT_TOKEN = args.telegram_bot_token
        if args.telegram_allowed_chats: config.TELEGRAM_ALLOWED_CHATS = args.telegram_allowed_chats
        if args.discord_bot_token: config.DISCORD_BOT_TOKEN = args.discord_bot_token
        if args.ollama_base_url: config.OLLAMA_BASE_URL = args.ollama_base_url
        if args.ollama_api_key: config.OLLAMA_API_KEY = args.ollama_api_key
        if args.ollama_model: config.OLLAMA_MODEL = args.ollama_model
    
    sections = [s.strip() for s in args.section.split(',')]
    all_sections = "all" in sections
    
    try:
        if all_sections or "model" in sections:
            step_model(config, args)
        if all_sections or "channel" in sections:
            step_telegram(config, args)
            step_discord(config, args)
        if all_sections or "daemon" in sections or "skills" in sections:
            step_daemon_skills(config, args)
            
        config.save(ENV_PATH)
        print_status("Configuration saved successfully to .env")
        
        errors = config.validate()
        if errors:
            for err in errors:
                print_status(err, "warn")
                
        print_section("Next Steps")
        print("Run `aureon-agent doctor` to verify system health.")
        print("Run `aureon-agent start` to run the bot in the foreground.")
        
    except KeyboardInterrupt:
        print("\nSetup cancelled.")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Aureon Agent Setup Wizard")
    parser.add_argument("--quick", action="store_true", help="Only prompt for unset fields")
    parser.add_argument("--non-interactive", action="store_true", help="Run without TUI, uses defaults and env")
    parser.add_argument("--reset", action="store_true", help="Reset all configuration")
    parser.add_argument("--section", default="all", help="Comma-separated sections (model,channel,daemon,skills,all)")
    
    # Overrides for non-interactive
    parser.add_argument("--telegram-bot-token", help=argparse.SUPPRESS)
    parser.add_argument("--telegram-allowed-chats", help=argparse.SUPPRESS)
    parser.add_argument("--discord-bot-token", help=argparse.SUPPRESS)
    parser.add_argument("--ollama-base-url", help=argparse.SUPPRESS)
    parser.add_argument("--ollama-api-key", help=argparse.SUPPRESS)
    parser.add_argument("--ollama-model", help=argparse.SUPPRESS)
    
    args = parser.parse_args()
    run_setup(args)

if __name__ == "__main__":
    main()
