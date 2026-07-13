import argparse
import asyncio
import os
import sys
import subprocess

from aureon_agent import __version__
from aureon_agent.cli import main as run_start
from aureon_agent.setup import main as run_setup
from aureon_agent.doctor import main as run_doctor
from aureon_agent.postinstall import main as run_postinstall

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")


def cmd_compaction_log(args):
    from compaction.log import CompactionLog
    from aureon_agent.tui import print_table

    async def _run():
        log = CompactionLog(os.path.join(DATA_DIR, "compaction_log.db"))
        await log.connect()
        try:
            runs = await log.list_recent(session_id=args.session, model=args.model, limit=args.last)
        finally:
            await log.close()
        if not runs:
            print("No compaction runs recorded.")
            return
        rows = [
            [r.session_id, f"{r.created_at:.0f}", str(r.tokens_before), str(r.tokens_after),
             r.model_used, str(r.context_window_used), r.status]
            for r in runs
        ]
        print_table(
            ["Session", "Created At", "Tokens Before", "Tokens After", "Model", "Context Window", "Status"],
            rows, title="Compaction Runs",
        )

    asyncio.run(_run())

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

    # compaction-log
    p_compaction_log = subparsers.add_parser("compaction-log", help="Show session compaction audit log")
    p_compaction_log.add_argument("--last", type=int, default=10, help="Number of runs to show (default 10)")
    p_compaction_log.add_argument("--session", default=None, help="Filter by session_id")
    p_compaction_log.add_argument("--model", default=None, help="Filter by model_used")

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
    elif args.command == "compaction-log":
        cmd_compaction_log(args)
    elif args.command == "version":
        cmd_version(args)

if __name__ == "__main__":
    main()
