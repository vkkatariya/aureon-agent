import argparse
import sys
import subprocess

from aureon_agent import __version__
from aureon_agent.cli import main as run_start
from aureon_agent.setup import main as run_setup
from aureon_agent.doctor import main as run_doctor
from aureon_agent.postinstall import main as run_postinstall

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

def cmd_version(args):
    print(f"aureon-agent v{__version__}")

def main():
    parser = argparse.ArgumentParser(description="aureon-agent CLI")
    subparsers = parser.add_subparsers(dest="command")
    
    # setup
    p_setup = subparsers.add_parser("setup", help="Interactive setup wizard")
    # Because setup has its own arguments, we parse known args or just delegate.
    # We will delegate the full sys.argv to setup.main later if chosen.
    
    # postinstall
    p_postinstall = subparsers.add_parser("postinstall", help="Bootstrap dependencies")
    
    # doctor
    p_doctor = subparsers.add_parser("doctor", help="Health checks")
    
    # start
    p_start = subparsers.add_parser("start", help="Run the agent in foreground (default)")
    
    # stop
    p_stop = subparsers.add_parser("stop", help="Stop the systemd service")
    
    # status
    p_status = subparsers.add_parser("status", help="Check systemd service status")
    
    # logs
    p_logs = subparsers.add_parser("logs", help="Tail systemd logs")
    
    # tool-log
    p_tool_log = subparsers.add_parser("tool-log", help="Show tool usage audit log")
    p_tool_log.add_argument("--last", type=int, default=10, help="Number of logs to show")
    
    # clarify-log
    p_clarify_log = subparsers.add_parser("clarify-log", help="Show clarification log")
    p_clarify_log.add_argument("--last", type=int, default=10, help="Number of logs to show")
    
    # version
    p_version = subparsers.add_parser("version", help="Print version")
    
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
    elif args.command == "version":
        cmd_version(args)

if __name__ == "__main__":
    main()
