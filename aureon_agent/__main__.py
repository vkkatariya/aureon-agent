import argparse
import sys
import subprocess
import os

from aureon_agent import __version__
from aureon_agent.cli import main as run_start
from aureon_agent.cron_cli import cmd_cron, register_cron_subparser
from aureon_agent.setup import main as run_setup
from aureon_agent.doctor import main as run_doctor
from aureon_agent.postinstall import main as run_postinstall


def cmd_mcp_list(args):
    """List configured MCP servers and their tools."""
    import asyncio
    asyncio.run(_cmd_mcp_list_async())


async def _cmd_mcp_list_async():
    from dotenv import load_dotenv
    load_dotenv(override=True)

    from aureon_agent.cli import _parse_mcp_servers
    from aureon_agent.mcp_client import MCPManager
    from rich.console import Console
    from rich.table import Table

    console = Console()
    servers = _parse_mcp_servers()

    if not servers:
        console.print("[yellow]No MCP servers configured.[/yellow]")
        console.print("Set NOTION_TOKEN or GITHUB_MCP_TOKEN in .env to enable MCP servers.")
        return

    manager = MCPManager()
    table = Table(title="MCP Servers")
    table.add_column("Server", style="cyan")
    table.add_column("Status")
    table.add_column("Tools", justify="right")
    table.add_column("Tool Names")

    for cfg in servers:
        try:
            ok = await manager.add_server(**cfg)
            if ok:
                client = manager.clients[cfg["server_name"]]
                tool_names = [t["name"] for t in client.tools]
                table.add_row(
                    cfg["server_name"],
                    "[green]connected[/green]",
                    str(len(tool_names)),
                    ", ".join(tool_names) if tool_names else "—",
                )
            else:
                table.add_row(cfg["server_name"], "[red]failed[/red]", "0", "—")
        except Exception as e:
            table.add_row(cfg["server_name"], f"[red]error: {e}[/red]", "0", "—")

    console.print(table)
    await manager.disconnect_all()

def cmd_stop(args):
    subprocess.run(["systemctl", "--user", "stop", "aureon-agent.service"], check=False)

def cmd_status(args):
    try:
        out = subprocess.check_output(["systemctl", "--user", "status", "aureon-agent.service", "--no-pager"], text=True)
        print(out)
    except subprocess.CalledProcessError as e:
        print(e.output)

def cmd_logs(args):
    subprocess.run(["journalctl", "--user", "-u", "aureon-agent.service", "-f"])

def cmd_tool_log(args):
    from aureon_agent.tools.log import get_recent_tool_logs
    logs = get_recent_tool_logs(limit=args.last)
    if not logs:
        print("No tool logs found.")
        return
    
    from rich.console import Console
    from rich.table import Table
    console = Console()
    table = Table(title=f"Recent Tool Logs (Last {len(logs)})")
    table.add_column("ID")
    table.add_column("Timestamp")
    table.add_column("Tool")
    table.add_column("Inputs", overflow="fold")
    table.add_column("Result", overflow="fold")
    table.add_column("Exit/Status")
    table.add_column("Confirmed")
    
    for row in logs:
        inputs_str = row['inputs']
        if len(inputs_str) > 50:
            inputs_str = inputs_str[:47] + "..."
        result_str = row['result']
        if len(result_str) > 50:
            result_str = result_str[:47] + "..."
            
        table.add_row(
            str(row['id']),
            row['timestamp'],
            row['tool_name'],
            inputs_str,
            result_str,
            row['exit_status'],
            row['confirmation_status']
        )
    console.print(table)

def cmd_clarify_log(args):
    from aureon_agent.tools.log import get_recent_tool_logs
    # Fetch more logs and filter for clarify
    logs = [log for log in get_recent_tool_logs(limit=args.last * 10) if log['tool_name'] == 'clarify'][:args.last]
    if not logs:
        print("No clarify logs found.")
        return
    
    from rich.console import Console
    from rich.table import Table
    console = Console()
    table = Table(title=f"Recent Clarifications (Last {len(logs)})")
    table.add_column("ID")
    table.add_column("Timestamp")
    table.add_column("Inputs", overflow="fold")
    table.add_column("Result", overflow="fold")
    
    for row in logs:
        table.add_row(
            str(row['id']),
            row['timestamp'],
            row['inputs'],
            row['result']
        )
    console.print(table)

def cmd_subagent_log(args):
    from aureon_agent.subagent.log import get_recent_subagent_logs
    logs = get_recent_subagent_logs(limit=args.last)
    if not logs:
        print("No subagent logs found.")
        return
        
    from rich.console import Console
    from rich.table import Table
    console = Console()
    table = Table(title=f"Recent Subagent Dispatches (Last {len(logs)})")
    table.add_column("Task ID")
    table.add_column("Created At")
    table.add_column("Backend")
    table.add_column("Tokens")
    table.add_column("Duration")
    table.add_column("Status")
    table.add_column("Summary", overflow="fold")
    
    import datetime
    for row in logs:
        dt = datetime.datetime.fromtimestamp(row['created_at']).strftime('%Y-%m-%d %H:%M:%S')
        summary = row['result_summary']
        if len(summary) > 50:
            summary = summary[:47] + "..."
        table.add_row(
            row['task_id'],
            dt,
            row['backend'],
            str(row['token_count']),
            f"{row['duration_sec']:.1f}s",
            str(row['exit_code']),
            summary
        )
    console.print(table)

