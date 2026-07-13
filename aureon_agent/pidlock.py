"""PID lock helpers for aureon-agent.

Prevents two instances from running on the same workspace/data dir. The
lock is a file at `~/.cache/aureon-agent.pid` containing the running PID.
On startup we:
  1. Check if a stale PID file exists (process dead or PID not ours).
  2. If stale or no file, write our PID and proceed.
  3. If fresh and points to a live process that isn't us, exit with a
     clear error pointing at the existing instance.

The lock is also removed on clean shutdown (SIGINT/SIGTERM handlers) so
restarts work without manual cleanup.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

PID_PATH = Path(os.path.expanduser("~/.cache/aureon-agent.pid"))


def _pid_alive(pid: int) -> bool:
    """Return True if a process with this PID is alive and not a zombie."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but owned by another user — treat as alive.
        return True
    # /proc/<pid>/status line 3 is the State; Z = zombie. Defensive check.
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("State:"):
                    return "Z" not in line.split()[1]
    except (FileNotFoundError, IndexError):
        pass
    return True


def acquire_lock() -> Optional[int]:
    """Acquire the PID lock for the current process.

    Returns the live PID of the existing owner if another instance holds
    the lock, None if we acquired successfully.
    """
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    my_pid = os.getpid()

    if PID_PATH.exists():
        try:
            existing = int(PID_PATH.read_text().strip())
        except (ValueError, OSError):
            existing = 0
        if existing and existing != my_pid and _pid_alive(existing):
            return existing
        # Stale — remove and fall through to acquire.
        try:
            PID_PATH.unlink()
        except FileNotFoundError:
            pass

    # O_EXCL ensures we don't race with another process acquiring the same
    # path. If we lose the race, re-read and report the winner.
    try:
        fd = os.open(PID_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.write(fd, str(my_pid).encode())
        os.close(fd)
        return None
    except FileExistsError:
        try:
            winner = int(PID_PATH.read_text().strip())
        except (ValueError, OSError):
            winner = 0
        return winner if winner else -1


def release_lock() -> None:
    """Remove the PID file if it points at the current process. Safe to
    call on any path — never raises."""
    try:
        if PID_PATH.exists():
            content = PID_PATH.read_text().strip()
            if content == str(os.getpid()):
                PID_PATH.unlink()
    except (OSError, ValueError):
        pass


def install_signal_handlers(loop) -> None:
    """Wire SIGINT/SIGTERM to release the lock before exit."""
    import signal

    def _cleanup(*_args):
        release_lock()
        sys.exit(0)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _cleanup)
        except (NotImplementedError, RuntimeError):
            # add_signal_handler not available on some platforms; fall
            # back to default handler. release_lock still runs on normal
            # interpreter shutdown.
            pass