def cmd_version(args):
    print(f"aureon-agent v{__version__}")


def cmd_sessions(args):
    """List all chat sessions from sessions.db (channel:client_id, msg count, last active)."""
    import asyncio
    import time as _time

    from rich.console import Console
    from rich.table import Table

    from session_manager import SessionManager

    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(BASE_DIR, "data", "sessions.db")

    async def _run():
        sm = SessionManager(db_path)
        await sm.connect()
        try:
            return await sm.list_sessions()
        finally:
            await sm.close()

    sessions = asyncio.run(_run())
    console = Console()

    if not sessions:
        console.print("[yellow]No sessions found.[/yellow]")
        return

    table = Table(title="Chat Sessions")
    table.add_column("Session ID", style="cyan")
    table.add_column("Channel")
    table.add_column("Client")
    table.add_column("Msgs", justify="right")
    table.add_column("Last active")

    for s in sessions:
        updated = s.get("updated_at")
        last = _time.strftime("%Y-%m-%d %H:%M", _time.localtime(updated)) if updated else "—"
        table.add_row(
            s["session_id"],
            s.get("channel") or "—",
            s.get("client_id") or "—",
            str(s.get("msg_count", 0)),
            last,
        )
    console.print(table)

def main():
    parser = argparse.ArgumentParser(description="aureon-agent CLI")
    subparsers = parser.add_subparsers(dest="command")
    
    # setup
    subparsers.add_parser("setup", help="Interactive setup wizard")
    # Because setup has its own arguments, we parse known args or just delegate.
    # We will delegate the full sys.argv to setup.main later if chosen.
    
    # postinstall
    subparsers.add_parser("postinstall", help="Bootstrap dependencies")
    
    # doctor
    subparsers.add_parser("doctor", help="Health checks")
    
    # start
    subparsers.add_parser("start", help="Run the agent in foreground (default)")
    
    # stop
    subparsers.add_parser("stop", help="Stop the systemd service")
    
    # status
    subparsers.add_parser("status", help="Check systemd service status")
    
    # logs
    subparsers.add_parser("logs", help="Tail systemd logs")
    
    # tool-log
    p_tool_log = subparsers.add_parser("tool-log", help="Show tool usage audit log")
    p_tool_log.add_argument("--last", type=int, default=10, help="Number of logs to show")
    
    # clarify-log
    p_clarify_log = subparsers.add_parser("clarify-log", help="Show clarification log")
    p_clarify_log.add_argument("--last", type=int, default=10, help="Number of logs to show")
    
    # subagent-log
    p_subagent_log = subparsers.add_parser("subagent-log", help="Show subagent dispatch log")
    p_subagent_log.add_argument("--last", type=int, default=10, help="Number of logs to show")
    
    # cron (subcommand group)
    register_cron_subparser(subparsers)
    
    # mcp
    p_mcp = subparsers.add_parser("mcp", help="MCP server management")
    mcp_sub = p_mcp.add_subparsers(dest="mcp_command")
    mcp_sub.add_parser("list", help="List configured MCP servers and their tools")
    
    # version
    subparsers.add_parser("version", help="Print version")
    
    # sessions
    subparsers.add_parser("sessions", help="List all chat sessions")
    
    # If no args provided, default to 'start'
    if len(sys.argv) == 1:
        sys.argv.append("start")
        
    # We want to allow `aureon-agent setup --quick` to work easily.
    # To do this cleanly, if sys.argv[1] is setup, we modify sys.argv and call setup.main
    if sys.argv[1] == "setup":
        # sys.argv is ['aureon-agent', 'setup', '--quick'] -> ['setup', '--quick']
        sys.argv = [sys.argv[0] + " " + sys.argv[1]] + sys.argv[2:]
        run_setup()
        sys.exit(0)
    
    args = parser.parse_args()
    
    if args.command == "start":
        import asyncio
        asyncio.run(run_start())
    elif args.command == "doctor":
        run_doctor()
    elif args.command == "postinstall":
        run_postinstall()
    elif args.command == "stop":
        cmd_stop(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "logs":
        cmd_logs(args)
    elif args.command == "tool-log":
        cmd_tool_log(args)
    elif args.command == "clarify-log":
        cmd_clarify_log(args)
    elif args.command == "subagent-log":
        cmd_subagent_log(args)
    elif args.command == "cron":
        cmd_cron(args)
    elif args.command == "mcp":
        if hasattr(args, 'mcp_command') and args.mcp_command == "list":
            cmd_mcp_list(args)
        else:
            print("Usage: aureon-agent mcp list")
    elif args.command == "version":
        cmd_version(args)
    elif args.command == "sessions":
        cmd_sessions(args)

if __name__ == "__main__":
    main()
